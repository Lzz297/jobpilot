"""
config.py - 共享配置、常量、OpenAI client、文件追踪、emit 基础设施
"""
from openai import OpenAI
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    except Exception as e:
        emit(f"   ⚠️ 数据库查询异常: {e}")
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
    except Exception as e:
        emit(f"   ⚠️ 数据库查询异常: {e}")
        return []

# ── 密码哈希工具 ──

from werkzeug.security import check_password_hash

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

# ── 诊断模式（见 is_diagnose_mode() 函数，定义在 load_search_config_dict 之后）──

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
        "max_concurrency": 20,
        # 预留字段（暂不启用）:
        # "max_rpm": None,           # 每分钟最大请求数
        # "max_tpm": None,           # 每分钟最大 token 数
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "default_model": "qwen3.6-plus",
        "max_concurrency": 10,
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_env": "GLM_API_KEY",
        "default_model": "glm-5.1",
        "max_concurrency": 10,
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


_raw_client, MODEL_NAME = _init_llm_client()

# ── LangSmith 追踪（未安装时自动降级为裸 client）──
try:
    from langsmith import wrappers as _ls_wrappers
    client = _ls_wrappers.wrap_openai(_raw_client)
except ImportError:
    print("   ⚠️ langsmith 未安装，LangSmith 追踪已禁用。pip install langsmith 后重启生效。")
    client = _raw_client

# ── Instructor 实例线程本地缓存（构造后事实不可变，同一线程复用安全）──
_instructor_local = threading.local()


def _get_instructor_client():
    """获取当前线程的 Instructor 客户端（惰性创建 + 线程本地缓存）。

    Instructor 实例经源码审计确认为构造后事实不可变:
      - client / create_fn / mode / provider 均为只读
      - hooks 无注册 handler，emit() 是空操作
      - handle_kwargs() 只读不改
    因此同一线程复用是安全的，同时避免了每次 llm_call 重复创建的开销。
    """
    inst = getattr(_instructor_local, 'client', None)
    if inst is None:
        import instructor as _instructor
        _instructor_local.client = _instructor.from_openai(client)
    return _instructor_local.client


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
        if tools is not None:
            print(f"[llm_call] 警告: tools 和 response_model 同时传入，tools 将被忽略，使用 Instructor 模式")
        client_instruct = _get_instructor_client()
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
                if not _llm_raw_local.text and hasattr(msg, 'tool_calls') and msg.tool_calls:
                    func = msg.tool_calls[0].function
                    _llm_raw_local.text = getattr(func, 'arguments', '') or ''
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

    # 原地修改 _raw_client（wrapper 代理读取，立即生效）
    _raw_client.base_url = base_url
    _raw_client.api_key = api_key
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


def get_llm_concurrency() -> int:
    """获取当前 LLM provider 的并发限制。

    优先级:
      1. search_config 中 llm.max_concurrency 显式配置
      2. _LLM_PRESETS[provider].max_concurrency 默认值
      3. 兜底值 5

    上限 capped 在 200，防止配置错误导致客户端资源耗尽。
    """
    cfg, _ = load_search_config_dict()
    user_limit = (cfg or {}).get("llm", {}).get("max_concurrency")
    if user_limit is not None and isinstance(user_limit, int) and user_limit > 0:
        return min(user_limit, 200)

    provider = (cfg or {}).get("llm", {}).get("provider", "deepseek")
    preset = _LLM_PRESETS.get(provider, {})
    return preset.get("max_concurrency", 5)


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


def is_diagnose_mode() -> bool:
    """诊断模式开关。

    优先级:
      1. 环境变量 JOB_AGENT_DIAGNOSE 存在且为 1/true/yes/verbose → 强制 ON
      2. search_config.diagnose_mode 为 True → ON（管理员在 Web UI 设置）
      3. 以上均不满足 → OFF

    内置 5 秒 TTL 缓存，避免 _score_batch 每次调用都查 SQLite。
    """
    import time as _time
    global _diagnose_cache_time, _diagnose_cache_val
    now = _time.time()
    if now - _diagnose_cache_time < 5:
        return _diagnose_cache_val

    env_flag = os.getenv("JOB_AGENT_DIAGNOSE", "").strip() in ("1", "true", "yes", "verbose")
    if env_flag:
        _diagnose_cache_val = True
    else:
        cfg, _ = load_search_config_dict()
        _diagnose_cache_val = (cfg or {}).get("diagnose_mode", False)
    _diagnose_cache_time = now
    return _diagnose_cache_val


# 诊断模式缓存（由 is_diagnose_mode() 维护）
_diagnose_cache_time = 0.0
_diagnose_cache_val = False


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


# ── Token 用量追踪（线程安全，全局聚合）──
_usage_lock = threading.Lock()
_aggregated_input = 0
_aggregated_output = 0
_usage_local = threading.local()

# ── Per-call token 日志（预留持久化接口）──
#     每条 llm_call 完成后追加，主线程在 pipeline 结束后可读取。
#     当前仅内存存储；未来可扩展为 SQLite 批量写入。
_token_log: list[dict] = []
_token_log_lock = threading.Lock()

# ── LLM 原始返回文本（线程安全，供诊断使用）──
_llm_raw_local = threading.local()


def get_last_raw_response_text() -> str:
    """获取最近一次 Instructor 调用的 LLM 原始返回文本。用于诊断。"""
    return getattr(_llm_raw_local, 'text', '')


def get_last_usage() -> tuple[int, int]:
    """获取当前线程最近一次 LLM 调用的 token 用量 (input, output)。

    用于 per-batch 统计：_score_batch 在 llm_call 返回后调用，
    读取的是本次调用的精确 token 消耗，不会与其他线程混淆。
    """
    inp = getattr(_usage_local, 'last_input', 0)
    out = getattr(_usage_local, 'last_output', 0)
    return inp, out


def _store_usage(input_tokens: int, output_tokens: int) -> None:
    """存储 LLM token 用量（任意线程调用，线程安全）。

    同时写入三处:
      1. 线程本地 last_input/last_output — get_last_usage() 读取，per-batch 诊断
      2. 全局聚合器 — get_accumulated_usage() 读取，跨线程汇总
      3. Per-call 日志 — get_per_call_token_log() 读取，预留持久化
    """
    from datetime import datetime as _dt
    _usage_local.last_input = input_tokens
    _usage_local.last_output = output_tokens
    global _aggregated_input, _aggregated_output
    with _usage_lock:
        _aggregated_input += input_tokens
        _aggregated_output += output_tokens
    with _token_log_lock:
        _token_log.append({
            "ts": _dt.now().isoformat(),
            "input": input_tokens,
            "output": output_tokens,
        })


def clear_usage_accumulator() -> None:
    """清空全局 token 累加器和 per-call 日志。批量调用开始前由主线程调用。"""
    global _aggregated_input, _aggregated_output
    with _usage_lock:
        _aggregated_input = 0
        _aggregated_output = 0
    with _token_log_lock:
        _token_log.clear()


def get_accumulated_usage() -> dict:
    """获取全局累加的 token 总量并清零。

    run_batches_concurrently 返回后所有 worker 线程已 join，
    全局聚合器包含完整的跨线程 token 总和，不会遗漏或重复计数。
    """
    global _aggregated_input, _aggregated_output
    with _usage_lock:
        inp = _aggregated_input
        out = _aggregated_output
        _aggregated_input = 0
        _aggregated_output = 0
    return {"input_tokens": inp, "output_tokens": out}


def get_per_call_token_log() -> list[dict]:
    """获取 per-call token 日志列表的快照（不清空）。

    每条记录: {"ts": ISO时间戳, "input": int, "output": int}
    调用时机: pipeline 返回后（所有 worker 已 join），主线程读取。
    当前仅内存存储；预留为未来 SQLite 批量持久化的数据源。
    """
    with _token_log_lock:
        return list(_token_log)


def clear_token_log() -> None:
    """清空 per-call token 日志。通常由 clear_usage_accumulator 统一调用。"""
    with _token_log_lock:
        _token_log.clear()


def flush_token_log() -> int:
    """【预留】将 per-call token 日志写入 SQLite token_usage_log 表。

    当前为桩实现，仅返回记录数。未来实现时:
      1. 在 data/migrate.py 中创建 token_usage_log 表:
         CREATE TABLE IF NOT EXISTS token_usage_log (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             ts TEXT NOT NULL,
             input_tokens INTEGER NOT NULL,
             output_tokens INTEGER NOT NULL,
             stage TEXT,         -- 从调用上下文注入（当前 _store_usage 不感知）
             batch_label TEXT,   -- 同上
             provider TEXT,      -- 从 get_model_info() 读取
             model TEXT
         );
      2. 在 _store_usage 中注入上下文（阶段/批次标识）
      3. 在 match_jobs() 末尾调用本函数批量 INSERT
      4. 调用方负责在 pipeline 返回后调用（此时无并发写竞争）

    Returns:
        写入的记录数（当前返回 0，表示未写入）。
    """
    records = get_per_call_token_log()
    if not records:
        return 0
    # TODO: 批量 INSERT INTO token_usage_log
    # conn = _get_db()
    # conn.executemany("INSERT INTO token_usage_log (ts, input_tokens, output_tokens) VALUES (?, ?, ?)",
    #                  [(r["ts"], r["input"], r["output"]) for r in records])
    # conn.commit()
    # conn.close()
    return 0  # 当前为桩


def set_emit_target(queue):
    """设置当前线程的 emit 目标队列（Web 模式用）。传 None 清除。"""
    _emit_local.queue = queue


def emit(text):
    """输出信息：如果当前线程有 SSE 队列则推送，否则 print 到终端。"""
    q = getattr(_emit_local, "queue", None)
    if q is not None:
        q.put({"type": "progress", "text": str(text)})
    else:
        try:
            print(text)
        except UnicodeEncodeError:
            # Windows GBK 编码不支持部分 Unicode 字符（如 emoji）
            # 用 sys.stdout 直接写入，绕过 print 的编码检查
            import sys
            sys.stdout.buffer.write((str(text) + '\n').encode('utf-8'))
            sys.stdout.buffer.flush()


def get_session_files():
    """获取并清空本轮生成的文件列表（Web 模式用）。"""
    global _session_files
    files = []
    for fp, desc in _session_files:
        try:
            rel = os.path.relpath(fp, OUTPUT_DIR)
        except ValueError:
            rel = fp
        files.append((rel, desc))
    _session_files = []
    return files


# ============================================================
#  通用并发执行器
# ============================================================

def run_batches_concurrently(
    tasks: list[callable],
    max_workers: int = 10,
    description: str = "LLM 批次",
) -> list:
    """并发执行一批无依赖的任务，返回按原始顺序排列的结果列表。

    行为约定:
      - tasks=[] → 返回 []
      - len(tasks)==1 或 max_workers<=1 → 退化为串行（不经线程池）
      - 单个任务抛异常 → 对应位置为 None，不影响其他任务
      - 全部失败 → 返回 [None, ...]，emit 告警
      - 部分失败 → 返回混合列表，emit 统计

    线程安全保证:
      - 使用 ThreadPoolExecutor + as_completed
      - with 块退出时 executor.shutdown(wait=True) 确保所有线程 join
      - 调用方在返回后可安全访问全局聚合器（如 token 统计）
      - 自动将调用线程的 emit target (SSE queue) 传播到 worker 线程
    """
    if not tasks:
        return []

    total = len(tasks)

    if total == 1 or max_workers <= 1:
        try:
            return [tasks[0]()]
        except Exception as e:
            emit(f"   ⚠️ {description} 执行失败: {e}")
            return [None]

    results = [None] * total
    failed = 0
    actual_workers = min(max_workers, total)

    # 捕获调用线程的 emit target，传播到 worker 线程
    # （_emit_local 是 threading.local，worker 线程默认看不到 pipeline 线程设置的 queue）
    parent_queue = getattr(_emit_local, "queue", None)

    def _wrap_task(task):
        def _wrapped():
            if parent_queue is not None:
                _emit_local.queue = parent_queue
            return task()
        return _wrapped

    emit(f"   🚀 {description}: {total} 个任务并发执行（最大 {actual_workers} 并发）")

    with ThreadPoolExecutor(max_workers=actual_workers) as executor:
        future_to_idx = {executor.submit(_wrap_task(task)): i for i, task in enumerate(tasks)}

        completed = 0
        last_reported_pct = 0

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            completed += 1
            try:
                results[idx] = future.result()
            except Exception as e:
                failed += 1
                emit(f"   ⚠️ {description} #{idx + 1} 失败: {e}")
                results[idx] = None

            # 里程碑式进度报告（25% 步进），避免乱序消息过多
            pct = completed * 100 // total
            if pct >= last_reported_pct + 25 or completed == total:
                msg = f"   📊 {description}进度: {completed}/{total} ({pct}%)"
                if failed:
                    msg += f"，{failed} 失败"
                emit(msg)
                last_reported_pct = pct - (pct % 25)

    if failed == total:
        emit(f"   ❌ 所有 {total} 个{description}任务均失败，请检查 LLM 连接")
    elif failed > 0:
        emit(f"   ⚠️ {description}: {failed}/{total} 个任务失败")

    return results


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
