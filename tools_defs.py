"""
tools_defs.py - 工具 JSON 定义、tool_map、执行逻辑
"""
from config import emit, get_campaign_config
import json

from tools_basic import (
    get_current_time,
    write_file,
    read_file,
    list_files,
    web_search,
    load_user_profile,
    load_search_config,
    fetch_job_detail,
)
from job_search import search_jobs
from job_match import match_jobs, list_matched_jobs
from resume_gen import generate_resume
from market_analysis import analyze_market, batch_analyze_market


# ============================================================
#  工具清单（OpenAI function calling 格式）
# ============================================================

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前日期和时间",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "创建或写入文件到 output 目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "文件名，如 note.txt"},
                    "content": {"type": "string", "description": "文件内容"}
                },
                "required": ["filename", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取 output 目录中的文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "文件名"}
                },
                "required": ["filename"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出当前 run 目录和 market 目录中的文件",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索，可搜索任何网上信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "max_results": {"type": "integer", "description": "返回数量，默认5"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "load_user_profile",
            "description": "读取用户个人档案(profiles/me.yaml)，包含技能、经历、求职意向等信息",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "load_search_config",
            "description": "读取搜索策略配置(profiles/search_config.yaml)",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": "三层漏斗搜索：扫描JobsDB列表页→规则过滤→抓取完整JD。可选传 sort_by 参数切换排序方式（默认从配置读取）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sort_by": {
                        "type": "string",
                        "enum": ["relevance", "date"],
                        "description": "排序方式：\"relevance\"（按相关度排序，JobsDB默认）或 \"date\"（按发布时间排序，最新在前）。默认从 search_config.yaml 的 sort_mode 读取，未配置则按 date。"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "match_jobs",
            "description": "对最近一次搜索到的岗位做多维度匹配分析。从技能、经验、职级、行业、加分项5个维度评分，生成详细排名报告。",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_resume",
            "description": "多模式简历生成（MD → PDF）。支持3种模式：(1) 传 by_direction=true 基于匹配数据按方向批量生成（需先 search + match）；(2) 传 job_index 基于匹配岗位生成；(3) 传 jd_text 基于用户粘贴的JD生成。参数都是可选的，根据用户意图选择一种传入。",
            "parameters": {
                "type": "object",
                "properties": {
                    "by_direction": {
                        "type": "boolean",
                        "description": "设为 true 时，基于匹配数据按方向（payment/solutions/web3/technical）批量生成简历。需要先执行过 search_jobs + match_jobs。会聚合各方向的 JD 共性需求，生成数据驱动的方向通用简历。"
                    },
                    "job_index": {
                        "type": "integer",
                        "description": "匹配排名中的岗位编号（从1开始）。需要先执行过 match_jobs。"
                    },
                    "jd_text": {
                        "type": "string",
                        "description": "用户粘贴的完整职位描述(JD)文本，用于直接基于该JD生成定制简历"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_matched_jobs",
            "description": "查看最近一次匹配分析的结果列表，包含多维度评分详情",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_job_detail",
            "description": "抓取单个岗位URL的完整职位描述(JD)，包括职责、要求、技术栈、薪资等。用于查看某个感兴趣岗位的完整信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "岗位详情页URL，如 https://hk.jobsdb.com/job/12345678"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_market",
            "description": "独立市场调研工具：指定岗位类别（如 Java Developer、Web3、AI-Agent 等），主动搜索 JobsDB 并分析该类岗位的技能需求排名、薪资行情、经验要求、行业分布等市场行情。可选差距分析（对比个人画像）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_category": {
                        "type": "string",
                        "description": "岗位类别关键词，必须严格保留用户输入的原始大小写，不得修改。如用户说 'Web3' 就传 'Web3'，不要改成 'web3'。"
                    },
                    "location": {
                        "type": "string",
                        "description": "搜索地点，默认 Hong Kong"
                    },
                    "include_gap_analysis": {
                        "type": "boolean",
                        "description": "是否包含个人差距分析（对比个人画像与市场需求），默认 true"
                    },
                    "classification": {
                        "type": "string",
                        "description": "JobsDB 行业分类标签（可选），必须保留原始大小写和拼写，如 'science-technology'、'banking-financial-services'。不填则搜索全部行业"
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["relevance", "date"],
                        "description": "排序方式：\"relevance\"（按相关度排序）或 \"date\"（按发布时间排序，最新在前）。默认从 search_config.yaml 的 sort_mode 读取。"
                    }
                },
                "required": ["job_category"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "batch_analyze_market",
            "description": "批量市场分析：一次性分析多个岗位类别，依次执行，每完成一个自动开始下一个。适用于用户同时提交多个岗位的市场调研需求。",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "description": "岗位列表，每项包含 category（岗位关键词）和可选的 classification（行业分类）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "category": {
                                    "type": "string",
                                    "description": "岗位类别关键词，必须严格保留用户输入的原始大小写，不得修改"
                                },
                                "classification": {
                                    "type": "string",
                                    "description": "JobsDB 行业分类标签（可选），如 'information-communication-technology'"
                                }
                            },
                            "required": ["category"]
                        }
                    },
                    "location": {
                        "type": "string",
                        "description": "搜索地点，默认 Hong Kong"
                    },
                    "include_gap_analysis": {
                        "type": "boolean",
                        "description": "是否包含个人差距分析，默认 true"
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["relevance", "date"],
                        "description": "排序方式：\"relevance\"（按相关度排序）或 \"date\"（按发布时间排序，最新在前）。默认从 search_config.yaml 的 sort_mode 读取。"
                    }
                },
                "required": ["tasks"]
            }
        }
    },
]


# ============================================================
#  工具映射
# ============================================================

tool_map = {
    "get_current_time": get_current_time,
    "write_file": write_file,
    "read_file": read_file,
    "list_files": list_files,
    "web_search": web_search,
    "load_user_profile": load_user_profile,
    "load_search_config": load_search_config,
    "search_jobs": search_jobs,
    "match_jobs": match_jobs,
    "generate_resume": generate_resume,
    "list_matched_jobs": list_matched_jobs,
    "fetch_job_detail": fetch_job_detail,
    "analyze_market": analyze_market,
    "batch_analyze_market": batch_analyze_market,
}


# ============================================================
#  工具执行
# ============================================================

# ── 需要系统层注入 config 的工具集合 ──
_CONFIG_AWARE_TOOLS = {
    "search_jobs",
    "match_jobs",
}


def execute_tool(tool_call):
    """执行工具调用"""
    func_name = tool_call.function.name
    args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}

    emit(f"   → 调用工具: {func_name}")
    if args:
        emit(f"   → 参数: {args}")

    func = tool_map.get(func_name)
    if not func:
        return f"错误：未知工具 {func_name}"

    # ── 系统层注入 campaign config ──
    if func_name in _CONFIG_AWARE_TOOLS:
        cfg = get_campaign_config()
        if cfg is not None:
            if "config" in args:
                emit(f"   ⚠️ [系统] LLM 传入了 config 参数，已被系统配置覆盖")
            args["config"] = cfg
            # match_jobs 还需要 user_profile
            if func_name == "match_jobs":
                if "profile" not in args:
                    args["profile"] = cfg.get("user_profile")

    try:
        result = func(**args) if args else func()
    except Exception as e:
        result = f"工具执行出错: {str(e)}"

    preview = result[:300] + "..." if len(result) > 300 else result
    emit(f"   → 结果: {preview}")
    return result


def deduplicate_tool_calls(tool_calls):
    """去除重复的工具调用"""
    seen = set()
    unique = []
    for tc in tool_calls:
        key = f"{tc.function.name}:{tc.function.arguments}"
        if key not in seen:
            seen.add(key)
            unique.append(tc)
        else:
            emit(f"   ⚠️ 跳过重复调用: {tc.function.name}")
    return unique
