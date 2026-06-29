"""
config.py - 共享配置、常量、OpenAI client、文件追踪、emit 基础设施
"""
from openai import OpenAI
from dotenv import load_dotenv
import os
import json
import yaml
import threading
import sqlite3

load_dotenv()

# ── 数据库连接（SQLite）──
_db_path = os.path.join(os.path.dirname(__file__), "data", "job_agent.db")

def _get_db():
    """获取数据库连接（每次调用创建新连接，线程安全）"""
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    return conn

def _db_fetch_one(query, params=()):
    """执行查询并返回单行 dict，无结果或异常返回 None"""
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None

def _db_fetch_all(query, params=()):
    """执行查询并返回所有行（list of dict），无结果或异常返回 []"""
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []

# ── 密码哈希工具 ──

from werkzeug.security import generate_password_hash, check_password_hash

def set_user_password(username, password):
    """设置或更新用户密码。返回 True 成功，False 用户不存在。"""
    try:
        pw_hash = generate_password_hash(password)
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash = ? WHERE username = ?", (pw_hash, username))
        if cursor.rowcount == 0:
            conn.close()
            return False
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def verify_user_password(username, password):
    """验证用户密码。返回 (True, user_dict) 或 (False, None)。"""
    row = _db_fetch_one("SELECT * FROM users WHERE username = ? AND is_active = 1", (username,))
    if not row or not row["password_hash"]:
        return False, None
    if check_password_hash(row["password_hash"], password):
        return True, dict(row)
    return False, None

# ── 常量 ──
PROFILES_DIR = "profiles"
OUTPUT_DIR = "output"

# ── OpenAI client 占位（在 load_yaml 定义后初始化） ──
client = None
MODEL_NAME = "deepseek-v4-pro"

# ── 本轮生成文件追踪 ──
_session_files = []


def track_file(filepath, description):
    """记录本轮生成的文件"""
    _session_files.append((filepath, description))


def print_session_summary():
    """打印本轮文件总览并清空"""
    global _session_files
    if not _session_files:
        return
    emit(f"\n{'='*60}")
    emit(f"  📦 本轮生成文件总览（共 {len(_session_files)} 个）")
    emit(f"{'='*60}")
    for i, (fp, desc) in enumerate(_session_files, 1):
        abs_path = os.path.abspath(fp)
        size = ""
        if os.path.exists(fp):
            s = os.path.getsize(fp)
            if s < 1024:
                size = f" ({s:,} bytes)"
            else:
                size = f" ({s/1024:.1f} KB)"
        emit(f"  {i}. 📄 {desc}")
        emit(f"     → {abs_path}{size}")
    emit(f"{'='*60}\n")
    _session_files = []


# ── YAML 加载工具 ──

def load_yaml(filename, directory=PROFILES_DIR):
    """加载 YAML 文件，返回 (dict, None) 或 (None, error_msg)"""
    filepath = os.path.join(directory, filename)
    if not os.path.exists(filepath):
        return None, f"错误：{filepath} 不存在"
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f), None


# ── LLM 动态初始化 ──

_LLM_PRESETS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-v4-pro",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "default_model": "qwen3.6-plus",
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_env": "GLM_API_KEY",
        "default_model": "glm-5.1",
    },
}


def _init_llm_client():
    """从 SQLite search_config 表读取 llm 配置，创建 OpenAI client"""
    try:
        cfg, _ = load_search_config_dict()
        llm_cfg = (cfg or {}).get("llm", {})
    except Exception:
        llm_cfg = {}

    provider = llm_cfg.get("provider", "deepseek")
    preset = _LLM_PRESETS.get(provider, _LLM_PRESETS["deepseek"])

    base_url = llm_cfg.get("base_url", preset["base_url"])
    api_key_env = llm_cfg.get("api_key_env", preset["api_key_env"])
    model_name = llm_cfg.get("model", preset["default_model"])

    api_key = os.getenv(api_key_env) or "sk-placeholder"
    return OpenAI(api_key=api_key, base_url=base_url), model_name


client, MODEL_NAME = _init_llm_client()


# ============================================================
#  统一 LLM 调用入口（所有模块通过此函数调用，不直接使用 client）
# ============================================================

def llm_call(messages, *, temperature=None, tools=None, max_retries=2, thinking=None, response_model=None):
    """调用 LLM，自动处理限流重试、超时、服务端错误。

    返回 message 对象（含 .content 和 .tool_calls 属性）。
    调用方可以直接 msg.content 取文本、msg.tool_calls 取工具调用。
    当 response_model 不为 None 时，使用 Instructor 模式，返回 Pydantic 模型实例。

    V4 模型 thinking 默认开启。需要确定性输出时传入 thinking={"type": "disabled"}，
    此时 temperature 参数正常运行。thinking 开启时不传 temperature（会被忽略）。

    可重试的错误（429/超时/连接/5xx）：指数退避，最多 max_retries 次。
    不可重试的错误（401/403/400）：直接抛出，不浪费等待时间。
    """
    import time
    from openai import RateLimitError, APITimeoutError, APIConnectionError, APIStatusError

    # ── Instructor 模式：response_model 不为 None 时走 Pydantic 结构化返回 ──
    if response_model is not None:
        import instructor as _instructor
        if tools is not None:
            print(f"[llm_call] 警告: tools 和 response_model 同时传入，tools 将被忽略，使用 Instructor 模式")
        client_instruct = _instructor.from_openai(client)
        kwargs_instruct = {}
        if thinking is not None:
            kwargs_instruct["extra_body"] = {"thinking": thinking}
        result, raw_completion = client_instruct.chat.completions.create_with_completion(
            model=MODEL_NAME,
            messages=messages,
            temperature=temperature if temperature is not None else 1.0,
            response_model=response_model,
            max_retries=max_retries,
            **kwargs_instruct
        )
        # Token 用量
        if hasattr(raw_completion, 'usage') and raw_completion.usage:
            _store_usage(raw_completion.usage.prompt_tokens, raw_completion.usage.completion_tokens)
        # 存储原始返回文本供诊断使用（线程安全）
        try:
            choices = getattr(raw_completion, 'choices', [])
            if choices:
                msg = choices[0].message
                _llm_raw_local.text = getattr(msg, 'content', '') or ''
            if not _llm_raw_local.text:
                emit(f"[诊断raw] choices count={len(choices)}")
                if choices:
                    emit(f"[诊断raw] message keys={list(choices[0].message.__dict__.keys()) if hasattr(choices[0].message, '__dict__') else dir(choices[0].message)}")
                    emit(f"[诊断raw] content={repr(choices[0].message.content)}")
        except Exception as e:
            emit(f"[诊断raw] 异常: {e}")
        return result

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            kwargs = {"model": MODEL_NAME, "messages": messages}
            if tools is not None:
                kwargs["tools"] = tools
            if thinking is not None:
                kwargs["extra_body"] = {"thinking": thinking}
            # V4 thinking mode ignores temperature; only pass when thinking is disabled
            if thinking is None or thinking.get("type") == "disabled":
                if temperature is not None:
                    kwargs["temperature"] = temperature

            response = client.chat.completions.create(**kwargs)
            if hasattr(response, 'usage') and response.usage:
                _store_usage(response.usage.prompt_tokens, response.usage.completion_tokens)
            return response.choices[0].message

        except RateLimitError as e:
            last_error = e
            if attempt < max_retries:
                wait = min(2 ** attempt, 30)
                emit(f"   ⚠️ LLM 限流 (429)，{wait}s 后重试 ({attempt + 1}/{max_retries})...")
                time.sleep(wait)

        except (APITimeoutError, APIConnectionError) as e:
            last_error = e
            if attempt < max_retries:
                wait = min(2 ** attempt, 30)
                emit(f"   ⚠️ LLM 调用失败 ({type(e).__name__})，{wait}s 后重试 ({attempt + 1}/{max_retries})...")
                time.sleep(wait)

        except APIStatusError as e:
            if e.status_code >= 500 and attempt < max_retries:
                last_error = e
                wait = min(2 ** attempt, 30)
                emit(f"   ⚠️ LLM 服务端错误 ({e.status_code})，{wait}s 后重试 ({attempt + 1}/{max_retries})...")
                time.sleep(wait)
            else:
                raise

    raise last_error


def switch_model(provider, model=None):
    """运行时切换 LLM 提供商，原地修改 client 属性使全局立即生效"""
    global MODEL_NAME

    preset = _LLM_PRESETS.get(provider, _LLM_PRESETS["deepseek"])
    model = model or preset["default_model"]
    api_key_env = preset["api_key_env"]
    base_url = preset["base_url"]

    api_key = os.getenv(api_key_env)
    if not api_key:
        return {"error": f"环境变量 {api_key_env} 未设置"}

    # 原地修改 client（所有模块持有同一个引用，立即生效）
    client.base_url = base_url
    client.api_key = api_key
    MODEL_NAME = model

    # 更新 SQLite search_config 表
    try:
        cfg_dict, _ = load_search_config_dict()
        if cfg_dict:
            cfg_dict["llm"] = {"provider": provider, "model": model}
            conn = _get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE search_config SET data = ?, updated_at = CURRENT_TIMESTAMP",
                           (json.dumps(cfg_dict, ensure_ascii=False),))
            conn.commit()
            conn.close()
    except Exception:
        pass  # SQL 更新失败不阻塞，内存 client 已切换

    return {"provider": provider, "model": MODEL_NAME}


def get_model_info():
    """返回当前模型信息和可选列表"""
    try:
        cfg, _ = load_search_config_dict()
        llm_cfg = (cfg or {}).get("llm", {})
    except Exception:
        llm_cfg = {}
    current_provider = llm_cfg.get("provider", "deepseek")
    return {
        "current_provider": current_provider,
        "current_model": MODEL_NAME,
        "presets": {k: v["default_model"] for k, v in _LLM_PRESETS.items()},
    }


def get_current_user():
    """
    读取当前活跃的用户名。
    从 SQLite user_profiles 表查询 is_current=1 的记录。
    """
    row = _db_fetch_one(
        "SELECT u.username FROM user_profiles p JOIN users u ON p.user_id = u.id WHERE p.is_current = 1"
    )
    if row:
        return row["username"]
    raise RuntimeError("无法确定当前用户：数据库无活跃画像")


def load_profile():
    """
    加载当前活跃用户的画像。
    从 SQLite user_profiles 表读取 is_current=1 的 data 字段（JSON）。
    """
    import json as _json
    row = _db_fetch_one(
        "SELECT data FROM user_profiles WHERE is_current = 1"
    )
    if row:
        try:
            return _json.loads(row["data"])
        except _json.JSONDecodeError:
            pass
    raise RuntimeError("无法加载用户画像：数据库无活跃画像数据")


def load_search_config_dict():
    """
    加载系统配置。
    从 SQLite search_config 表读取 data 字段（JSON）。
    返回 (dict, None) 或 (None, error_msg)，保持与 load_yaml 相同的返回值格式。
    """
    import json as _json
    row = _db_fetch_one("SELECT data FROM search_config LIMIT 1")
    if row:
        try:
            return _json.loads(row["data"]), None
        except _json.JSONDecodeError:
            pass
    return None, "系统配置读取失败：数据库无配置数据"


# ── JSON 解析工具 ──

def parse_json_response(text):
    """从 LLM 回复中提取 JSON（兼容 markdown code block 包裹）"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


# ============================================================
#  Emit 基础设施（支持 terminal print 和 web SSE 双模式）
# ============================================================

_emit_local = threading.local()

# ── Campaign 配置管理（线程安全）──
_campaign_local = threading.local()


def set_campaign_config(cfg: dict) -> None:
    """设置当前线程的 campaign 配置。CLI 入口调用，Web 端暂不调用。"""
    _campaign_local.config = cfg


def get_campaign_config() -> dict | None:
    """获取当前线程的 campaign 配置。没有则返回 None。"""
    return getattr(_campaign_local, 'config', None)


# ── Token 用量追踪（线程安全）──
_usage_local = threading.local()

# ── LLM 原始返回文本（线程安全，供诊断使用）──
_llm_raw_local = threading.local()


def get_last_raw_response_text() -> str:
    """获取最近一次 Instructor 调用的 LLM 原始返回文本。用于诊断。"""
    return getattr(_llm_raw_local, 'text', '')


def _store_usage(input_tokens: int, output_tokens: int) -> None:
    """存储最近一次 LLM 调用的 token 用量，并自动累加到 batch 总和（内部使用）"""
    _usage_local.last_input = input_tokens
    _usage_local.last_output = output_tokens
    _usage_local.batch_input = getattr(_usage_local, 'batch_input', 0) + input_tokens
    _usage_local.batch_output = getattr(_usage_local, 'batch_output', 0) + output_tokens


def get_last_usage() -> dict | None:
    """获取最近一次 LLM 调用的 token 用量。无数据返回 None。"""
    inp = getattr(_usage_local, 'last_input', 0)
    out = getattr(_usage_local, 'last_output', 0)
    if inp == 0 and out == 0:
        return None
    return {"input_tokens": inp, "output_tokens": out}


def clear_last_usage() -> None:
    """清空最近一次 token 记录。每次独立 LLM 调用前使用，防止异常时串台。"""
    _usage_local.last_input = 0
    _usage_local.last_output = 0


def clear_usage_accumulator() -> None:
    """清空累加器。批量调用开始前使用。"""
    _usage_local.batch_input = 0
    _usage_local.batch_output = 0


def get_accumulated_usage() -> dict:
    """获取累加的总 token 用量并自动清零。"""
    inp = getattr(_usage_local, 'batch_input', 0)
    out = getattr(_usage_local, 'batch_output', 0)
    _usage_local.batch_input = 0
    _usage_local.batch_output = 0
    return {"input_tokens": inp, "output_tokens": out}


def set_emit_target(queue):
    """设置当前线程的 emit 目标队列（Web 模式用）。传 None 清除。"""
    _emit_local.queue = queue


def emit(text):
    """输出信息：如果当前线程有 SSE 队列则推送，否则 print 到终端。"""
    q = getattr(_emit_local, "queue", None)
    if q is not None:
        q.put({"type": "progress", "text": str(text)})
    else:
        print(text)


def get_session_files():
    """获取并清空本轮生成的文件列表（Web 模式用）。"""
    global _session_files
    files = [(os.path.abspath(fp), desc) for fp, desc in _session_files]
    _session_files = []
    return files


# ============================================================
#  Run 管理（按次归档输出文件）
# ============================================================

_current_run_dir = None


def start_new_run():
    """创建新的 run 目录，返回路径。每次搜索调用一次。"""
    global _current_run_dir
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _current_run_dir = os.path.join(OUTPUT_DIR, f"run_{ts}")
    os.makedirs(_current_run_dir, exist_ok=True)
    return _current_run_dir


def get_current_run_dir():
    """获取当前 run 目录。无活跃 run 时返回 None。"""
    return _current_run_dir


def get_latest_run_dir():
    """查找最近一次 run 目录（按文件名排序）。"""
    if not os.path.exists(OUTPUT_DIR):
        return None
    runs = sorted([d for d in os.listdir(OUTPUT_DIR)
                   if d.startswith("run_") and os.path.isdir(os.path.join(OUTPUT_DIR, d))])
    if not runs:
        return None
    return os.path.join(OUTPUT_DIR, runs[-1])


# ============================================================
#  Prompt 模板加载 & 渲染
# ============================================================

_prompts_cache = None


def load_prompts():
    """加载 profiles/prompts.yaml 并缓存。文件不存在时返回空 dict（各调用点回退到硬编码默认值）。"""
    global _prompts_cache
    if _prompts_cache is not None:
        return _prompts_cache
    data, _ = load_yaml("prompts.yaml")
    _prompts_cache = data if data else {}
    return _prompts_cache


def render_prompt(tpl, **kwargs):
    """将 prompt 模板中的 <key> 占位符替换为实际值。

    使用尖括号而非花括号，避免与 JSON 示例中的 {} 冲突，
    让 prompts.yaml 中的 JSON 保持原样，方便非程序员编辑。
    """
    for key, value in kwargs.items():
        tpl = tpl.replace(f"<{key}>", str(value))
    return tpl


def get_system_prompt():
    """返回 Agent 系统提示词。唯一来源为 prompts.yaml，缺失时报错。"""
    prompts = load_prompts()
    prompt = prompts.get("agent", {}).get("system_prompt")
    if not prompt:
        raise RuntimeError("agent.system_prompt 在 prompts.yaml 中缺失或为空")
    return prompt
