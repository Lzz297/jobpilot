"""
config.py - 共享配置、常量、OpenAI client、文件追踪、emit 基础设施
"""
from openai import OpenAI
from dotenv import load_dotenv
import os
import json
import yaml
import threading

load_dotenv()

# ── 常量 ──
PROFILES_DIR = "profiles"
OUTPUT_DIR = "output"

# ── OpenAI client 占位（在 load_yaml 定义后初始化） ──
client = None
MODEL_NAME = "deepseek-chat"

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
        "default_model": "deepseek-chat",
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
    """从 search_config.yaml 读取 llm 配置，创建 OpenAI client"""
    try:
        cfg, _ = load_yaml("search_config.yaml")
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

def llm_call(messages, *, temperature=None, tools=None, max_retries=2):
    """调用 LLM，自动处理限流重试、超时、服务端错误。

    返回 message 对象（含 .content 和 .tool_calls 属性）。
    调用方可以直接 msg.content 取文本、msg.tool_calls 取工具调用。

    可重试的错误（429/超时/连接/5xx）：指数退避，最多 max_retries 次。
    不可重试的错误（401/403/400）：直接抛出，不浪费等待时间。
    """
    import time
    from openai import RateLimitError, APITimeoutError, APIConnectionError, APIStatusError

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            kwargs = {"model": MODEL_NAME, "messages": messages}
            if tools is not None:
                kwargs["tools"] = tools
            if temperature is not None:
                kwargs["temperature"] = temperature

            response = client.chat.completions.create(**kwargs)
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

    # 同步更新 yaml（只替换 llm 段的 provider 和 model，保留注释和其他内容）
    import re
    filepath = os.path.join(PROFILES_DIR, "search_config.yaml")
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r'(provider:\s*)\S+', rf'\g<1>{provider}', text, count=1)
    text = re.sub(r'(model:\s*)\S+', rf'\g<1>{model}', text, count=1)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(text)

    return {"provider": provider, "model": MODEL_NAME}


def get_model_info():
    """返回当前模型信息和可选列表"""
    try:
        cfg, _ = load_yaml("search_config.yaml")
        llm_cfg = (cfg or {}).get("llm", {})
    except Exception:
        llm_cfg = {}
    current_provider = llm_cfg.get("provider", "deepseek")
    return {
        "current_provider": current_provider,
        "current_model": MODEL_NAME,
        "presets": {k: v["default_model"] for k, v in _LLM_PRESETS.items()},
    }


def load_profile():
    """加载 profiles/me.yaml，返回 (dict, None) 或 (None, error_msg)"""
    return load_yaml("me.yaml")


def load_search_config_dict():
    """加载 profiles/search_config.yaml，返回 (dict, None) 或 (None, error_msg)"""
    return load_yaml("search_config.yaml")


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
#  Agent 系统 Prompt（供 agent.py 和 web_app.py 共用）
# ============================================================

SYSTEM_PROMPT = """你是一个专业的求职助手 Agent，帮助用户在 JobsDB 上寻找合适的工作并生成简历。

⚠️ 重要：用户的个人信息保存在配置文件中，不需要通过对话询问。

🔄 标准求职流程：
1. search_jobs → 三层漏斗搜索：扫描列表页→基础清洗→全量抓取完整JD
   * 排序控制：可选传 sort_by="date" 按发布时间（最新在前），传 sort_by="relevance" 按相关度排序
2. match_jobs → 自动从技能、经验、职级、行业、加分项5个维度做匹配评分
3. generate_resume → 多模式简历生成（MD → PDF）

📋 你的工具列表：
- get_current_time: 获取当前时间
- write_file / read_file / list_files: 文件操作
- web_search: 联网搜索
- load_user_profile: 查看用户档案
- load_search_config: 查看搜索配置
- search_jobs: 三层漏斗搜索 JobsDB 岗位。可选参数 sort_by="date"（按发布时间，最新在前）或 "relevance"（按相关度），默认从配置读取
- match_jobs: 多维度匹配分析（动态权重 + 及格线复评，无需参数）
- generate_resume: 多模式简历生成，支持以下5种方式：
    ① 传 by_direction=true → 基于匹配数据按方向批量生成（需先 search + match，批量投递首选）
    ② 传 job_index → 基于匹配排名中的某个岗位定制生成
    ③ 传 jd_text → 基于用户粘贴的 JD 文本直接生成（无需搜索流程）
    ④ 传 role_direction → 基于岗位方向生成（如 "Solutions Engineer 方向"，无需搜索数据）
    ⑤ 不传参数 → 基于用户画像生成通用简历
- list_matched_jobs: 查看匹配结果列表
- fetch_job_detail: 抓取单个岗位 URL 的完整 JD（传入 URL）
- analyze_market: 独立市场调研，指定岗位类别主动搜索并分析（技能需求、薪资、经验要求、差距分析）。可选参数 sort_by="date" 或 "relevance"

📝 简历生成场景路由：
- 用户说「按方向生成简历」或「批量生成简历」→ generate_resume(by_direction=true)
- 用户说「为第X个生成简历」→ generate_resume(job_index=X)
- 用户贴了一段 JD 说「根据这个生成简历」→ generate_resume(jd_text="用户贴的内容")
- 用户说「帮我生成 Solutions Engineer 方向的简历」→ generate_resume(role_direction="Solutions Engineer")
- 用户说「帮我生成一份通用简历」→ generate_resume()（不传参数）

📊 市场分析场景路由：
⚠️ 关键词大小写敏感！用户输入什么就原样传入，绝对不要修改大小写或拼写。classification 同理。
- 用户问「Java Developer 市场行情」→ analyze_market(job_category="Java Developer")  ← 保持原样
- 用户问「Web3 岗位薪资水平」→ analyze_market(job_category="Web3")  ← 不要改成 web3
- 用户问「AI Agent Developer 需要什么技能」→ analyze_market(job_category="AI Agent Developer")
- 用户说「分析后端开发市场，不需要差距分析」→ analyze_market(job_category="Backend Developer", include_gap_analysis=false)
- 用户说「分析 science-technology 行业的 Solutions Engineer」→ analyze_market(job_category="Solutions Engineer", classification="science-technology")
- 用户说「按相关度排序分析 Web3 市场」→ analyze_market(job_category="Web3", sort_by="relevance")
- 用户说「按最新发布分析 Java 市场行情」→ analyze_market(job_category="Java Developer", sort_by="date")

当用户说「帮我找工作」或类似意思时，依次调用 search_jobs → match_jobs → generate_resume(by_direction=true)。
当用户想看某个具体岗位详情时，调用 fetch_job_detail。
当用户问某类岗位的市场行情、技能需求、薪资水平时，调用 analyze_market。
每个工具每次只调用一次，不要重复。
用中文回答。

在展示匹配结果时，重点说明每个岗位的：
- 多维度分数（技能/经验/职级/行业/加分项）
- 权重方案和置信度（如有复评信息）
- 技能匹配详情（哪些匹配、哪些缺失）
- 具体的建议"""


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
    """返回 Agent 系统提示词，优先从 prompts.yaml 读取，缺失时回退到硬编码默认值。"""
    prompts = load_prompts()
    return prompts.get("agent", {}).get("system_prompt", SYSTEM_PROMPT)
