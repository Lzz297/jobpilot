# JobsDB 智能求职 Agent — 项目完整介绍

> 一个基于 LLM + 工具调用架构的全自动求职系统，覆盖「职位搜索 → 智能筛选 → 匹配评分 → 简历生成 → 市场调研」完整链路。支持终端 CLI 和 Web UI 两种交互模式。

---

## 一、项目概述

### 1.1 项目定位

本项目是一个 **AI Agent 驱动的自动化求职助手**，面向香港 JobsDB 市场，自动完成以下流程：

1. **职位搜索** — 从 JobsDB 批量抓取职位信息（Playwright 无头浏览器 + 4 层解析回退）
2. **基础清洗** — 排除空标题 + 排除指定公司，不经过 LLM 预过滤
3. **匹配评分** — 从技能、经验、职级、行业、加分项 5 个维度评分（LLM 动态权重 + 及格线复评）
4. **简历生成** — 3 种模式 × 三语（英/繁中/简中）× 质量自检，每次产出 7 个文件
5. **市场调研** — 独立模块：指定岗位类别 → 全量抓取 → LLM 分析 11+ 个市场维度 → 差距分析 → 报告生成

### 1.2 技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| 编程语言 | Python 3.13 | 主开发语言 |
| LLM | DeepSeek / Qwen / GLM（可配置切换） | 通过 OpenAI SDK 兼容接口调用，`config.py` 中的 `llm_call()` 为统一入口 |
| LLM 调用层 | `llm_call()` 统一入口（P0 重构） | 所有 24 处 LLM 调用点收敛到一个函数，内建指数退避重试（429/5xx/超时/连接）、错误分类、不可重试错误（401/403）直接抛出。支持 `thinking` 模式（DeepSeek V4）和 `response_model` 模式（Instructor + Pydantic 结构化输出） |
| 结构化输出 | Instructor（Pydantic schema 校验） | 市场分析 Phase B/C 和评估脚本 `score_single_jd()` 走 Instructor 模式，自动校验 LLM 输出结构并重试修正。匹配评分主路径 `_score_batch()` 使用 JSON 解析后 Pydantic 校验模式 |
| 网页抓取 | Playwright 无头浏览器 | JobsDB 对所有 requests 请求返回 403，已全面切换 Playwright |
| HTML 解析 | BeautifulSoup (lxml) + JSON | BS4 做 DOM 辅助解析，核心数据来自页面内嵌 `__NEXT_DATA__` JSON |
| PDF 渲染 | Playwright/Chromium | Markdown → HTML → PDF，两个独立浏览器实例（爬虫 + 渲染器各一个） |
| 网络搜索 | DuckDuckGo (ddgs) | 联网搜索 |
| Web 框架 | Flask + SSE | Web UI 服务器，SSE 实时进度推送 |
| 前端 | 原生 HTML/CSS/JS（单页应用） | Web UI，通过 SSE 实时推送进度，支持对话模式和快捷操作模式 |
| 配置管理 | YAML | 用户画像、搜索策略、Prompt、简历模板/指南均为 YAML |
| 环境管理 | python-dotenv | API Key 通过 `.env` 文件管理 |

### 1.3 项目结构

```text
D:\job-agent/
│
├── agent.py                  # [入口] Agent 主循环 — 终端对话交互 + 工具调用循环
├── web_app.py                # [入口] Flask Web UI — SSE 实时推送 + 直接流水线模式
├── config.py                 # [配置中心] llm_call() 统一入口、LLM Client 管理、YAML 加载、
│                             #            JSON 解析、文件追踪、emit 双模式输出、Prompt 模板引擎
├── tools_defs.py             # [工具注册] 14 个工具的 JSON Schema 定义 + 执行分发 + 去重
├── tools_basic.py            # [基础工具] 时间/文件/搜索/配置查看/单岗位抓取
│
├── scraper.py                # [爬虫] JobsDB 页面抓取（~1031 行），4 层列表解析 + 3 层详情解析
├── job_search.py             # [搜索] 三层漏斗搜索（扫描 → 基础清洗 → 全量抓取 JD）
├── job_match.py              # [匹配] LLM 五维评分 + 动态权重 + 及格线复评 + 方向分类
├── resume_gen.py             # [简历] 5 模式生成 + 方向聚合 + 英文先行 + 三语翻译 + 质量自检
├── checker.py                # [核查] 简历 bullet 事实核查 — 检测数字矛盾、强度升级、占位符
├── pdf_renderer.py           # [渲染] Markdown → HTML → PDF（独立 Playwright 实例）
├── market_analysis.py        # [市场] 四阶段市场调研 + 多批聚合 + 差距分析 + 批量分析
├── config_assembler.py       # [组装] Campaign 配置三层组装（user × strategy × campaign）
│
├── engine/                   # [契约] Pydantic 数据模型（6 个文件）
│   ├── contracts/            #     14 个 Pydantic 模型
│   │   ├── match_result.py   #       MatchResult + Scores
│   │   ├── market_result.py  #       MarketAnalysisResult + TechnicalSkill
│   │   ├── gap_result.py     #       GapAnalysisResult + 4 个子模型
│   │   ├── resume.py         #       Resume + ResumeBullet
│   │   ├── direction_result.py #     DirectionAggregationResult + CommonRequirements
│   │   └── review_result.py  #       ResumeReviewResult
│
├── evaluation/               # [评估] Prompt 评估脚本 + 数据集
│   ├── run_eval.py           #     匹配评分评估
│   ├── run_checker_eval.py   #     Checker 用例评估
│   └── split_eval.py         #     训练集/验证集拆分
│
├── instances/                # [实例] 新配置架构（三层组合）
│   ├── campaigns/            #     Campaign 定义（用户 + 策略 + 搜索词组合）
│   ├── strategies/           #     策略文件（权重方案 + 关键词规则）
│   ├── users/                #     用户画像（按用户拆分）
│   └── eval/                 #     评估数据集 + 标注规范
│
├── prompts/                  # [示例] Prompt 模板示例
│   └── examples/job_match/   #     各方向的评分 prompt 示例
│
├── profiles/                 # [配置文件目录] 系统基础设施配置
│   ├── search_config.yaml    #     LLM 配置 + 过滤 + 市场参数 + user 字段（业务配置已迁移至 instances/）
│   ├── search_config_fast.yaml #   快速测试用配置
│   ├── prompts.yaml          #     15 个 LLM prompt 模板
│   ├── resume_template.yaml  #     简历模板
│   └── resume_guide.yaml     #     简历撰写指南
│
├── static/
│   ├── index.html            #     Web UI 前端（单页应用）
│   └── index_old.html        #     旧版 UI 备份（Phase 1 改造前）
│
├── new-ui/                   # [Demo] PM 交付的 UI 原型（独立交互演示）
│   └── index.html            #     Demo 原型
│
├── tests/                    # [测试] Playwright 自动化测试套件
│   ├── conftest.py           #     Fixture 层（配置管理、DeepSeek 切换）
│   ├── full_regression_v2.py #     全量回归测试（40 用例）
│   └── screenshots/diffs/    #     灰度 diff 图输出目录
│
├── output/                   # [输出目录]
│   ├── run_{timestamp}/      #     每次"找工作"的输出
│   │   ├── scan_listings.json
│   │   ├── rejected_jobs.json
│   │   ├── filter_stats.json
│   │   ├── raw_jobs.json
│   │   ├── matched_jobs.json
│   │   ├── unmatched_jobs.json
│   │   ├── job_report.md
│   │   ├── direction_analysis.json
│   │   └── resumes/
│   └── market/               #     市场调研输出
│
├── .env                      # API Key
├── CONFIG_GUIDE.md           # 配置文件详细说明
├── PROMPT_CHANGE_PROCESS.md  # Prompt 修改流程与评估规范
├── .claude/                  # Claude Code 工作文件
└── .venv/                    # Python 虚拟环境
```

---

## 二、系统架构

### 2.1 整体架构：双入口 + 统一 LLM 调用层

```text
┌──────────────────────────────────────────────────┐
│                    入口层                          │
│  ┌──────────────┐          ┌──────────────┐       │
│  │  agent.py    │          │  web_app.py   │       │
│  │  (终端 CLI)  │          │  (Flask Web)  │       │
│  └──────┬───────┘          └──────┬───────┘       │
│         │                         │                │
│         │    ┌────────────────────┤                │
│         │    │  /api/chat         │                │
│         │    │  (LLM Agent 模式)  │                │
│         │    │                    │                │
│         │    │  /api/pipeline     │                │
│         │    │  (直接流水线模式)   │                │
│         ▼    ▼                    │                │
│  ┌─────────────────────────────────────────┐      │
│  │              config.py                   │      │
│  │  ┌──────────────────────────────────┐   │      │
│  │  │  llm_call()  统一 LLM 调用入口    │   │      │
│  │  │  · 24 处调用点全部收敛到这里      │   │      │
│  │  │  · 指数退避重试（429/超时/5xx）  │   │      │
│  │  │  · 错误分类（不可重试直接抛出）   │   │      │
│  │  │  · 3 Provider 运行时切换         │   │      │
│  │  └──────────────────────────────────┘   │      │
│  │  emit() 双模式输出 + JSON 解析 + Prompt  │      │
│  └────────────────────┬────────────────────┘      │
│                       │                            │
│                       ▼                            │
│  ┌─────────────────────────────────────────┐      │
│  │            tools_defs.py                 │      │
│  │  14 个工具的 JSON Schema + 分发 + 去重  │      │
│  └────────────────────┬────────────────────┘      │
│                       │                            │
│     ┌──────────┬──────┼──────┬──────────┐         │
│     ▼          ▼      ▼      ▼          ▼         │
│  tools_     job_   job_   resume_   market_       │
│  basic     search  match   gen     analysis       │
│     │          │      │      │          │         │
│     │      scraper.py │  pdf_renderer.py          │
│     ▼          ▼      ▼      ▼          ▼         │
│  [控制台/  [output/  [output/  [output/ [output/  │
│   SSE]     run_*/]  run_*/]  run_*/] market/]     │
└──────────────────────────────────────────────────┘
```

**两种运行时模式**：

| 触发方式 | 入口 | 特点 |
|---------|------|------|
| `python agent.py --campaign <name>` | 终端 CLI | 交互式对话，LLM 决定工具调用顺序。必须指定 Campaign |
| `python web_app.py` → Web 按钮 | `/api/pipeline` | 直接调用 search→match→resume 三步函数，不经过 LLM 决策，更快 |
| `python web_app.py` → Web 对话框 | `/api/chat` | 同 CLI 模式，LLM Agent 决策，通过 SSE 推送进度 |

### 2.2 llm_call() — 统一 LLM 调用入口（P0 重构）

所有模块的 LLM 调用不再直接使用 `client.chat.completions.create()`，而是通过 `config.py` 中的 `llm_call()` 函数：

```python
llm_call(messages, *, temperature=None, tools=None, max_retries=2, thinking=None, response_model=None)
# 默认模式：返回 message 对象（含 .content 和 .tool_calls 属性）
# Instructor 模式（response_model 不为 None）：返回 Pydantic 模型实例，附带 ._usage 属性
```

**参数说明**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `messages` | list | — | 对话消息列表 |
| `temperature` | float | `None` | `None` 时不传（使用 API 默认 1.0）；`0` 时显式传递（确定性任务） |
| `tools` | list | `None` | Function Calling 工具定义列表 |
| `max_retries` | int | `2` | 可重试错误的最大重试次数 |
| `thinking` | dict | `None` | DeepSeek V4 思考模式：`{"type": "disabled"}` 关闭。开启时不传 `temperature`（会被忽略） |
| `response_model` | Pydantic | `None` | 传入 Pydantic 模型后走 Instructor 结构化输出模式，自动校验 + 重试修正。此时 `tools` 参数被忽略 |

**错误处理策略**：

| 错误类型 | 行为 |
|----------|------|
| 429 Rate Limit | 指数退避重试（wait = min(2^attempt, 30)，即 1s → 2s），最多 `max_retries` 次（默认 2 次） |
| 超时 (APITimeoutError) | 同上 |
| 连接中断 (APIConnectionError) | 同上 |
| 5xx 服务端错误 | 同上 |
| 401 / 403 认证错误 | 直接抛出，不重试 |
| 400 请求错误 | 直接抛出，不重试 |
| 所有重试耗尽 | 抛出最后一个异常，由调用方现有 `except` 块捕获 |

**设计要点**：
- `temperature` 参数为 `None` 时不传给 API（使用默认值 1.0，用于简历生成等创造性任务）
- `temperature=0` 时显式传递（用于匹配评分、市场分析等确定性任务）
- `tools` 参数为 `None` 时不传（纯文本分析类调用不需要工具）
- 所有 24 处调用点已收敛，新增任何 LLM 功能（如 token 统计、缓存、fallback）只需改这一处

### 2.3 核心工作流

```text
用户说「帮我找工作」→ Agent 自动执行三步流水线：

search_jobs()  →  match_jobs()  →  generate_resume(by_direction=True)
     │                  │                    │
     ▼                  ▼                    ▼
三层漏斗抓取      五维匹配评分         方向聚合 + 三语简历 PDF
(扫描→清洗→JD)  (动态权重+复评)     (英文先行→审查→翻译)
```

---

## 三、模块详解

### 3.1 config.py — 共享配置中心

**职责**：LLM 调用统一入口、多 Provider 管理、YAML 加载、JSON 解析、文件追踪、emit 双模式输出、Run 目录管理、Prompt 模板引擎、Campaign 配置管理。

#### 3.1.1 llm_call() — 统一 LLM 调用入口

见 §2.2。

#### 3.1.2 多 Provider LLM 管理

```python
_LLM_PRESETS = {
    "deepseek": {"base_url": "https://api.deepseek.com", "default_model": "deepseek-v4-pro"},
    "qwen":     {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen3.6-plus"},
    "glm":      {"base_url": "https://open.bigmodel.cn/api/paas/v4", "default_model": "glm-5.1"},
}
```

- `switch_model(provider, model)`：运行时切换 LLM，原地修改全局 `client` 的 `base_url` 和 `api_key`（所有模块持有同一引用，立即生效），同时回写 `search_config.yaml`
- `get_model_info()`：返回当前 provider、model 及所有可选预设列表
- 启动时从 `search_config.yaml` 的 `llm` 段读取配置，支持自定义 `base_url` 和 `api_key_env`

#### 3.1.3 emit 双模式输出

```python
def emit(text):
    if 当前线程绑定了 SSE 队列:
        推送到 SSE 队列  # Web 模式
    else:
        print(text)       # 终端模式
```

通过 `threading.local()` 实现线程隔离。Web 模式下每个请求线程独立绑定 SSE 队列。

#### 3.1.4 JSON 解析器（多层容错）

```python
def parse_json_response(text):
    # 策略 1：去除 ```json ``` 代码块包裹 → json.loads()
    # 策略 2：find("[") / rfind("]") 截取 JSON 数组
    # 策略 3：find("{") / rfind("}") 截取 JSON 对象
```

注意：此函数仅校验 JSON 语法，不校验字段语义和类型。对于关键调用路径（如匹配评分），已通过 `llm_call()` 的 `response_model` 参数走 Instructor + Pydantic 模式进行结构化输出校验和自动重试修正。

#### 3.1.5 Prompt 模板引擎

```python
load_prompts()           # 加载 prompts.yaml（有缓存）
render_prompt(tpl, **kw)  # 替换 <key> 占位符（尖括号避免与 JSON {} 冲突）
get_system_prompt()      # 获取 Agent 系统提示词，唯一来源为 prompts.yaml，缺失时抛出 RuntimeError
```

所有模块通过 `render_prompt()` 将 `<key>` 占位符替换为实际值。每个 prompt 的唯一来源是 `prompts.yaml`——任何 key 缺失时程序会抛出 `RuntimeError`，不允许静默回退。所有模块通过 `_load_*_prompt()` helper 函数（如 `job_match.py:_load_scoring_prompt()`、`market_analysis.py:_load_market_prompt()`、`resume_gen.py:_load_resume_prompt()`）统一加载，确保 prompt 变更只需编辑一个文件。

#### 3.1.6 Run 目录管理

```python
start_new_run()       # 创建 output/run_{YYYYmmdd_HHMMSS}/ 目录
get_current_run_dir() # 获取当前活跃的 run 目录
get_latest_run_dir()  # 查找最近一次 run（按文件名排序）
```

每次搜索创建一个新的 run 目录，后续匹配和简历输出都写入同一目录。

#### 3.1.7 文件追踪系统

```python
track_file(filepath, description)  # 记录生成的文件
get_session_files()                # 获取并清空本轮文件列表
```

每轮对话后汇总生成的文件列表（路径 + 大小），在终端打印或在 Web UI 中展示。

#### 3.1.8 Campaign 配置管理

通过线程本地存储（`threading.local()`）管理 campaign 配置，与 `emit()` 使用相同的架构模式：

```python
set_campaign_config(cfg)   # 设置当前线程的 campaign 配置
get_campaign_config()      # 获取当前线程的 campaign 配置（无则返回 None）
```

CLI 模式通过 `agent.py --campaign <name>` 参数在启动时注入，Web 模式通过 `/api/session/campaign` 端点按 session 注入。在 `execute_tool()` 中，系统层自动将 campaign 配置注入到 `search_jobs`、`match_jobs`、`generate_resume` 三个工具函数——LLM 无需感知 config 的存在。

---

### 3.2 agent.py — Agent 主入口（终端模式）

**职责**：对话循环 + 工具调用编排。

**核心流程**：
1. 初始化 `messages`（含系统 prompt）
2. `while True:` 用户输入 → 追加到 messages → 调用 `llm_call(messages, tools=tools)`
3. 如果返回 `tool_calls`，进入工具调用循环：
   - `deduplicate_tool_calls()` 去重（`{name}:{arguments}` 为 key）
   - 逐个 `execute_tool()` 执行 → 结果追加为 `{"role": "tool", ...}`
   - 跳过重复调用的占位 tool result 追加 → 防止 LLM 报错
   - 再次调用 `llm_call(messages, tools=tools)` 获取最终回复
4. 打印回复 → `print_session_summary()` 打印本轮生成的文件总览
5. 输入 `quit` 退出，调用 `cleanup_playwright()` + `cleanup_renderer()`

---

### 3.3 tools_defs.py — 工具注册与执行引擎

**职责**：定义所有工具的 JSON Schema（OpenAI Function Calling 格式）+ 执行分发 + 去重。

#### 3.3.1 注册的 14 个工具

| 工具名 | 来源模块 | 必填参数 | 可选参数 | 功能 |
|--------|----------|----------|----------|------|
| `get_current_time` | tools_basic | 无 | — | 获取当前日期时间（中文格式 `2026年06月04日 14:30:00 星期四`） |
| `write_file` | tools_basic | `filename`, `content` | — | 写入文件到 `output/` 目录 |
| `read_file` | tools_basic | `filename` | — | 读取 `output/` 中的文件 |
| `list_files` | tools_basic | 无 | — | 列出当前 run + market 目录中的所有文件 |
| `web_search` | tools_basic | `query` | `max_results`（默认 5） | DuckDuckGo 联网搜索 |
| `load_user_profile` | tools_basic | 无 | — | 查看用户画像 `instances/users/{user}.yaml` 内容（JSON 格式化，通过 `search_config.yaml` 的 `user` 字段定位） |
| `load_search_config` | tools_basic | 无 | — | 查看 `profiles/search_config.yaml` 内容（JSON 格式化，仅系统基础设施配置段） |
| `search_jobs` | job_search | 无 | `sort_by`（`"date"` / `"relevance"`，默认从配置读取） | 三层漏斗搜索：扫描列表页 → 基础清洗 → 全量抓取 JD |
| `match_jobs` | job_match | 无 | — | 五维动态权重匹配评分 + 及格线复评 |
| `generate_resume` | resume_gen | 无（3 种模式，`by_direction` / `job_index` / `jd_text`。均需显式指定，无参数时返回错误提示） | 见 §3.9 | 多模式三语简历 + Cover Letter 生成 |
| `list_matched_jobs` | job_match | 无 | — | 查看最近一次匹配排名结果（含五维分数 + 复评信息） |
| `fetch_job_detail` | tools_basic | `url` | — | 抓取单个岗位 URL 的完整 JD |
| `analyze_market` | market_analysis | `job_category` | `location`（默认 `"Hong Kong"`）、`include_gap_analysis`（默认 `true`）、`classification`、`sort_by` | 单类市场调研（四阶段） |
| `batch_analyze_market` | market_analysis | `tasks`（数组，每项含 `category` + 可选 `classification`） | `location`、`include_gap_analysis`、`sort_by` | 批量市场调研（依次执行） |

> **大小写敏感**：`analyze_market` 和 `batch_analyze_market` 的 `job_category` / `category` 参数**严格保留用户输入的原始大小写**，代码不会做任何修改。`classification` 参数同理。例如用户说「分析 Web3 市场行情」→ `job_category="Web3"`（不是 `"web3"`）。

#### 3.3.2 执行分发 + Campaign 配置注入

```python
def execute_tool(tool_call):
    func_name = tool_call.function.name
    args = json.loads(tool_call.function.arguments) or {}
    func = tool_map[func_name]
    return func(**args) if args else func()
```

无参数校验层——LLM 传的参数直接透传给工具函数。工具函数内部各自做错误处理。

**Campaign 配置注入机制**：`execute_tool()` 在调用 `search_jobs`、`match_jobs` 两个工具时，自动从线程本地存储注入 Campaign 配置（通过 `_CONFIG_AWARE_TOOLS` 集合判断）。`match_jobs` 还会额外注入 `user_profile`。此机制让 LLM 无需感知 config 的存在——LLM 只需调用工具，系统层自动补齐配置。如果 LLM 已经传了 `config` 参数，系统会输出警告并覆盖。

#### 3.3.3 去重机制

`deduplicate_tool_calls()` 以 `{function.name}:{function.arguments}` 为 key 去重。被跳过的重复调用会追加一个占位 tool result（内容为 `"（重复调用已跳过）"`），否则 LLM 会因为缺少 tool result 而报错。


### 3.4 web_app.py — Web UI 服务器

**职责**：Flask Web 服务器 + SSE 流式事件推送 + Session 管理 + 直接流水线执行。

#### 3.4.1 架构要点

- **Session 管理**：`POST /api/session` 分配 `sid`（8 位 UUID），独立维护 `messages` 历史 + `queue.Queue()` SSE 推送队列
- **全局 Agent 锁** (`_agent_lock`)：`threading.Lock()`，Playwright 不支持并发，同一时间只允许一个 Agent 执行。新请求在锁被占用时返回 429
- **队列清理**：每次新请求前清空旧的 SSE 队列事件，防止残留数据干扰
- **两种执行路径**：
  - `/api/chat` → `_run_agent_turn()`：LLM Agent 模式（同 CLI 逻辑）
  - `/api/pipeline` → `_run_pipeline()`：直接执行 `search_jobs → match_jobs → generate_resume(by_direction=True)` 三步流水线

#### 3.4.2 SSE 事件类型

后端推送 JSON 到队列，前端通过 `EventSource` 接收。SSE 协议格式为：

```
event: {type}
data: {json_payload}

```

前端监听 7 种事件类型，与后端一一对应：

| type | 含义 | 后端 payload | 前端渲染 |
|------|------|-------------|---------|
| `status` | 阶段性状态提示 | `{"type": "status", "text": "Starting job search..."}` | 🟡 琥珀色圆点 + 文字 |
| `progress` | 执行结果文本 | `{"type": "progress", "text": "搜索完成 → raw_jobs.json"}` | ⚪ 灰色文字 |
| `tool_call` | 正在调用的工具 | `{"type": "tool_call", "tool": "search_jobs", "args": "{...}"}` | 🔵 青色工具名 + 参数 |
| `review` | 简历核查报告 | `{"type": "review", "bullets": [...], "flagged_count": N}` | 🟠 核查标记列表（checker 系统产出） |
| `done` | 任务完成 | `{"type": "done", "reply": "...", "files": [...]}` | 🟢 完成面板含文件列表 |
| `error` | 执行出错 | `{"type": "error", "text": "..."}` | 🔴 红色错误信息 |
| `ping` | 30 秒心跳保活 | `{}` | 忽略 |

> 所有事件类型已在前后端对齐。前端统一通过 `startSSE()` 建立连接，内建指数退避重试（最多 3 次）。后端空闲连接有约 8 秒缓冲期，防止 pipeline 启动前的时序竞态关停连接。

#### 3.4.3 完整 API 参考

##### `GET /`
返回 `static/index.html` 前端页面。

##### `POST /api/session`
创建新会话。

**Request**: `{}`（空 body 或无 body）

**Response**: `{"sid": "a1b2c3d4"}`

---

##### `POST /api/chat`
LLM Agent 对话（后台线程执行，通过 SSE 获取结果）。

**Request**:
```json
{
  "sid": "a1b2c3d4",
  "message": "帮我找工作"
}
```

**Response** (立即): `{"status": "started"}`

**SSE 事件流** (`GET /stream/{sid}`): 实时推送 `progress` / `tool_call` / `review` / `done` / `error` 事件。`review` 事件（简历核查报告）在 `done` 之前推送。
---

##### `POST /api/pipeline`
直接执行 search→match→resume 三步流水线（不经过 LLM 决策，更快）。

**Request**:
```json
{
  "sid": "a1b2c3d4",
  "action": "search_match",
  "sort_by": "date",
  "languages": ["en", "hk"]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `sid` | 是 | 会话 ID |
| `action` | 是 | 固定 `"search_match"` |
| `sort_by` | 否 | `"date"`（按发布时间）或 `"relevance"`（按相关度）。不传从配置读取 |
| `languages` | 否 | 简历输出语言子集，如 `["en","hk"]`，默认 `["en","hk","cn"]` |

**Response** (立即): `{"status": "started"}`

**SSE 事件流** (`GET /stream/{sid}`): 实时推送 progress / status / review / done / error。其中 `review` 事件（Checker 核查报告）在 `done` 之前自动推送。

---

##### `GET /stream/<sid>`
SSE 事件流端点，浏览器 `EventSource` 连接。30 秒无事件自动发送 `event: ping` 心跳。空闲时有约 8 秒缓冲期（4 轮 × 2 秒超时），防止 pipeline API 调用前的时序竞态导致连接过早关闭。当 session 不再 busy 且队列连续空超过缓冲期后自动断开。

**Response**: `text/event-stream`，协议格式为 `event: {type}\ndata: {json}\n\n`。

---

##### `GET /api/runs`
列出所有 run 目录及元数据。

**Response**:
```json
[
  {
    "id": "run_20260417_221145",
    "path": "run_20260417_221145",
    "time": "2026-04-17 22:11",
    "stage": "matched",
    "has_raw": true,
    "has_matched": true,
    "has_resumes": true,
    "job_count": 200,
    "match_count": 15,
    "is_current": false
  }
]
```

| 字段 | 含义 |
|------|------|
| `stage` | `"empty"`（空目录）/ `"searched"`（有 raw_jobs）/ `"matched"`（有 matched） |
| `is_current` | 是否为当前活跃 run |

---

##### `GET /api/runs/<run_id>/files`
查看指定 run 的文件列表（递归遍历所有子目录，含 resumes/）。

**Response**: `[{"name": "raw_jobs.json", "path": "run_xxx/raw_jobs.json", "size": 12345, "mtime": 1234567890.0}, ...]`

---

##### `GET /api/files`
列出整个 `output/` 目录下所有文件（递归）。

##### `GET /api/market/files`
列出 `output/market/` 下所有文件（不递归）。

##### `GET /api/config/model`
获取当前 LLM 配置。

**Response**:
```json
{
  "current_provider": "glm",
  "current_model": "glm-5.1",
  "presets": {"deepseek": "deepseek-v4-pro", "qwen": "qwen3.6-plus", "glm": "glm-5.1"}
}
```

##### `POST /api/config/model`
运行时切换 LLM provider/model。

**Request**:
```json
{
  "provider": "qwen",
  "model": "qwen3.6-plus"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `provider` | 是 | `"deepseek"` / `"qwen"` / `"glm"` |
| `model` | 否 | 不传则使用该 provider 的默认模型 |

切换立即生效（原地修改全局 client 属性），同时回写 `search_config.yaml`。

##### `GET /api/campaigns`
列出所有可用的 campaign（摘要信息）。

**Response**:
```json
[{"name": "web3_hunt", "user": "li_ming", "strategy": "web3", "queries": 3, "keywords": ["Web3", "Blockchain Developer", "Smart Contract"], "sort_mode": "date"}]
```

##### `POST /api/session/campaign`
设置当前 session 的 campaign。传 `null` 清除选择。

**Request**:
```json
{"sid": "a1b2c3d4", "campaign": "web3_hunt"}
```

**Response**: `{"status": "ok", "campaign": "web3_hunt"}`

##### `GET /api/users`
列出 `instances/users/` 下所有可用的用户画像。

**Response**:
```json
[{"name": "li_ming", "user_name": "请替换为真实姓名"}]
```

##### `POST /api/config/user`
运行时切换用户画像（更新 `search_config.yaml` 的 `user` 字段，即时生效）。

**Request**:
```json
{"user": "li_ming"}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `user` | 是 | 用户画像文件名（不含 `.yaml` 后缀），需在 `instances/users/` 下存在 |

**Response**: `{"status": "ok", "user": "li_ming"}`

##### `GET /download/<path>`
文件下载。路径相对于 `output/` 目录。如 `/download/run_xxx/resumes/resume_web3_20260417_en.pdf`。

##### `GET /api/runs/<run_id>/matches`
返回指定 run 的结构化匹配评分数据。

**Response**:
```json
[
  {
    "title": "Web3 Payment Backend Engineer",
    "company": "PayChain Solutions",
    "url": "https://hk.jobsdb.com/job/...",
    "total_score": 84,
    "scores": {"skill": 88, "experience": 80, "level": 75, "industry": 90, "bonus": 85},
    "llm_direction": "payment",
    "weight_profile": "payment",
    "confidence": "verified",
    "score_variance": 3.5,
    "skill_match": ["Java ✅", "Python ✅", "Kubernetes ❌"],
    "missing_skills": ["Kubernetes"],
    "reason": "...",
    "recommendation": "强烈推荐"
  }
]
```

##### `POST /api/resume`
直接调用简历生成。参数由前端表单提供，SSE 流返回进度。

**Request**:
```json
{
  "sid": "a1b2c3d4",
  "mode": "job",
  "languages": ["en", "hk"],
  "job_index": 1,
  "jd_text": "..."
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `sid` | 是 | 会话 ID |
| `mode` | 是 | `"job"` / `"jd"`。不支持的模式返回错误 |
| `languages` | 否 | 语言子集，如 `["en"]`，默认 `["en","hk","cn"]` |
| `job_index` | 否 | mode=`"job"` 时必填，匹配排名中的岗位编号（从 1 开始） |
| `jd_text` | 否 | mode=`"jd"` 时必填，粘贴的完整 JD 文本 |

**Response** (立即): `{"status": "started"}`

**SSE 事件流** (`GET /stream/{sid}`): 实时推送 progress / status / review / done / error。`review` 事件（Checker 核查报告）在 `done` 之前自动推送。

##### `POST /api/resume/fix`
定点修正单条 resume bullet（配合 checker 系统使用），返回修正后的完整 Markdown。

**Request**:
```json
{
  "resume_md": "（完整简历 Markdown）",
  "bullet_index": 0,
  "feedback": "这条 bullet 的量化数据不对，实际是 10,000+ 笔而不是 5,000 笔"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `resume_md` | 否 | 完整简历 Markdown。不传则使用最近一次生成的简历 |
| `bullet_index` | 是 | 要修正的 bullet 索引（从 0 开始） |
| `feedback` | 是 | 用户对这条 bullet 的修正意见 |

**Response**: `{"fixed_md": "...", "check_result": {"text": "...", "source_ids": [...], "flags": [...]}}`

##### `POST /api/market`
直接调用单个市场调研。SSE 流返回进度。

**Request**:
```json
{
  "sid": "a1b2c3d4",
  "job_category": "Web3",
  "location": "Hong Kong",
  "include_gap_analysis": true,
  "classification": "information-communication-technology",
  "sort_by": "date"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `sid` | 是 | 会话 ID |
| `job_category` | 是 | 岗位类别关键词，大小写敏感 |
| `location` | 否 | 默认 `"Hong Kong"` |
| `include_gap_analysis` | 否 | 默认 `true` |
| `classification` | 否 | JobsDB 行业分类标签，大小写敏感 |
| `sort_by` | 否 | `"date"` 或 `"relevance"` |

**Response** (立即): `{"status": "started"}`

##### `POST /api/market/batch`
批量市场调研，依次执行每个任务。

**Request**:
```json
{
  "sid": "a1b2c3d4",
  "tasks": [
    {"category": "AI Agent", "classification": "information-communication-technology"},
    {"category": "Web3"}
  ],
  "location": "Hong Kong",
  "include_gap_analysis": true,
  "sort_by": "date"
}
```

##### `GET /api/config/yaml/<name>`
读取 YAML 配置文件并返回 JSON。

**URL 参数**: `name` — `"me"` 或 `"search_config"`

> **⚠️ 路径说明**：`name="me"` 实际读写 `instances/users/{user}.yaml`（通过 `search_config.yaml` 的 `user` 字段定位），而非 `profiles/me.yaml`。`name="search_config"` 读写 `profiles/search_config.yaml`。

**Response**: `{"name": "me", "content": {...}}`

##### `PUT /api/config/yaml/<name>`
回写 YAML 配置文件。前端提交 JSON，后端转为 YAML 存储。

**Request**: `{"content": {...}}` — 完整的配置对象

**Response**: `{"status": "ok", "name": "me"}`

> **⚠️**：`name="me"` 写入路径为 `instances/users/{user}.yaml`，`name="search_config"` 写入路径为 `profiles/search_config.yaml`。

---

### 3.5 Web UI — 功能能力

Web UI 提供与终端 CLI 相同的功能，通过浏览器访问。核心能力包括：

- **自然语言对话**：用户输入文本指令，LLM 解析意图后调用对应工具，执行结果实时反馈
- **快捷操作**：用户无需输入文本即可触发「找工作」完整流程（系统自动按固定顺序执行搜索→匹配→简历生成）
- **实时进度反馈**：通过 SSE（Server-Sent Events）协议向界面推送执行进度，包括当前操作日志、工具调用状态、阶段完成通知和错误信息
- **多 Provider 切换**：用户可在 DeepSeek / Qwen / GLM 之间实时切换 LLM，切换立即生效
- **排序切换**：用户可切换搜索排序方式（按发布时间最新在前 / 按相关度），影响 `search_jobs` 和 `analyze_market` 的行为
- **Campaign 切换**：用户可通过侧边栏下拉框选择求职方向（campaign），切换后后续请求自动使用对应的搜索词和权重策略。未选择时自动使用第一个可用 campaign
- **画像切换**：用户可通过侧边栏切换用户画像（`instances/users/` 下的不同画像文件），切换后立即生效，影响匹配评分和简历生成
- **简历审查面板**：生成简历后自动展示 bullet 核查结果（checker 系统产出），支持逐条查看 7 种 flag（空源/悬空引用/占位符/数字缺失/数字冲突/约数超范围/强度升级），确认放行，逐条修正（`/api/resume/fix`，含 LLM 修补 → 验证 → 重检 → 重试流程）
- **简历生成**：支持「匹配岗位」和「JD 文本」两种直接触发方式；方向聚合由「一键找工作」全流程自动完成
- **市场调研**：用户可输入岗位类别参数直接触发市场调研
- **文件管理**：浏览所有历史 Run 和市场调研的输出文件，支持文件下载。默认折叠、按分组展开/折叠、全部展开/折叠
- **运行历史**：查看历史 Run 列表（含时间、当前阶段、岗位数量），区分活跃 Run 和已完成 Run
- **智能路由层**：`routeMessage()` 函数拦截用户输入，匹配已知指令（"帮我找工作""分析X市场""看看匹配结果"等）直接执行本地操作，无需经过 LLM 决策，其余自由对话才发给 LLM Agent。建议 chips 也通过路由层触发
- **全局忙锁**：`setBusy()` / `guardBusy()` 控制并发，同一时间只允许一个 Agent 任务执行。busy 状态下 `.agent-trigger` 元素半透明（opacity:0.45）且不可点击，状态指示灯变为琥珀色旋转动画。并发请求返回 HTTP 429
- **键盘快捷键**：Escape 关团 YAML 浮层和语言弹窗；Enter 发送消息（Shift+Enter 换行）

> 以上为功能能力描述。具体的 UI 布局、视觉风格、交互方式由产品设计决定。

---

### 3.6 tools_basic.py — 基础工具函数

**职责**：提供时间、文件操作、DuckDuckGo 搜索、配置查看、单岗位抓取等基础能力。

| 工具 | 输出格式 | 要点 |
|------|----------|------|
| `get_current_time()` | `2026年06月04日 14:30:00 星期四` | 中文格式 |
| `write_file(filename, content)` | 写入 `output/` 目录，自动创建子目录，自动 `track_file()` |
| `read_file(filename)` | 全文返回 | 限定在 `output/` 目录内 |
| `list_files()` | 分层列出当前 run + market 目录文件（含递归子目录） | 无 run 时自动找最近一次 run |
| `web_search(query)` | 标题 + 摘要 + 链接 | DuckDuckGo，默认 5 条，region=`wt-wt` |
| `load_user_profile()` | 用户画像（`instances/users/{user}.yaml`）转 JSON | 对 LLM 更友好的结构化格式 |
| `load_search_config()` | `search_config.yaml` 转 JSON | 同上（仅系统基础设施配置段） |
| `fetch_job_detail(url)` | 标题/公司/地点/薪资/完整 JD | 调用 `scraper.fetch_job_detail()` |

---

### 3.7 scraper.py — JobsDB 网页爬虫（核心模块，~1032 行）

**职责**：抓取 JobsDB 职位列表页和详情页。

#### 3.7.1 HTTP 请求层

- **主引擎**：Playwright 无头浏览器（JobsDB 对所有 requests 请求返回 403）
- **反爬措施**：
  - 完整浏览器 Headers
  - `navigator.webdriver` 属性覆盖 + `window.chrome` 注入
  - Cloudflare 挑战页检测与额外等待（5s）
  - 翻页间隔随机延迟 `random.uniform(1.5, 3.0)` 秒
  - 失败时重建浏览器重试（1 次）
  - 浏览器健康检查：`browser.contexts` 轻量探活，失效自动重启

#### 3.7.2 列表页扫描（4 层解析策略）

```
策略 1: __NEXT_DATA__ JSON jobs 数组（最优先）
  ├── 深度优先递归搜索（max_depth=10），定位 jobs 数组
  ├── 支持 GraphQL edges 模式 ({node: {...}})
  ├── _extract_field() 提取 title/company/salary/location/job_id
  │
  ├── 策略 1 有结果但超半数 title 为空 → 策略 2 补充
  │   策略 2: HTML DOM 补充标题
  │   _build_html_title_map() 构建 {job_id: title} 映射
  │   两阶段回退：card 选择器 → <a> 标签链接文本
  │
  └── 策略 1 本页完全无结果 (page_count == 0) → 策略 3
      策略 3: 纯 HTML Card 解析
      _parse_html_job_cards()，多种选择器回退
      article[data-testid] → div[data-job-id] → div[class*="job-card"]
        │
        └── 策略 3 也解析不到 → 策略 4
            策略 4: <a> 标签链接提取（最后兜底）
            过滤太短 (<3) 或太长 (>200) 的链接文本
```

#### 3.7.3 数据驱动的字段提取器

`_FIELD_SPECS` + `_extract_field()` 系统。JobsDB 页面结构频繁变化，只需在 `_FIELD_SPECS` 中增加新 key 名称，无需改解析逻辑：

```python
_FIELD_SPECS = {
    "title": {
        "direct_keys": ["title", "jobTitle", "displayTitle", "heading", ...],  # Phase 1
        "parent_keys": ["job", "content", "details", ...],                     # Phase 2
        "sub_keys": ["title", "jobTitle", ...],                                # Phase 2
        "recursive": True, "max_depth": 3, "min_len": 2,                      # Phase 3
    },
    "company": { ... }, "salary": { ... }, "location": { ... },
}
```

#### 3.7.4 详情页解析（3 层策略）

```
策略 1: __NEXT_DATA__ 中的 pageProps → jobDetail
策略 2: JSON-LD 结构化数据 (<script type="application/ld+json">)
策略 3: HTML DOM 直接解析 (h1 + 多选择器找职位描述)
```

#### 3.7.5 URL 工具

- `normalize_jobsdb_url(url)` → `https://hk.jobsdb.com/job/{id}`（去重用）
- `is_listing_page(url)` / `is_job_detail_url(url)` / `classify_urls(urls)` → URL 分类


### 3.8 job_search.py — 搜索管道

**职责**：编排完整搜索流程。`search_jobs(sort_by=None)`。

#### 三层漏斗

```
第一层（扫描）：scan_jobsdb_listings()
  多组搜索关键词 × 多页翻页（跨关键词 job_id 去重）
  sort_by: "date" → ?sortmode=ListedDate（最新在前）
           "relevance" → 不传 sortmode（JobsDB 默认相关度排序）
  结果字段：title, company, salary, snippet, url, job_id
           │
           ▼
第二层（清洗）：basic_filter()
  排除空标题 + 排除公司（search_config.yaml 的 exclude_companies）
  成本：0（纯代码规则，毫秒完成）
  诊断：超 80% 标题为空 → 返回爬虫选择器需要修复的提示
           │
           ▼
第三层（抓取）：fetch_multiple_details()
  全量抓取完整 JD（上限 max_total_results，默认 200）
  随机延迟 1.5~3.5 秒防封
  降级策略：详情页抓取失败 → 列表页 snippet 兜底（source: "snippet"）
  结果字段：title, company, location, salary, description, url, jd_length,
            posted_date, classification, source
```

#### 输出文件

| 文件 | 内容 |
|------|------|
| `raw_jobs.json` | 全量抓取的完整 JD（含 source 字段标记 full_jd/snippet） |
| `scan_listings.json` | 第一层扫描的全量列表（过滤前） |
| `rejected_jobs.json` | 被基础清洗排除的岗位 + 原因 + 阶段标记 |
| `filter_stats.json` | 过滤统计（各层数量 + 全量 JD/snippet 计数 + 被拒样本） |

#### 设计理念

不做 LLM 预过滤，全量抓取完整 JD 后交给 `match_jobs` 精确评分。虽然抓取时间更长（100 条约 150~350 秒），但避免基于标题+摘要的误杀。


### 3.9 job_match.py — LLM 五维匹配评分

**职责**：读取 `raw_jobs.json` + 用户画像（从 `instances/users/{user}.yaml` 加载），用 LLM 从 5 个维度评分。

#### 五维评分体系 + 动态权重

| 方案 | 技能 | 经验 | 职级 | 行业 | 加分 | 适用场景 |
|------|------|------|------|------|------|----------|
| default | 30% | 25% | 15% | 15% | 15% | 无法分类的通用岗位 |
| technical | 35% | 20% | 15% | 15% | 15% | 纯技术开发岗 |
| solutions | 25% | 20% | 15% | 20% | 20% | 方案/集成工程师 |
| web3 | 25% | 15% | 10% | 30% | 20% | Web3/区块链岗位 |
| payment | 25% | 20% | 10% | 25% | 20% | 支付/结算岗位 |

#### 方向判断流程

```
1. LLM 评分时返回 direction 字段（基于完整 JD 内容判断）
2. 检查 direction 是否在 {payment, solutions, web3, technical, default} 中
   ├── 有效 → 采用为 llm_direction
   └── 无效或未返回 → 回退到 classify_job() 标题关键词匹配
                       ↓
       检查顺序：payment → solutions → web3 → technical → default
       （更具体的类别在前，防止误匹配到通用关键词）
```

**Few-shot 示例注入**：评分 prompt 中会注入方向相关的 few-shot 示例，帮助 LLM 更准确地判断岗位方向。示例来源为 `prompts/examples/job_match/` 目录，始终加载 `common.yaml` 的通用示例，并根据当前 campaign 的 strategy 加载对应的 `{strategy}.yaml` 示例（如 `web3.yaml`）。实现函数为 `_load_examples(strategy)`。

**Instructor 模式说明**：匹配评分主路径 `_score_batch()` 使用 LLM 返回 JSON 文本 + `parse_json_response()` 解析模式；评估脚本 `score_single_jd()` 使用 Instructor + Pydantic（`response_model=MatchResult`）进行结构化输出校验和自动重试修正。

**权重方案可用性**：Campaign 模式下，`weight_profiles` 仅包含当前 strategy 的权重方案 + default 默认权重。其他方向类别（如使用 `web3` strategy 时的 `payment`/`solutions`/`technical`）的岗位将使用 default 权重计算总分。所有 5 种策略文件位于 `instances/strategies/`，不同 campaign 可通过切换 strategy 来使用不同的权重方案。

#### 完整评分流程

1. **第一轮**：所有岗位用 default 权重统一打分（分批评分，每批 5 个），LLM 同时返回 direction
2. **方向权重重算**：用 `llm_direction` 对应权重重新计算 `total_score`
3. **去重 + 排序**：按 URL 标准化去重 + `total_score` 降序排列
4. **第二轮（可选）**：`borderline_rescore: true` 时，对 `min_match_score ± borderline_range` 区间内的岗位：
   - 逐个用其方向权重重新评分
   - 五维取两轮平均，计算波动
   - 波动 ≤10 → `confidence: "verified"`（复评一致）
   - 波动 >10 → `confidence: "uncertain"`（评分波动大，需人工判断）
5. **筛选**：保留 ≥ `min_match_score`（默认 45）的岗位，上限 `top_n`

#### LLM 评分 JSON 输出格式

每个岗位 LLM 返回：
```json
{
  "index": 1,
  "title": "Backend Developer",
  "company": "某公司",
  "direction": "web3",
  "scores": {"skill": 85, "experience": 70, "level": 60, "industry": 75, "bonus": 90},
  "total_score": 76,
  "skill_match": ["Python ✅", "Go ❌", "AWS ✅"],
  "missing_skills": ["Go"],
  "reason": "候选人的 WaaS 支付经验与岗位高度匹配...",
  "recommendation": "强烈推荐"
}
```

`total_score` 计算公式：
```
skill × w1 + experience × w2 + level × w3 + industry × w4 + bonus × w5
（各权重根据方向方案动态变化）
```

#### 推荐等级

| 分数 | 标记 | 含义 |
|------|------|------|
| ≥ 80 | 🟢 | 强烈推荐 |
| ≥ 60 | 🟡 | 可考虑 |
| < 60 | 🔴 | 不推荐 |

#### 额外评估维度（prompts.yaml 中扩展，不参与加权计算）

| 维度 | 值 | 含义 |
|------|-----|------|
| `english_risk` | 低/中/高 | 岗位英语要求对候选人的阻碍程度 |
| `interview_risk` | 低/中/高 | 面试中算法/八股文等候选人的薄弱环节风险 |

#### 输出文件

| 文件 | 内容 |
|------|------|
| `matched_jobs.json` | 达标岗位（含五维 scores、total_score、llm_direction、weight_profile、confidence、score_rounds、score_variance） |
| `unmatched_jobs.json` | 未达标岗位（低于 min_match_score） |
| `job_report.md` | Markdown 排名报告（权重方案表 + 各岗位详情 + 技能匹配 + 复评信息） |


### 3.10 resume_gen.py — 多模式简历生成

**职责**：3 种生成模式 × 英文先行 × 三语翻译 × 质量自检 × bullet 事实核查。

**函数签名**：
```python
def generate_resume(job_index=None, jd_text=None, by_direction=False, output_langs=None, profile=None)
```
其中 `output_langs` 控制输出语言子集（如 `["en","hk"]`，默认 `["en","hk","cn"]`），Web API 通过 `languages` 字段透传。`profile` 供 Campaign 模式注入，留空则从 `instances/users/{user}.yaml` 自动加载。

#### 3 种生成模式

| 模式 | 参数 | 适用场景 |
|------|------|----------|
| 方向聚合 | `by_direction=true` | search+match 后批量投递，按方向（payment/web3/solutions/technical）聚合 JD 共性需求生成 |
| 匹配岗位 | `job_index=N` | 从匹配排名中选某个高分岗位单独定制 |
| JD 文本 | `jd_text="..."` | 在其他平台看到的岗位，粘贴完整 JD |

> **已删除的模式**：岗位方向（`role_direction`）和通用简历（无参数）因缺乏市场数据支撑已被移除。方向聚合仅通过 `/api/pipeline`（一键找工作）触发；Web UI 简历页提供「匹配岗位」和「JD 文本」两种模式。

#### 方向聚合模式详细流程

1. 读取 `matched_jobs.json`，按 `llm_direction` 分组
   - **跳过 `default` 方向的岗位**（无法归类，不参与聚合）
   - **每个方向至少需要 2 个达标岗位**，不足则跳过
2. 每个方向调用 LLM 聚合分析（取前 15 个岗位，每条 JD 截断至 2000 字符），输出三级技能分类：

| 分类 | 含义 | 简历中的处理 |
|------|------|-------------|
| `direct_match` | 候选人具备 → 简历重点展示 | 标熟练度，工作经历突出相关成果 |
| `quick_learnable` | 不直接具备但属于通用技术栈，有相近基础 | Skills 列出不标精通，Cover Letter 表态 |
| `hard_gap` | 需要专门培训或完全不相关 | 简历不提 |

3. 保存聚合数据到 `direction_analysis.json`
4. 对每个方向生成三语简历 + Cover Letter

#### 英文先行 + 翻译流程

```
Step 1: 英文简历生成
Step 2: 审查（resume_review_prompt，输出 JSON 审查报告）
  ├── 总评 A/B → 英文简历定稿
  └── 总评 C/D → 审查反馈注入 prompt → 重新生成英文简历（最多重写一次）→ 定稿
Step 3: 英文 Cover Letter 生成
Step 4: 将定稿英文简历精确翻译为 繁體中文（hk）和 简体中文（cn）
Step 5: 将定稿英文 Cover Letter 翻译为 繁體中文（hk）和 简体中文（cn）
```

**翻译规则**：
- 保持完全一致的结构、段落顺序和 bullet points 数量
- 技术术语保留英文原文（如 `Java`, `AWS Lambda`）
- 公司名称保留英文（可在括号内加中文）
- 学历、证书名称保留英文
- 数字和量化指标保持不变

#### 每次调用生成 7 个文件

```
resume_{label}_{date}_en.pdf          # 英文简历（主版本）
resume_{label}_{date}_hk.pdf          # 繁體中文简历
resume_{label}_{date}_cn.pdf          # 简体中文简历
cover_letter_{label}_{date}_en.pdf    # 英文 Cover Letter
cover_letter_{label}_{date}_hk.pdf    # 繁體中文 Cover Letter
cover_letter_{label}_{date}_cn.pdf    # 简体中文 Cover Letter
resume_review_{label}_{date}.json     # 审查报告
```

> `{label}` 是安全的文件名片段（`_make_safe_label()` 处理，取前 30 字符，非字母数字替换为 `_`）。
> `{date}` 格式为 `YYYYMMDD`。

#### 质量自检机制

**第一层：LLM 审查**。审查维度：6 秒测试、关键词覆盖、业务/技术平衡、量化程度、弱点暴露、ATS 友好度。

审查输出 JSON 结构（示例）：
```json
{
  "overall_score": "A",
  "six_second_test": {"passed": true, "feedback": "..."},
  "keyword_coverage": {"score": "A", "missing": []},
  "quantification": {"score": "B", "suggestions": ["..."], "feedback": "..."},
  "weakness_exposure": {"issues": [], "feedback": "..."},
  "ats_friendliness": {"score": "A", "issues": [], "feedback": "..."},
  "top_3_improvements": ["增加第2段经历的量化数据"]
}
```

**第二层：Bullet 事实核查（`checker.py`）**。对 LLM 生成的每条 bullet 与用户画像源条目进行逐条比对（通过 `source_ids` 溯源），检测以下 7 种问题：

| flag 类型 | 说明 | 示例 |
|----------|------|------|
| `empty_source` | bullet 未声明任何 source_ids | 无溯源引用 |
| `dangling_reference` | source_ids 在当前画像中找不到对应条目 | 引用了不存在的 id |
| `placeholder_present` | bullet 中含有未替换的占位符 | `[请在此填写具体数据]`、`[TODO]`、`【待补充】` |
| `number_not_found` | bullet 中有数字，但源数据中没有任何对应数字 | bullet 有"5,000 笔"但源数据无数字 |
| `number_conflict` | bullet 中的精确数字与源数据不一致 | bullet 写"处理 5,000+ 笔交易"，源数据是 10,000+ |
| `approx_out_of_range` | bullet 中的约数与源数据偏差超过 5% | bullet 写"约 50%"，源数据约 80% |
| `strength_upgrade` | bullet 动词强度超出源数据支撑 | 源数据是"参与"项目（强度1），bullet 写成"主导"项目（强度3） |

核查通过 `check_bullet(source_ids, profile, bullet_text)` 函数完成，返回 flags 列表。核查结果通过 SSE `review` 事件推送至前端。

**Bullet 定点修正（`fix_single_bullet()`）**：用户通过 `/api/resume/fix` 端点修正单条 bullet 时，系统执行以下流程：

```
1. 解析简历 Markdown 中所有 bullet（含 source_ids 标记）
2. 构造修补 prompt：只修改目标 bullet，其他内容不变
3. LLM 修补 → 验证 bullet 数量不变 → 验证非目标 bullet 未被改动
4. 重新调用 check_bullet() 核查修补后的 bullet
5. 若仍有问题 → 将 checker 结果反馈给 LLM → 再重试一次
6. 返回修正后的完整 Markdown + 核查结果
```

所有修补失败时回退到原始简历，确保不会引入错误。

#### 输出文件（方向聚合模式）

`direction_analysis.json` 结构：
```json
{
  "payment": {
    "direction": "payment",
    "job_count": 5,
    "common_requirements": {
      "direct_match": [{"skill": "Python", "frequency": "80%", "candidate_level": "精通"}],
      "quick_learnable": [{"skill": "Kafka", "frequency": "60%", "related_skill": "RabbitMQ", "reason": "消息队列原理相通"}],
      "hard_gap": [{"skill": "Solidity审计", "frequency": "40%", "reason": "需要专门培训"}]
    },
    "typical_responsibilities": ["设计 RESTful API", "..."],
    "common_bonus": ["粤语", "AWS 认证"],
    "resume_strategy": "一段100字以内的简历撰写策略建议"
  },
  "web3": { ... },
  ...
}
```


### 3.11 pdf_renderer.py — Markdown → PDF 渲染

**职责**：将 LLM 生成的 Markdown 简历/报告转为 A4 PDF。

#### 渲染流程

```
Markdown → _fix_resume_markdown() 格式修复 → markdown_to_html() → 嵌入 CSS → Playwright Chromium page.pdf() → PDF
```

#### 格式修复 (`_fix_resume_markdown`)

LLM 输出的 bullet points 之间有额外空行，会导致 markdown 库生成 `<li><p>` 嵌套，在 PDF 中产生多余间距。此函数自动去除相邻 bullet 之间的空行。

#### 两个 CSS 样式

| 样式 | 用途 | 特点 |
|------|------|------|
| `RESUME_CSS` | 简历 PDF | 深灰 `#222` 章节标题、全大写、`1.5px solid #333` 下划线分隔、`@page { margin: 2cm }` + `page.pdf()` 层叠 margin `1.5cm/2cm`、打印分页优化 |
| `REPORT_CSS` | 市场分析报告 | 深蓝 `#1a5276` 标题色、表格样式（斑马纹：`tr:nth-child(even) { background: #fafbfc }`）、更宽间距 |

#### 中文字体回退链

`Arial → Calibri → Microsoft JhengHei → PingFang HK → PingFang SC → SimHei → sans-serif`

#### 关键设计

- 两个独立的 Playwright 浏览器实例（scraper.py 和 pdf_renderer.py 各一个，避免冲突）
- 浏览器懒加载 + 全局复用 + 健康检查（`browser.contexts` 探活）+ 自动恢复
- `python-markdown` 库优先（带 `extra/smarty/sane_lists` 扩展），缺失时回退内置简易转换器
- `_render_in_thread()`：独立线程中完成 Playwright 渲染，解决 asyncio 冲突

#### 两个渲染入口

```python
render_resume(markdown_text, md_filepath)  # → PDF 文件路径或 None
render_report(markdown_text, md_filepath)  # → PDF 文件路径或 None（使用 REPORT_CSS）
```


### 3.12 market_analysis.py — 独立市场调研

**职责**：指定岗位类别，主动搜索 JobsDB 并多维度分析市场行情。

#### 四阶段流程

```
Phase A: 数据采集
  scan_jobsdb_listings(job_category, ...) → 翻 max_pages 页（YAML 默认 4，代码级 fallback 3）
  fetch_multiple_details() → 全量抓取完整 JD（上限 max_fetch_jd，YAML 默认 100，代码级 fallback 40）
  无效 JD 用列表页 snippet 兜底
           │
           ▼
Phase B: LLM 市场分析（分批评分 + 多批自动聚合）
  每批 batch_size 条 JD（YAML 默认 5，代码级 fallback 10）发给 LLM
  单条 JD 截断至 jd_max_chars 字符（YAML 默认 6000，代码级 fallback 2000）
  > 以上参数均从 `search_config.yaml` 的 `market_analysis` 段读取。代码级 fallback 仅在 YAML 配置缺失时生效。
  LLM 提取以下 11 个维度：
   1. technical_skills      — 技术技能（排名、分类、工具、说明）
   2. soft_skills           — 软技能/业务能力
   3. salary_overview       — 薪资概况（按级别分类）
   4. experience_distribution — 经验要求分布
   5. common_responsibilities — 岗位职责共性
   6. industry_distribution — 行业分布
   7. key_trends            — 关键趋势观察
   8. language_requirements — 语言要求（英语/中文，按级别统计）
   9. education_requirements — 学历要求
  10. company_profile       — 公司画像（规模分布、知名雇主）
  11. interview_hints       — 面试线索（技术面/行为面/BQ 等）

  单批结果直接使用；多批结果通过 _aggregate_batch_results() 自动合并
  （计数累加 + 去重 + 百分比重算，覆盖上述全部 11 个维度）
           │
           ▼
Phase C: 差距分析（可选，include_gap_analysis 控制）
  对比候选人画像 vs 市场需求
  输出：strengths（优势）、gaps（差距+学习路径）、
        low_value_skills（低价值技能）、strategic_advice（策略建议）
           │
           ▼
Phase D: LLM 撰写报告 + 保存所有文件
  结构化数据 → LLM 撰写专业 Markdown 报告 → 渲染 PDF
  若 LLM 报告生成失败 → 回退到 JSON dump 格式（确保数据不丢）
```

> **Instructor 模式**：Phase B（JD 分析）和 Phase C（差距分析）已改用 Instructor + Pydantic 结构化输出。Phase B 使用 `MarketAnalysisResult` 模型（12 字段），Phase C 使用 `GapAnalysisResult` 模型（6 字段）。Instructor 自动校验 LLM 输出结构，格式错误时自动重试修正；失败时通过 try/except 回退到旧 `parse_json_response()` 方式，确保兼容性。`.model_dump()` 转回 dict，后续聚合逻辑和报告撰写代码零改动。

#### 函数签名

```python
analyze_market(job_category, location="Hong Kong", include_gap_analysis=True,
               classification="", sort_by=None)

batch_analyze_market(tasks, location="Hong Kong", include_gap_analysis=True,
                     sort_by=None)
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `job_category` | str | 是 | — | 岗位类别关键词，**大小写敏感**，用户输入原样传入 |
| `location` | str | 否 | `"Hong Kong"` | 搜索地点 |
| `include_gap_analysis` | bool | 否 | `true` | 是否含个人差距分析 |
| `classification` | str | 否 | `""` | JobsDB 行业分类，**大小写敏感**。如 `"information-communication-technology"`, `"banking-financial-services"` |
| `sort_by` | str | 否 | 从 `sort_mode` 配置读取 | `"date"`（按发布时间）或 `"relevance"`（按相关度） |

`batch_analyze_market` 的 `tasks` 参数格式：
```json
[
  {"category": "AI Agent", "classification": "information-communication-technology"},
  {"category": "Web3"},
  {"category": "Java Developer", "classification": "banking-financial-services"}
]
```
依次执行每个任务，每完成一个自动开始下一个，最后汇总所有结果。

> **⚠️ 大小写敏感规则**：`job_category`（或 `category`）和 `classification` 的值会原样传给 JobsDB 搜索。用户说「分析 Web3 市场」→ `job_category="Web3"`（**不**变成 `"web3"`）。用户说「分析 science-technology 行业」→ `classification="science-technology"`（**不**变成 `"Science-Technology"`）。LLM 的 system prompt 中明确告知了此规则。

#### 市场分析每个维度的输出格式

**technical_skills**（每条技能）：
```json
{
  "skill": "Ethers.js Web3 Library",
  "category": "框架",
  "description": "以太坊 JavaScript 库，用于与智能合约交互和构建 DApp 前端",
  "typical_tools": ["Ethers.js v6", "Web3.js", "Wagmi", "Viem"],
  "count": 15,
  "percentage": "60%",
  "level": "必须"
}
```
- 技能名称必须具体到可以学习的程度（如 `"Ethers.js Web3 Library"` 而非 `"Web3"`）
- `category` 取值范围：`编程语言 / 框架 / 数据库 / 云平台 / DevOps / 安全 / 协议 / 其他工具`
- `level` 取值范围：`必须 / 优先 / 加分`
- 按频次降序，最多 20 项

**gap_analysis**（每条差距）：
```json
{
  "skill": "Kubernetes",
  "description": "容器编排平台，用于管理大规模微服务部署、自动伸缩和服务发现",
  "market_demand": "高",
  "learning_difficulty": "中",
  "current_gap": "候选人有 Docker 和 docker-compose 经验但没在生产环境用过 K8s 编排",
  "learning_path": [
    "第 1 步：在 Minikube 上部署一个简单的 3 层应用（2 周，每天 1 小时）",
    "第 2 步：学习 Helm Chart 打包和 ConfigMap/Secret 管理（1 周）",
    "第 3 步：在 AWS EKS 或 GCP GKE 上部署一个带 CI/CD 的项目（2 周）"
  ],
  "priority": "高 — 18/25 条 JD 要求 K8s 经验"
}
```

#### 输出文件

`output/market/` 目录下，每次分析生成 **5 个文件**：

| 文件 | 格式 | 内容 |
|------|------|------|
| `market_{category}_{date}.md` | Markdown | LLM 生成的专业分析报告（所有 11+ 维度） |
| `market_{category}_{date}.pdf` | PDF | 同上，Playwright Chromium 渲染 |
| `market_{category}_{date}.json` | JSON | 结构化分析数据（含 analysis + gap_analysis） |
| `market_{category}_{date}_scan.json` | JSON | 全量扫描列表（过滤前的原始 listing 数据） |
| `market_{category}_{date}_jds.json` | JSON | 抓取的完整 JD 原文（用于后续验证或深入分析） |

> `{category}` = 岗位类别名（空格替换为 `_`，`/` 替换为 `_`，截断至 30 字符）
> `{date}` = `YYYYMMDD_HHMMSS`

---

## 四、配置文件说明

### 4.1 instances/users/{user}.yaml — 用户画像

> **⚠️ 路径变更**：用户画像已从 `profiles/me.yaml` 迁移至 `instances/users/{user}.yaml`。通过 `search_config.yaml` 的 `user` 字段指定当前使用的画像文件名（不含 `.yaml` 后缀）。例如 `user: "li_ming"` → 加载 `instances/users/li_ming.yaml`。

```yaml
基本信息:
  姓名、电话、邮箱、LinkedIn、GitHub、所在地

战略定位:
  核心画像、方向优先级、关键约束（英语/算法/经验年限）

求职意向:
  target_titles（按优先级排序，当前：Web3 支付基础设施工程师 > 方案工程师 > Web3 后端 > 技术支持）
  target_industries、薪资期望（25-35K HKD）、到岗时间

专业技能:
  数据库（MySQL/Redis/MongoDB）、API 集成（RESTful/Webhook/SDK）
  编程语言（Java/Python/Go/JS）、框架（Spring Boot/FastAPI/MyBatis）
  区块链（Ethereum/BSC/TRON + USDT/USDC/TRC20 代币接入）
  DevOps（Docker/GitHub Actions/AWS EC2/S3）
  AI 工具（Cursor/Claude Code/GitHub Copilot）
  业务能力（WaaS 钱包即服务 / 支付清结算 / 商户对接）
  语言能力（普通话/粤语/英语）

工作经历:
  某 Web3 科技公司 | Java 后端工程师 | 2024.08-2026.05
  5 个核心业务模块详细描述：充值监听（5 层防假充值）、提款（5 层防重复出款）、
  归集（3 阶段流水线）、B2B 商户对接、链上交易监控

教育背景 / 项目经历 / 证书 / 自我评价
```

### 4.2 profiles/search_config.yaml — 系统基础设施配置

> **⚠️ 职责分离**：`search_config.yaml` 现仅保留系统基础设施配置（LLM、过滤、市场参数、用户选择）。**业务配置**（搜索关键词 `search_queries`、匹配权重 `matching`、翻页数 `max_pages_per_query`、JD上限 `max_total_results`）已迁移至 `instances/campaigns/` 和 `instances/strategies/`。详见 `config_assembler.py` 的三层组装逻辑。

当前文件内容（约 13 行）：

```yaml
filters:
  exclude_companies: []
llm:
  model: deepseek-v4-pro
  provider: deepseek
market_analysis:
  batch_size: 5
  jd_max_chars: 6000
  max_fetch_jd: 100
  max_pages: 4
sort_mode: date
user: li_ming
```

完整配置项汇总：

| 配置段 | 配置项 | 默认值 | 说明 |
|--------|--------|--------|------|
| `user` | — | `"li_ming"` | **当前使用的用户画像文件名**（不含 `.yaml` 后缀），对应 `instances/users/{user}.yaml`。`load_profile()` 和 `/api/config/yaml/me` 均通过此字段定位画像 |
| `llm` | `provider` | `"deepseek"` | `deepseek` / `qwen` / `glm` |
| `llm` | `model` | `"deepseek-v4-pro"` | 模型名称 |
| `llm` | `base_url` | （可选） | 自定义 API 端点 |
| `llm` | `api_key_env` | （可选） | 自定义环境变量名 |
| — | `sort_mode` | `"date"` | 全局排序：`"date"`（最新在前）/ `"relevance"`（相关度） |
| `filters` | `exclude_companies` | `[]` | 排除的公司名列表（大小写不敏感） |
| `market_analysis` | `max_pages` | `4` | 市场调研列表页翻页数（代码级 fallback: 3） |
| `market_analysis` | `max_fetch_jd` | `100` | 市场调研最多抓取 JD 数（代码级 fallback: 40） |
| `market_analysis` | `batch_size` | `5` | 市场调研 LLM 每批分析条数（代码级 fallback: 10） |
| `market_analysis` | `jd_max_chars` | `6000` | 市场调研单条 JD 截断长度（代码级 fallback: 2000） |

> **已迁移到 `instances/` 的配置项**：`search_queries`、`max_pages_per_query`、`max_total_results` 现位于 `instances/campaigns/{name}.yaml`；`matching` 段（`weight_profiles`、`weight_rules`、`min_match_score`、`borderline_rescore`、`borderline_range`、`top_n`）现位于 `instances/strategies/{name}.yaml`。这些业务配置通过 Campaign 三层组装机制合并，不再从 `search_config.yaml` 读取。

### 4.3 profiles/prompts.yaml — LLM 提示词配置

所有模块的 LLM 提示词均可通过此文件配置（共 15 个 prompt 模板）。**此文件是所有 prompt 的唯一来源**——任何 key 缺失时程序会抛出 `RuntimeError`，不允许静默回退。各模块通过 `_load_*_prompt()` helper 函数统一加载。

```yaml
agent:
  system_prompt                           # Agent 对话系统提示词

job_match:
  scoring_system_prompt                   # 匹配评分（<profile_summary> <weights_text> <score_formula>）

market_analysis:
  analysis_system_prompt                  # JD 数据提取（<job_category>）
  gap_analysis_prompt                     # 差距分析（<technical_skills> <profile>）
  report_prompt                           # 报告撰写（<job_category> <location> <sample_size> <analysis_json> <gap_analysis_json>）

resume:
  base_rules                              # 简历核心规则（<guide>）
  prompt_for_job                          # 匹配岗位模式（<template> <base_rules>）
  prompt_for_jd_text                      # JD 文本模式
  cover_letter_prompt                     # Cover Letter 生成
  resume_review_prompt                    # 简历审查（输入为简历 Markdown）
  aggregate_system_prompt                 # 方向聚合分析（<profile_summary>）
  prompt_for_direction_data               # 方向简历生成（<direction> <template> <base_rules>）
  cl_for_direction_data                   # 方向 Cover Letter（<direction>）
  translate_resume_prompt                 # 简历翻译（<target_lang>）
  translate_cl_prompt                     # Cover Letter 翻译（<target_lang>）
```

占位符用 `<name>` 尖括号格式（避免与 JSON `{}` 冲突），通过 `render_prompt()` 替换。

> **注意**：`agent.system_prompt` 的唯一来源是 `prompts.yaml`。`config.py` 中原有的硬编码 `SYSTEM_PROMPT` 已在 prompt 体系清理中删除——不再存在双版本同步问题。修改 Agent 行为只需编辑 `prompts.yaml` 即可。

### 4.4 profiles/resume_guide.yaml — 简历撰写指南

通过 `<guide>` 占位符注入到简历生成 prompt 中：

| 章节 | 内容 |
|------|------|
| `general` | 页数限制（1-2 页）、目标市场（香港 JobsDB） |
| `ats_rules` | 单栏布局、标准标题（Summary/Skills/Work Experience/Education/Certifications）、Bullet points、无表格/图片/图表 |
| `content_rules` | Summary 3 句结构、工作经历 "动词+做了什么+量化结果"格式、Skills 按市场需求排序（含好坏对比示例） |
| `weakness_handling` | 4 类弱点处理策略（经验年限不写精确年数/Java 不写精通/英语不夸大/公司规模不强调/教育背景不写 GPA） |
| `hk_specific` | 香港市场特殊规则（粤语优势在简历中标注等） |
| `cover_letter` | Cover Letter 撰写规则（250-350 词，开头-中间-结尾结构） |

### 4.5 profiles/resume_template.yaml — 简历模板

```yaml
format: "markdown"
output_style: "professional"
sections_order: [summary, skills, work_experience, projects, education, certifications]
customization:
  auto_reorder_skills: true       # 自动按目标岗位重排技能展示顺序
  auto_adjust_summary: true       # 自动调整 Summary 呼应 JD 关键词
  max_pages: 2                    # 最多 2 页
```

---

## 五、完整输出文件清单

### 5.1 找工作流程 — 每个 run 目录下

```
output/run_{YYYYmmdd_HHMMSS}/
│
├── scan_listings.json        # 第一层扫描全量列表（过滤前）
│                             字段：title, company, salary, snippet, url, job_id
│
├── rejected_jobs.json        # 被基础清洗排除的岗位
│                             字段：title, company, url, snippet, reject_reasons, reject_stage
│
├── filter_stats.json         # 过滤统计
│                             字段：scan_total, basic_rejected, filter_passed,
│                                   jd_fetched, full_jd_count, snippet_count, rejected_samples
│
├── raw_jobs.json             # 全量抓取的完整 JD（洗后）
│                             字段：title, company, location, salary, description, url,
│                                   jd_length, posted_date, classification, source, index
│
├── matched_jobs.json         # 达标岗位的匹配评分
│                             字段：title, company, url, description, scores（5维）,
│                                   total_score, llm_direction, weight_profile, confidence,
│                                   score_rounds, score_variance, skill_match, missing_skills,
│                                   reason, recommendation
│
├── unmatched_jobs.json       # 未达标岗位（低于 min_match_score）
│                             字段同 matched_jobs.json
│
├── job_report.md             # Markdown 匹配排名报告
│
├── direction_analysis.json   # 各方向聚合分析（三级技能分类）
│                             结构：{"payment": {...}, "web3": {...}, ...}
│                             每个方向含：direct_match, quick_learnable, hard_gap,
│                                        typical_responsibilities, common_bonus, resume_strategy
│
└── resumes/                  # 简历 + Cover Letter + 审查报告
    ├── resume_{label}_{date}_en.pdf           # 英文简历
    ├── resume_{label}_{date}_hk.pdf           # 繁體中文简历
    ├── resume_{label}_{date}_cn.pdf           # 简体中文简历
    ├── cover_letter_{label}_{date}_en.pdf     # 英文 Cover Letter
    ├── cover_letter_{label}_{date}_hk.pdf     # 繁體中文 Cover Letter
    ├── cover_letter_{label}_{date}_cn.pdf     # 简体中文 Cover Letter
    └── resume_review_{label}_{date}.json      # 审查报告
```

### 5.2 市场调研流程 — output/market/ 目录下

```
output/market/
│
├── market_{category}_{date}.md         # LLM 生成的专业分析报告（Markdown）
├── market_{category}_{date}.pdf        # 分析报告（PDF，REPORT_CSS 样式）
├── market_{category}_{date}.json       # 结构化分析结论（含全部分析 + 差距分析）
├── market_{category}_{date}_scan.json  # 全量扫描列表（过滤前，所有 listing）
└── market_{category}_{date}_jds.json   # 抓取的完整 JD 原文（有效 JD）
```

每次 `analyze_market()` 或 `batch_analyze_market()` 每个任务生成 **5 个文件**。

---

## 六、使用方式

### 6.1 环境准备

```bash
# 1. 安装 Python 依赖
pip install openai python-dotenv playwright beautifulsoup4 lxml ddgs pyyaml markdown flask

# 2. 安装 Playwright Chromium 浏览器
playwright install chromium

# 3. 配置 API Key
# 在 search_config.yaml 中选择 provider，在 .env 中设置对应 Key
echo "DEEPSEEK_API_KEY=your_key_here" > .env

# 4. 编辑个人画像
# 修改 instances/users/{user}.yaml 填入真实信息（文件名需与 search_config.yaml 中 user 字段一致）
```

### 6.2 启动

```bash
# 终端模式（必须指定 campaign）
python agent.py --campaign web3_hunt

# 查看可用的 campaign
# python agent.py（不带参数时会列出所有可用 campaign）

# Web UI 模式（无需 campaign 参数，在侧边栏下拉框选择）
python web_app.py
# 浏览器访问 http://127.0.0.1:5000
```

### 6.3 对话示例（终端模式）

```text
# ── 找工作全流程 ──
你: 帮我找工作
    → Agent 依次调用 search_jobs → match_jobs → generate_resume(by_direction=true)

# ── 匹配分析 ──
你: 看看匹配结果
    → list_matched_jobs → 显示排名列表（含五维分数、复评状态）
你: 为第1个生成简历
    → generate_resume(job_index=1) → 三语简历 + Cover Letter（7 个文件）

# ── 基于粘贴的 JD ──
你: [粘贴一段完整 JD] 根据这个生成简历
    → generate_resume(jd_text="...") → 7 个文件

# ── 单岗位查看 ──
你: 查看这个岗位 https://hk.jobsdb.com/job/12345678
    → fetch_job_detail(url="...") → 完整 JD 信息

# ── 市场调研 ──
你: 分析 Web3 市场行情
    → analyze_market(job_category="Web3") → 5 个文件（含差距分析）

你: 分析 Java Developer 市场行情（不需要差距分析）
    → analyze_market(job_category="Java Developer", include_gap_analysis=false)

你: 分析 science-technology 行业的 Solutions Engineer
    → analyze_market(job_category="Solutions Engineer", classification="science-technology")

你: 按最新发布分析 Java 市场行情
    → analyze_market(job_category="Java Developer", sort_by="date")

你: 按相关度分析 Web3 市场
    → analyze_market(job_category="Web3", sort_by="relevance")

# ── 批量市场调研 ──
你: 帮我分析 AI Agent，Web3，Java Developer 三个方向的市场行情
    → batch_analyze_market(tasks=[
        {"category": "AI Agent", "classification": "information-communication-technology"},
        {"category": "Web3"},
        {"category": "Java Developer"}
      ])

# ── 配置查看 ──
你: 看看我的档案
    → load_user_profile
你: 看看搜索配置
    → load_search_config

# ── 联网搜索 ──
你: 搜索香港 IT 行业薪资水平 2026
    → web_search(query="香港 IT 行业薪资水平 2026")

# ── 退出 ──
你: quit
    → 退出程序，清理 Playwright + 渲染器资源
```

### 6.4 Web UI 使用方式

Web UI 提供图形化操作界面。使用上与终端模式功能对等：

- **对话模式**：在输入框中输入自然语言指令（同终端模式的所有对话示例），系统通过 SSE 实时反馈进度和结果
- **快捷模式**：通过界面上的快捷操作一键触发「找工作」全流程，无需输入文本
- **模型切换**：通过界面切换 LLM Provider，立即生效
- **文件管理**：浏览历史 Run 列表、查看文件、下载任意输出文件
- **市场报告**：浏览所有市场调研报告文件

> 完整的 API 接口规范见 §3.4.3，前端需通过以下端点与后端交互：`/api/session` → `/api/chat` 或 `/api/pipeline` → `/stream/{sid}`（获取 SSE 事件流）→ `/api/runs`（获取历史）→ `/download/{path}`（下载文件）。

---

## 七、关键设计决策

| # | 决策 | 原因 |
|---|------|------|
| 1 | **全量抓取 JD 而非 LLM 预过滤** | 避免基于不完整信息（标题+摘要）误杀匹配岗位；完整 JD 让五维评分更准确；省掉 LLM 预过滤的 API 成本 |
| 2 | **数据驱动的字段提取器** | JobsDB `__NEXT_DATA__` JSON 结构频繁变化；`_FIELD_SPECS` 只需加新 key 名称，无需重写解析逻辑 |
| 3 | **完全放弃 requests 直接用 Playwright** | JobsDB 对所有 requests 请求返回 403，无头浏览器是唯一稳定的方式 |
| 4 | **Playwright 而非 wkhtmltopdf 渲染 PDF** | Chromium CSS 支持最完整、原生 CJK 字体、复用爬虫的 Playwright 依赖 |
| 5 | **简历英文先行 + 精确翻译** | 英文是通用求职语言；各语言独立生成会导致内容差异（面试时信息不一致）；翻译 prompt 严格控制结构一致性 |
| 6 | **简历质量自检 + 自动重写** | LLM 生成的简历可能暴露候选人弱点（年限、英语水平）、缺少量化、ATS 不友好；审查 → 反馈 → 自动修正 |
| 7 | **llm_call() 统一入口** | 消除 24 处分散调用点的维护负担；集中管理重试/退避/错误分类；任何新功能（缓存、fallback、token 统计）只需改一处 |
| 8 | **方向聚合跳过 default** | `default` 方向的岗位无法归类到具体方向，聚合分析无意义（JD 之间共性不足） |
| 9 | **LLM 判断方向优先 + 标题关键词回退** | LLM 基于完整 JD 判断更准确；标题关键词回退作为兜底（LLM 输出不可靠时） |

---

## 八、大小写敏感规则汇总

| 场景 | 参数 | 规则 |
|------|------|------|
| 市场分析 | `job_category` | **严格保留用户原始输入**。`"Web3"` 不会变成 `"web3"`, `"Java Developer"` 不会变成 `"java developer"` |
| 批量市场分析 | `tasks[].category` | 同上 |
| 市场分析 | `classification` | **严格保留原始输入**。`"science-technology"` 不会变成 `"Science-Technology"` |
| 批量市场分析 | `tasks[].classification` | 同上 |
| 岗位分类（权重选择） | 标题关键词匹配 | **大小写不敏感**（`classify_job()` 中 `title.lower()` + `kw.lower()`） |
| 公司排除 | `exclude_companies` | **大小写不敏感**（`basic_filter()` 中 `company_lower` 比较） |

---

## 九、错误处理与降级策略

| 场景 | 降级策略 |
|------|----------|
| LLM 匹配评分失败 | 记录错误，跳过该批次，继续处理其他批次 |
| LLM 简历审查失败 | 跳过审查，使用原始英文简历定稿 |
| LLM 简历审查 C/D → 重写失败 | 打印警告，使用原版简历 |
| LLM 市场分析批量失败 | 跳过该批次，继续处理其他批次 |
| LLM 市场报告生成失败 | 回退到 JSON dump 格式（确保分析数据不丢失） |
| LLM 翻译失败（某语言） | 跳过该语言，继续其他语言翻译 |
| LLM 429/超时/5xx | `llm_call()` 自动指数退避重试（最多 2 次） |
| LLM 401/403 | 直接抛出，不浪费重试时间 |
| 详情页抓取失败 | 使用列表页 snippet 兜底（标记 `source: "snippet"`） |
| 列表页解析全部失败 | 4 层回退策略（NEXT_DATA → HTML 补充 → Card 解析 → `<a>` 链接提取） |
| Playwright 浏览器失效 | 健康检查探活 + 自动重启 |
| PDF 渲染失败 | 返回 None，文件追踪中无 PDF 记录，不影响其他输出 |

---

## 十、项目亮点总结

1. **双入口架构**：终端 CLI + Web UI（Flask + SSE），共用同一套 Agent 和工具系统
2. **统一 LLM 调用层**：`llm_call()` 收敛 24 处调用点 + 内建指数退避重试 + 错误分类
3. **多 Provider 支持**：DeepSeek / Qwen / GLM 运行时动态切换，不重启、立即生效
4. **全量抓取 + 精准评分**：三层漏斗不经过 LLM 预过滤，确保匹配评分基于完整 JD
5. **数据驱动爬虫**：通用字段提取器 + 4 层解析回退 + GraphQL 模式支持，适应 JobsDB 页面结构变化
6. **动态权重匹配**：5 种权重方案 + LLM 自动判断方向 + 及格线复评取平均 + 置信度标注
7. **3 种简历模式**：方向聚合（数据驱动批量投递）/ 匹配岗位 / JD 文本
8. **三语输出 + 质量闭环**：英文先行 → 审查评分 → 不合格自动重写 → 精确翻译，每次 7 个文件
9. **独立市场调研**：四阶段流程 + 11+ 维度分析 + 差距分析（含可执行学习路径）+ 批量分析
10. **全流程文件追踪**：每轮对话后自动汇总生成的文件列表（路径 + 大小）
11. **双模式 emit**：`threading.local()` 实现终端 print / Web SSE 自动切换
12. **Prompt 全配置化**：15 个 prompt 模板通过 YAML 控制，`<key>` 模板引擎支持动态替换
13. **多层次降级**：详情页失败 → snippet 兜底；审查失败 → 跳过；报告生成失败 → JSON dump 保底；浏览器失效 → 自动重启