# JobsDB 智能求职 Agent - 项目完整介绍

> 一个基于 LLM + 工具调用架构的全自动求职系统，覆盖「职位搜索 - 智能筛选 - 匹配评分 - 简历生成 - 市场调研」完整链路。

---

## 一、项目概述

### 1.1 项目定位

本项目是一个 **AI Agent 驱动的自动化求职助手**，支持两种交互模式（终端对话 / Web UI），自动完成以下流程：

1. 从 JobsDB 网站批量抓取职位信息（Playwright 无头浏览器）
2. 基础清洗（排除空标题 + 排除公司）后全量抓取完整 JD
3. 从技能、经验、职级、行业、加分项 5 个维度对岗位进行匹配评分（动态权重 + 及格线复评）
4. 根据目标岗位按方向聚合后自动生成三语简历 + Cover Letter（PDF 格式，含质量自检）
5. 独立的「市场调研」模块：指定岗位类别，搜索并分析市场行情（技能需求/薪资/差距分析）

### 1.2 技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| 编程语言 | Python 3.13 | 主开发语言 |
| LLM | DeepSeek / Qwen / GLM（可配置） | 通过 OpenAI SDK 兼容接口调用，可在 search_config.yaml 或 Web UI 中切换 |
| 网页抓取 | Playwright 无头浏览器（主） | JobsDB 对所有 requests 请求返回 403，已全面切换 Playwright |
| HTML 解析 | BeautifulSoup (lxml) + JSON | BS4 做 DOM 辅助解析，核心数据来自页面内嵌的 `__NEXT_DATA__` JSON |
| PDF 渲染 | Playwright/Chromium | Markdown -> HTML -> PDF 浏览器原生渲染，两个独立浏览器实例（爬虫 + 渲染器各一个） |
| 网络搜索 | DuckDuckGo (ddgs) | 通用联网搜索能力 |
| Web 框架 | Flask + SSE | Web UI 服务器，SSE (Server-Sent Events) 实现实时进度推送 |
| 前端 | 原生 HTML/CSS/JS（单页应用） | static/index.html，含侧边栏、对话区、进度日志、文件管理等 |
| 配置管理 | YAML | 用户画像、搜索策略、Prompt、简历模板/指南均为 YAML |
| 环境管理 | python-dotenv | API Key 通过 .env 文件管理 |

### 1.3 项目结构

```text
D:\job-agent/
|
|-- agent.py                  # [入口] Agent 主循环 - 终端对话交互 + 工具调用循环
|-- web_app.py                # [入口] Flask Web UI - SSE 实时推送 + 直接流水线模式
|-- config.py                 # [配置中心] LLM Client 管理、YAML 加载、JSON 解析、文件追踪、emit 双模式输出
|-- tools_defs.py             # [工具注册] 14 个工具的 JSON Schema 定义 + 执行分发 + 去重
|-- tools_basic.py            # [基础工具] 时间/文件/搜索/配置查看/单岗位抓取
|
|-- scraper.py                # [爬虫] JobsDB 页面抓取（~1021 行，最大模块），4 层列表解析 + 3 层详情解析
|-- job_search.py             # [搜索] 三层漏斗搜索（扫描 → 基础清洗 → 全量抓取 JD）
|-- job_match.py              # [匹配] LLM 五维度评分 + 动态权重 + 及格线复评
|-- resume_gen.py             # [简历] 5 模式生成 + 英文先行 + 三语翻译 + 质量自检
|-- pdf_renderer.py           # [渲染] Markdown -> HTML -> PDF（独立 Playwright 实例）
|-- market_analysis.py        # [市场] 独立市场调研：JD 采集 → LLM 分析 → 差距分析 → 报告生成
|
|-- profiles/                 # [配置文件目录]
|   |-- me.yaml               #     用户个人画像（技能/经历/求职意向/战略定位）
|   |-- search_config.yaml    #     搜索策略 + LLM 配置 + 匹配权重 + 市场调研参数
|   |-- prompts.yaml          #     LLM 提示词配置（17 个 prompt 模板）
|   |-- resume_template.yaml  #     简历模板（章节顺序/格式/页数限制）
|   |-- resume_guide.yaml     #     简历撰写指南（ATS 规则/内容规则/弱点处理/香港市场）
|
|-- static/
|   |-- index.html            #     Web UI 前端（单页应用，含 SSE 流式交互）
|
|-- output/                   # [输出目录]
|   |-- run_{timestamp}/      #     每次"找工作"流程的输出目录
|   |   |-- scan_listings.json    #   第一层全量扫描列表
|   |   |-- rejected_jobs.json    #   被基础清洗排除的岗位
|   |   |-- raw_jobs.json         #   全量抓取的完整 JD
|   |   |-- filter_stats.json     #   过滤统计
|   |   |-- matched_jobs.json     #   匹配评分结果（达标岗位）
|   |   |-- unmatched_jobs.json   #   未达标岗位
|   |   |-- job_report.md         #   匹配分析报告
|   |   |-- direction_analysis.json # 方向聚合分析结果
|   |   |-- resumes/              #   简历 + Cover Letter + 审查报告
|   |-- market/               #     市场调研输出（每组 5 个文件）
|
|-- .env                      # API Key（DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / GLM_API_KEY）
|-- CONFIG_GUIDE.md            # 配置文件详细说明（独立手册，457 行）
|-- RESUME_PROMPTS_FOR_REVIEW.md  # 简历 prompt 审查汇总（含修改指南）
|-- .venv/                    # Python 虚拟环境
```

---

## 二、系统架构

### 2.1 整体架构：双入口 + Agent-Tool Calling 模式

系统支持两个入口，共用同一套工具系统和 LLM 客户端：

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
│  ┌─────────────────────────────┐  │                │
│  │       config.py             │  │                │
│  │   LLM Client + emit 双模式  │  │                │
│  └─────────────────────────────┘  │                │
│                │                   │                │
│                ▼                   │                │
│  ┌─────────────────────────────┐  │                │
│  │      tools_defs.py          │  │                │
│  │  14 个工具的 JSON Schema    │  │                │
│  │  + 执行分发 + 去重          │  │                │
│  └─────────────────────────────┘  │                │
│                │                   │                │
│     ┌──────────┼──────────┬────────┴──────────┐   │
│     ▼          ▼          ▼                   ▼   │
│  tools_     job_       job_       resume_    market_ │
│  basic     search     match       gen      analysis │
│     │          │          │          │          │    │
│     │      scraper.py      │    pdf_renderer.py     │
│     │     (网页抓取)        │     (PDF渲染)          │
│     ▼          ▼          ▼          ▼          ▼   │
│  [控制台/  [output/      [output/    [output/  [output/
│   SSE]     run_*/]      run_*/]    run_*/]  market/] │
└──────────────────────────────────────────────────┘
```

**两种运行时模式**：

| 触发方式 | 入口 | 特点 |
|---------|------|------|
| 终端 CLI | `python agent.py` | 交互式对话，LLM 决定工具调用顺序 |
| Web 前端按钮 (`/api/pipeline`) | `python web_app.py` | 直接调用 search→match→resume 三步函数，不经过 LLM 决策，更快 |
| Web 对话框 (`/api/chat`) | `python web_app.py` | 同 CLI 模式，LLM Agent 决策，通过 SSE 推送进度 |

### 2.2 核心工作流

用户说「帮我找工作」或在 Web 前端点击对应按钮时，自动执行三步流水线：

```text
search_jobs()  -->  match_jobs()  -->  generate_resume(by_direction=True)
   |                    |                    |
   v                    v                    v
三层漏斗抓取        五维匹配评分         方向聚合 + 三语简历PDF
(扫描→清洗→JD)   (动态权重+复评)     (英文先行→审查→翻译)
```

---

## 三、模块详解

### 3.1 agent.py — Agent 主入口（终端模式）

**职责**：对话循环 + 工具调用编排

**核心流程**：
1. 初始化 messages（含系统 prompt）
2. 用户输入 → 追加到 messages → 调用 LLM
3. 如果 LLM 返回 `tool_calls`，进入工具调用循环：
   - 去重 → 逐个执行 → 结果追加到 messages → 再次调用 LLM
4. LLM 返回最终文本回复 → 打印 → 打印本轮文件总览

**关键设计**：
- **工具去重** (`deduplicate_tool_calls`)：LLM 偶尔会重复调用同一工具，通过 `{name}:{arguments}` 去重
- **文件追踪** (`print_session_summary`)：每轮对话后打印生成的文件列表（路径 + 大小）
- **资源清理**：退出时调用 `cleanup_playwright()` 和 `cleanup_renderer()` 释放浏览器实例

---

### 3.2 config.py — 共享配置中心

**职责**：LLM Client 管理、YAML 加载、JSON 解析、文件追踪、emit 双模式输出、Run 管理、Prompt 模板引擎

**关键实现**：

**（1）多 Provider LLM Client**

```python
_LLM_PRESETS = {
    "deepseek": {"base_url": "https://api.deepseek.com", "default_model": "deepseek-chat"},
    "qwen":     {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen3.6-plus"},
    "glm":      {"base_url": "https://open.bigmodel.cn/api/paas/v4", "default_model": "glm-5.1"},
}
```

`switch_model(provider, model)` 可运行时切换 LLM，原地修改全局 client 的 `base_url` 和 `api_key`（所有模块持有同一引用，立即生效），同时回写 search_config.yaml。`get_model_info()` 可查询当前 provider、model 及所有可选预设。

**（2）emit 双模式输出**

```python
def emit(text):
    q = getattr(_emit_local, "queue", None)
    if q is not None:
        q.put({"type": "progress", "text": str(text)})  # Web SSE 模式
    else:
        print(text)  # 终端模式
```

通过 `threading.local()` 实现线程隔离。Web 模式下每个请求线程有独立的 SSE 队列，终端模式直接 print。

**（3）JSON 解析器（多层容错）**

```python
def parse_json_response(text):
    # 策略 1：去除 ```json ``` 代码块 → json.loads()
    # 策略 2：find("[") / rfind("]") 截取 JSON 数组
    # 策略 3：find("{") / rfind("}") 截取 JSON 对象
```

**（4）Prompt 模板引擎**

```python
load_prompts()        # 加载 prompts.yaml（有缓存），缺失时返回空 dict
render_prompt(tpl, **kw)  # 替换 <key> 占位符（用尖括号避免与 JSON {} 冲突）
get_system_prompt()   # 获取 Agent 系统提示词，优先从 prompts.yaml 读取，缺失回退到硬编码默认值
```

**（5）Run 目录管理**

```python
start_new_run()       # 创建 output/run_{timestamp}/ 目录
get_current_run_dir() # 获取当前活跃的 run 目录
get_latest_run_dir()  # 查找最近一次 run（按文件名排序）
```

**（6）文件追踪系统**

`track_file()` 记录生成的文件 → `get_session_files()` 获取并清空 → Web 模式返回给前端展示。

---

### 3.3 tools_defs.py — 工具注册与执行引擎

**职责**：定义所有工具的 JSON Schema（OpenAI Function Calling 格式）+ 执行分发 + 去重

**注册的 14 个工具**：

| 工具名 | 来源模块 | 参数 | 功能 |
|--------|----------|------|------|
| `get_current_time` | tools_basic | 无 | 获取当前日期时间（中文格式） |
| `write_file` | tools_basic | filename, content | 写入文件到 output/ |
| `read_file` | tools_basic | filename | 读取 output/ 中的文件 |
| `list_files` | tools_basic | 无 | 列出当前 run + market 目录文件 |
| `web_search` | tools_basic | query, max_results | DuckDuckGo 联网搜索 |
| `load_user_profile` | tools_basic | 无 | 查看 `profiles/me.yaml` |
| `load_search_config` | tools_basic | 无 | 查看 `profiles/search_config.yaml` |
| `search_jobs` | job_search | sort_by（可选） | 三层漏斗搜索，支持按日期或相关度排序 |
| `match_jobs` | job_match | 无 | 五维匹配评分 |
| `generate_resume` | resume_gen | by_direction / job_index / jd_text / role_direction（均可选） | 5 种模式简历生成 |
| `list_matched_jobs` | job_match | 无 | 查看匹配结果列表 |
| `fetch_job_detail` | tools_basic | url | 抓取单个岗位完整 JD |
| `analyze_market` | market_analysis | `job_category`, `location`, `include_gap_analysis`, `classification`, `sort_by`（可选） | 单类市场调研 |
| `batch_analyze_market` | market_analysis | `tasks`, `location`, `include_gap_analysis` | 批量市场调研 |

**执行分发**：

```python
def execute_tool(tool_call):
    func_name = tool_call.function.name
    args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
    func = tool_map.get(func_name)
    result = func(**args) if args else func()
    return result
```

**去重机制**：`deduplicate_tool_calls()` 以 `{name}:{arguments}` 为 key 去重，跳过的调用追加占位 tool result 防止 LLM 报错。

---

### 3.4 web_app.py — Web UI 服务器

**职责**：Flask Web 服务器 + SSE 流式事件推送 + Session 管理 + 直接流水线执行

**架构要点**：

- **Session 管理**：每个浏览器会话通过 `POST /api/session` 分配 `sid`（8 位 UUID），独立维护 messages 历史和 SSE 推送队列
- **全局 Agent 锁** (`_agent_lock`)：Playwright 不支持并发，确保同一时间只有一个 Agent 执行。新请求在锁被占用时返回 429
- **队列清理**：每次新请求前清空旧的 SSE 队列事件，防止残留数据干扰
- **两种执行路径**：
  - `/api/chat` → `_run_agent_turn()`：LLM Agent 模式（同终端 agent.py 逻辑）
  - `/api/pipeline` → `_run_pipeline()`：直接执行 `search_jobs → match_jobs → generate_resume(by_direction=True)` 三步流水线，仅支持 `action="search_match"`

**SSE 事件类型**：

| type | 含义 |
|------|------|
| `progress` | emit() 输出的进度文本 |
| `status` | 状态提示（如 "Agent 正在工作..."） |
| `tool_call` | 正在调用的工具名和参数 |
| `done` | 执行完成，携带 `reply` 文本和 `files` 文件列表 |
| `error` | 执行出错 |
| `ping` | 30 秒心跳，保持 SSE 连接 |

**其他 API**：

| 路由 | 方法 | 功能 |
|------|------|------|
| `/` | GET | 提供 static/index.html 前端页面 |
| `/api/session` | POST | 创建新会话，返回 `sid` |
| `/api/chat` | POST | LLM Agent 对话（后台线程执行） |
| `/api/pipeline` | POST | 直接执行 search→match→resume 流水线 |
| `/stream/<sid>` | GET | SSE 事件流（实时推送进度和结果） |
| `/api/runs` | GET | 列出所有 run 目录及元数据（阶段、岗位数量） |
| `/api/runs/<id>/files` | GET | 查看指定 run 的文件列表 |
| `/api/files` | GET | 列出 output/ 下所有文件 |
| `/api/market/files` | GET | 列出 output/market/ 下所有文件 |
| `/api/config/model` | GET | 获取当前 LLM provider/model 配置 |
| `/api/config/model` | POST | 运行时切换 LLM provider/model |
| `/download/<path>` | GET | 文件下载 |

---

### 3.5 tools_basic.py — 基础工具函数

**职责**：提供基础能力（时间、文件操作、DuckDuckGo 搜索、配置查看、单岗位抓取）

**关键实现**：

- **时间获取**：返回中文格式 `2026年04月07日 14:30:00 星期一`
- **文件操作**：限定在 `output/` 目录内，写入时自动创建子目录
- **DuckDuckGo 搜索**：使用 `ddgs` 库，默认 5 条结果，格式化输出标题+摘要+链接
- **配置查看**：将 YAML dict 转为 JSON 字符串输出（JSON 格式对 LLM 更友好）
- **单岗位抓取**：调用 `scraper.fetch_job_detail()`，格式化输出标题/公司/地点/薪资/JD

---

### 3.6 scraper.py — JobsDB 网页爬虫（核心模块，~1021 行）

**职责**：抓取 JobsDB 的职位列表页和详情页，支持多层解析策略 + 反爬回退

#### 3.6.1 HTTP 请求层

- **主引擎**：Playwright 无头浏览器（JobsDB 对所有 requests 请求返回 403，已放弃 requests 方案）
- **反爬措施**：
  - 完整浏览器 Headers + 自定义 User-Agent
  - `navigator.webdriver` 属性覆盖 + `window.chrome` 注入
  - Cloudflare 挑战页检测与额外等待
  - 翻页间隔随机延迟 `random.uniform(1.5, 3.0)` 秒
  - 失败时重建浏览器重试（1 次）

#### 3.6.2 列表页扫描（4 层解析策略）

每次翻页会依次尝试以下策略，策略 2 可与策略 1 配合使用（补充标题），策略 3/4 仅在策略 1 完全无结果时触发：

```text
策略 1: __NEXT_DATA__ 中的 JSON jobs 数组（最优先）
  JobsDB 是 Next.js 应用，页面内嵌 <script id="__NEXT_DATA__"> 标签
  通过 _find_jobs_array() 递归搜索 jobs 数组（深度优先，max_depth=10）
  支持 GraphQL edges 模式（{node: {...}}）
  对每条 job 用 _extract_field() 提取 title/company/salary/location/job_id 等字段
    |
    ├── 如果策略 1 有结果，但超半数 title 为空 → 策略 2 补充
    |   策略 2: HTML DOM 补充标题
    |   从 HTML job card 元素提取标题，通过 _build_html_title_map() 构建 {job_id: title} 映射
    |   补充 __NEXT_DATA__ 中缺失的标题字段（两阶段：card 选择器 → <a> 标签链接文本回退）
    |
    v 如果策略 1 本页完全无结果 (page_count == 0) → 策略 3
策略 3: 纯 HTML Card 解析
  _parse_html_job_cards() 从 DOM 中完整解析 job card 元素
  多种 CSS 选择器回退：
    article[data-testid="job-card"] → div[data-job-id] → div[class*="job-card"]
  提取：title, company, location, salary, snippet, job_id
    |
    v 如果策略 3 也解析不到 (page_count 仍为 0) → 策略 4
策略 4: <a> 标签链接提取（最后兜底）
  从所有 <a> 标签中提取 /job/ID 格式的链接
  过滤掉太短 (<3 字符) 或太长 (>200 字符) 的链接文本
```

#### 3.6.3 数据驱动的字段提取器

为应对 JobsDB 频繁变化的 JSON 结构，设计了 `_FIELD_SPECS` + `_extract_field()` 系统：

```python
_FIELD_SPECS = {
    "title": {
        "direct_keys": ["title", "jobTitle", "displayTitle", "heading", ...],  # Phase 1: 直接查找
        "parent_keys": ["job", "content", "details", ...],                     # Phase 2: 嵌套父 key
        "sub_keys": ["title", "jobTitle", ...],                                # Phase 2: 子 key
        "recursive": True, "max_depth": 3, "min_len": 2,                      # Phase 3: 递归搜索
    },
    "company": { ... }, "salary": { ... }, "location": { ... },
}
```

结构变化时只需在 `_FIELD_SPECS` 中增加新的 key 名称，无需改动解析逻辑。

#### 3.6.4 详情页解析（3 层策略）

```text
策略 1: __NEXT_DATA__ 中的 pageProps → jobDetail
策略 2: JSON-LD 结构化数据 (<script type="application/ld+json"> 中的 JobPosting Schema.org 对象)
策略 3: HTML DOM 直接解析 (h1 标题 + 多种选择器找职位描述)
```

#### 3.6.5 URL 工具

- `normalize_jobsdb_url(url)` — 统一为 `https://hk.jobsdb.com/job/{id}` 格式（去重用）
- `is_listing_page(url)` / `is_job_detail_url(url)` / `classify_urls(urls)` — URL 分类

---

### 3.7 job_search.py — 搜索管道

**职责**：编排完整搜索流程：配置读取 → 扫描 → 清洗 → 抓取 JD → 保存

#### 三层搜索设计

```text
第一层（扫描）: scan_jobsdb_listings()
  多组关键词 × 多页翻页，跨搜索词去重
  结果：title, company, salary, snippet, url, job_id
            |
            v
第二层（清洗）: basic_filter()
  排除空标题 + 排除公司（来自 search_config.yaml 的 exclude_companies）
  成本：0（纯代码规则，毫秒完成）
  诊断：如果超 80% 标题为空，返回详细错误提示，建议检查爬虫
            |
            v
第三层（抓取）: fetch_multiple_details()
  对清洗后的岗位全量抓取完整 JD（上限 max_total_results）
  随机延迟 1.5~3.5 秒防封
  降级策略：详情页抓取失败 → 使用列表页 snippet 兜底（标记 source: "snippet"）
            |
            v
保存到 output/run_{timestamp}/:
  raw_jobs.json + scan_listings.json + rejected_jobs.json + filter_stats.json
```

**设计理念**：不做 LLM 预过滤，直接全量抓取完整 JD，将精确判断交给 match_jobs 的五维评分。虽然抓取时间更长（100 条约 150~350 秒），但能避免基于不完整信息（标题+摘要）误杀真正匹配的岗位。

**排序控制**：通过 `sort_by` 参数切换搜索排序。`"date"` 按发布时间（最新在前，对应 `?sortmode=ListedDate`），`"relevance"` 按相关度（JobsDB 默认）。全局默认在 `search_config.yaml` 的 `sort_mode` 中配置，Web UI 侧边栏提供一键切换。

---

### 3.8 job_match.py — LLM 五维匹配评分

**职责**：读取搜索结果 + 用户画像，用 LLM 从 5 个维度评分，支持动态权重和及格线复评

#### 五维评分体系（动态权重）

根据岗位方向自动选择权重方案：

| 方案 | 技能 | 经验 | 职级 | 行业 | 加分 | 适用场景 |
|------|------|------|------|------|------|----------|
| default | 30% | 25% | 15% | 15% | 15% | 通用岗位 |
| technical | 35% | 20% | 15% | 15% | 15% | 纯技术开发岗 |
| solutions | 25% | 20% | 15% | 20% | 20% | SE/集成工程师 |
| web3 | 25% | 15% | 10% | 30% | 20% | Web3/区块链岗位 |
| payment | 25% | 20% | 10% | 25% | 20% | 支付/结算岗位 |

**方向判断**：LLM 在评分时同步返回 `direction` 字段（基于完整 JD），有效则采用为 `llm_direction`；LLM 未返回有效方向时回退到 `classify_job()` 标题关键词匹配。

**评分流程**：
1. 第一轮：所有岗位用 default 权重统一打分，同时 LLM 返回 direction
2. 用 `llm_direction` 对应权重重新计算 total_score（如 LLM 判断方向为 web3，则用 web3 权重重算）
3. 排序 + URL 去重
4. 第二轮（可选）：及格线附近岗位（`min_match_score ± borderline_range`）逐个用其方向权重重新评分
   - 五维取两轮平均，total_score 重算
   - 两轮波动 ≤10 标记 `confidence: verified`，>10 标记 `confidence: uncertain`
5. 保留 ≥ min_match_score 的岗位（上限 top_n）

**推荐等级**：≥80 🟢 强烈推荐 | ≥60 🟡 可考虑 | <60 🔴 不推荐

**额外评估维度**（prompts.yaml 中扩展，不参与加权计算）：
- `english_risk`（低/中/高）：评估岗位英语要求对候选人的阻碍程度
- `interview_risk`（低/中/高）：评估面试流程中算法/八股文等候选人的薄弱环节风险

---

### 3.9 resume_gen.py — 多模式简历生成

**职责**：根据不同输入生成三语简历 + Cover Letter（英文先行 → 审查 → 翻译）

#### 5 种生成模式

| 模式 | 触发方式 | 数据来源 | 适用场景 |
|------|---------|----------|---------|
| 方向聚合 | `by_direction=true` | matched_jobs 聚合 + `me.yaml` | 批量投递首选：search+match 后按方向生成 |
| 匹配岗位 | `job_index=1` | matched_jobs 单条 + `me.yaml` | 对某个高分岗位单独定制 |
| JD 文本 | `jd_text="..."` | 用户粘贴的 JD + `me.yaml` | 在其他平台看到的岗位 |
| 岗位方向 | `role_direction="SE"` | LLM 对角色的理解 + `me.yaml` | 没有具体 JD，只有方向 |
| 通用简历 | 不传参数 | `me.yaml` | 投递通用平台 |

#### 方向聚合模式详细流程

1. 读取 `matched_jobs.json`，按 `llm_direction`（payment/solutions/web3/technical）分组
   - **跳过 `default` 方向**的岗位（无法归类，不参与聚合）
   - **每个方向至少需要 2 个达标岗位**，不足则跳过该方向
2. 每个方向调用 LLM 聚合分析，取前 15 个岗位的 JD（截断至 2000 字符），提取共性需求并做三级技能分类：
   - **direct_match**：候选人具备 → 简历重点展示
   - **quick_learnable**：不直接具备但属于通用技术栈且有相近基础 → Skills 列出不标精通，Cover Letter 表态
   - **hard_gap**：高门槛/不相关 → 简历不提
3. 保存聚合数据到 `direction_analysis.json`
4. 对每个方向生成三语简历 + Cover Letter（复用英文先行 + 翻译 + 审查流程）

#### 英文先行 + 翻译流程

```text
英文简历生成 → 审查（A/B/C/D 评级）→ 不合格(C/D)则附反馈重写 → 英文定稿
  → 英文 Cover Letter 生成
    → 将定稿英文简历精确翻译为繁中/简中
    → 将定稿英文 Cover Letter 翻译为繁中/简中
```

翻译规则：
- 保持完全一致的结构、段落顺序和 bullet points 数量
- 技术术语保留英文原文
- 公司名称、学历证书名称保留英文
- 数字和量化指标保持不变

#### 质量自检机制

英文简历定稿前调用 `resume_review_prompt` 审查：
- 检查 6 秒测试、关键词覆盖、业务/技术平衡、量化程度、弱点暴露、ATS 友好度
- 输出 JSON 审查报告（`resume_review_{label}_{date}.json`）
- 总评 C 或 D → 自动将反馈注入 prompt 重新生成（最多重写一次）

#### 每次调用生成 7 个文件

```text
resume_{label}_{date}_en.pdf      # 英文简历（主版本）
resume_{label}_{date}_hk.pdf      # 繁體中文简历
resume_{label}_{date}_cn.pdf      # 简体中文简历
cover_letter_{label}_{date}_en.pdf  # 英文 Cover Letter
cover_letter_{label}_{date}_hk.pdf  # 繁體中文 Cover Letter
cover_letter_{label}_{date}_cn.pdf  # 简体中文 Cover Letter
resume_review_{label}_{date}.json   # 审查报告
```

---

### 3.10 pdf_renderer.py — Markdown → PDF 渲染

**职责**：将 LLM 生成的 Markdown 简历/报告转换为专业排版的 A4 PDF

**渲染流程**：`Markdown → _fix_resume_markdown() 格式修复 → markdown_to_html() → 嵌入 CSS → Playwright Chromium page.pdf() → PDF`

**格式修复** (`_fix_resume_markdown`)：LLM 输出的 bullet points 之间常有空行，会导致 markdown 库生成 `<li><p>` 嵌套，渲染后在 PDF 中产生多余间距。此函数自动去除相邻 bullet 之间的空行。

**两个 CSS 样式**：
- `RESUME_CSS`：专业紧凑型（深灰 `#222` 章节标题、全大写、`1.5px solid #333` 下划线分隔、`@page { margin: 2cm }` + `page.pdf()` 层叠 margin `1.5cm/2cm`、打印分页优化）
- `REPORT_CSS`：深蓝 `#1a5276` 标题色、含表格样式（斑马纹）、更宽间距（用于市场分析报告）

**关键设计**：
- 两个独立的 Playwright 浏览器实例（scraper.py 和 pdf_renderer.py 各一个，避免冲突）
- 浏览器懒加载 + 全局复用 + 健康检查（`browser.contexts` 探活）+ 自动恢复
- 中文字体回退链：`Arial → Calibri → Microsoft JhengHei → PingFang HK → PingFang SC → SimHei → sans-serif`
- `python-markdown` 库优先，带 `extra/smarty/sane_lists` 扩展；缺失时回退内置简易转换器（支持标题/列表/粗体/斜体/链接/代码）
- `_render_in_thread()`：独立线程中完成完整 Playwright 渲染，应对 asyncio 事件循环冲突

---

### 3.11 market_analysis.py — 独立市场调研

**职责**：指定岗位类别，主动搜索 JobsDB 并全面分析市场行情

**四阶段流程**：

```text
Phase A: 数据采集
  搜索 JobsDB 列表页（翻 max_pages 页）→ 全量抓取完整 JD（有效 JD 存于内存）
            |
            v
Phase B: LLM 市场分析（分批处理）
  每批 batch_size 条 JD 发给 LLM
  LLM 提取：技术技能需求（排名 + 分类 + 工具 + 说明）、软技能需求、
           薪资范围（按级别）、经验要求分布、岗位职责共性、行业分布、
           关键趋势、语言要求、学历要求、公司画像、面试线索
  多批结果自动聚合（累加计数 / 去重 / 合并上述全部 11 个维度）
            |
            v
Phase C: 差距分析（可选，include_gap_analysis 控制）
  对比候选人画像 vs 市场需求
  输出：strengths（优势技能）、gaps（差距 + 可执行学习路径）、
        low_value_skills（低价值技能）、strategic_advice（策略建议）
            |
            v
Phase D: LLM 撰写报告 + 统一保存所有文件
  将结构化分析数据转为专业 Markdown 报告 → 渲染 PDF
  若 LLM 报告生成失败，回退到基础 JSON dump 格式
  保存：.md + .pdf + .json（结构化数据）+ _scan.json + _jds.json
```

**特点**：
- 不做预过滤，全量抓取 JD 后由 LLM 分析
- LLM 分析 prompt 强调技能名称具体化（如 "Ethers.js Web3 Library" 而非 "Web3"）
- 差距分析给出可执行的学习路径（每一步具体到"学什么、怎么学"）
- 支持 `batch_analyze_market()` 批量分析多个岗位类别
- 支持 `sort_by` 参数切换排序方式（`"date"` 按发布时间 / `"relevance"` 按相关度），Web UI 和 CLI 均可控制

---

## 四、配置文件说明

### 4.1 profiles/me.yaml — 用户画像

```yaml
# 基本信息：姓名、电话、邮箱、LinkedIn、GitHub、所在地
# 战略定位：核心画像、方向优先级、关键约束（英语/算法/经验）
# 求职意向：target_titles（按优先级排序）、target_industries、薪资期望、到岗时间
# 专业技能：按类别分组（数据库、API集成、编程语言、框架、区块链、DevOps、AI工具、业务能力、语言能力）
# 工作经历：公司/职位/时间/描述/技术栈/亮点/core_modules（含详细模块描述）
# 教育背景 / 项目经历 / 证书 / 自我评价
```

### 4.2 profiles/search_config.yaml — 搜索策略 + LLM 配置 + 匹配权重 + 市场调研参数

```yaml
llm:                              # LLM 配置（provider + model + 可选自定义 base_url）
sort_mode: "date"                 # 排序方式："date"=按发布时间 / "relevance"=按相关度
search_queries:                   # 搜索关键词组（keywords + location + classification + direction + sort_by可选）
filters:                          # 排除公司列表
max_pages_per_query: 3            # 每组关键词翻页数
max_total_results: 200            # 最终抓取 JD 上限

matching:                         # 匹配评分设置
  min_match_score: 45             # 最低达标分数
  top_n: 999                      # 保留 Top N
  borderline_rescore: true        # 及格线复评开关
  borderline_range: 8             # 复评区间 ±8 分
  weight_profiles:                # 5 种动态权重方案
  weight_rules:                   # 标题关键词 → 权重方案映射（4 类 + 关键词列表）

market_analysis:                  # 市场调研参数
  max_pages: 4                    # 列表页翻页数
  max_fetch_jd: 100               # 最多抓取 JD 数
  batch_size: 5                   # LLM 每批分析条数
  jd_max_chars: 6000              # 每条 JD 截断长度
```

### 4.3 profiles/prompts.yaml — LLM 提示词配置

所有模块的 LLM 提示词均可通过此文件配置（共 17 个 prompt 模板），各调用点在文件不存在时回退到硬编码默认值。

```yaml
agent:
  system_prompt                           # Agent 对话系统提示词

job_match:
  scoring_system_prompt                   # 匹配评分提示词（<profile_summary> <weights_text> <score_formula>）

market_analysis:
  analysis_system_prompt                  # JD 数据提取（<job_category>）
  gap_analysis_prompt                     # 差距分析（<technical_skills> <profile>）
  report_prompt                           # 报告撰写（<job_category> <location> <sample_size> <analysis_json> <gap_analysis_json>）

resume:
  base_rules                              # 简历核心规则（<guide>）
  prompt_for_job                          # 匹配岗位模式（<template> <base_rules>）
  prompt_for_jd_text                      # JD 文本模式
  prompt_for_role                         # 岗位方向模式（<role>）
  prompt_for_general                      # 通用模式
  cover_letter_prompt                     # Cover Letter
  resume_review_prompt                    # 简历自检（输入为简历 Markdown）
  aggregate_system_prompt                 # 方向聚合分析（<profile_summary>）
  prompt_for_direction_data               # 方向简历生成（<direction> <template> <base_rules>）
  cl_for_direction_data                   # 方向 Cover Letter（<direction>）
  translate_resume_prompt                 # 简历翻译（<target_lang>）
  translate_cl_prompt                     # Cover Letter 翻译（<target_lang>）
```

占位符使用 `<name>` 格式（避免与 JSON `{}` 冲突），通过 `render_prompt()` 替换。

> **注意**：`agent.system_prompt` 在 `prompts.yaml` 中的版本与 `config.py` 中的硬编码回退版本内容有所不同——`prompts.yaml` 版本包含详细的候选人战略定位和方向优先级，而 `config.py` 版本更简洁通用。两个版本都描述了 `generate_resume` 的全部 5 种模式（含 `by_direction`）。修改 Agent 行为时务必保持两者模式数量和工作流描述同步，内容细节可根据需要差异化。

### 4.4 profiles/resume_guide.yaml — 简历撰写指南

通过 `<guide>` 占位符注入到简历生成 prompt 中，包含：
- **general**：页数限制、目标市场
- **ats_rules**：单栏布局、标准标题等 ATS 友好规则
- **content_rules**：各段落内容规则（Summary 3 句话结构、工作经历"动词+成果"格式、Skills 按市场排序等），含好坏示例
- **weakness_handling**：弱点处理策略（经验年限/Java/英语/公司规模/教育），含规则和原因
- **hk_specific**：香港市场特殊要求（粤语优势等）
- **cover_letter**：Cover Letter 撰写规则

### 4.5 profiles/resume_template.yaml — 简历模板

```yaml
format: "markdown"
output_style: "professional"
sections_order: [summary, skills, work_experience, projects, education, certifications]
customization:
  auto_reorder_skills: true       # 自动按目标岗位重排技能顺序
  auto_adjust_summary: true       # 自动调整 Summary
  max_pages: 2                    # 最多 2 页
```

---

## 五、数据流 & 输出文件

### 5.1 找工作流程（search → match → resume）

```text
profiles/me.yaml + profiles/search_config.yaml
            │
            ▼
search_jobs() → 三层漏斗
    ├── scan_listings.json   # 第一层全量扫描列表
    ├── rejected_jobs.json   # 被基础清洗排除的岗位 + 原因
    ├── raw_jobs.json        # 全量完整 JD（title, company, description, url, jd_length, source）
    └── filter_stats.json    # 过滤统计
            │
            ▼
match_jobs() → 五维动态权重评分 + 及格线复评
    ├── matched_jobs.json    # 达标岗位（scores, total_score, llm_direction, weight_profile, confidence）
    ├── unmatched_jobs.json  # 未达标岗位
    └── job_report.md        # Markdown 排名报告
            │
            ▼
generate_resume(by_direction=true) → 方向聚合 + 三语简历
    ├── direction_analysis.json   # 各方向聚合分析（三级技能分类）
    ├── resume_*_{en,hk,cn}.pdf   # 三语简历 PDF
    ├── cover_letter_*_{en,hk,cn}.pdf  # 三语 Cover Letter PDF
    └── resume_review_*.json      # 简历审查报告
```

### 5.2 市场调研流程

```text
输入: job_category + location
            │
            ▼
analyze_market() → 全量抓取 + LLM 分析 + 差距分析 + 报告撰写
            │
            ▼
output/market/
  ├── market_{cat}_{date}.md           分析报告（Markdown）
  ├── market_{cat}_{date}.pdf          分析报告（PDF）
  ├── market_{cat}_{date}.json         LLM 结构化分析结论
  ├── market_{cat}_{date}_scan.json    全量扫描列表（过滤前）
  └── market_{cat}_{date}_jds.json     完整 JD 原文
```

---

## 六、关键设计决策

### 6.1 为什么全量抓取 JD 而不是先过滤？

全量抓取虽然耗时更长，但优势明显：
- 避免基于不完整信息（标题+摘要）误杀匹配岗位
- 完整 JD 让后续五维评分更准确
- 省掉 LLM 预过滤的 API 成本

### 6.2 为什么用数据驱动的字段提取器？

JobsDB 的 `__NEXT_DATA__` JSON 结构会随版本更新变化。数据驱动方式（`_FIELD_SPECS`）只需在配置中增加新 key 名称，无需重写解析逻辑。

### 6.3 为什么完全放弃 requests 直接用 Playwright？

JobsDB 对所有来自 requests 库的 HTTP 请求返回 403。Playwright 无头浏览器模拟真实浏览器环境，配合反检测脚本（`navigator.webdriver` 覆盖 + `window.chrome` 注入）可以稳定获取页面内容。

### 6.4 为什么用 Playwright 而不是 wkhtmltopdf 生成 PDF？

- Chromium 对 CSS 支持最完整（与浏览器一致）
- 原生支持 CJK 字体（中文简历必需）
- 复用 Playwright 依赖，不增加额外安装
- wkhtmltopdf 的 CSS 支持有限，中文排版问题多

### 6.5 为什么简历生成后要做自检？

LLM 生成的简历可能存在的问题：
- Summary 没有在 6 秒内传达核心价值
- Bullet points 偏向技术实现而非业务成果
- 暴露候选人弱点（具体工作年限、夸大英语水平等）
- 缺少关键行业关键词（影响 ATS 通过率）

通过审查反馈自动重写，确保产出质量。

### 6.6 为什么英文先行 + 精确翻译？

- 英文是世界通用求职语言
- 如果各语言独立生成，内容会有差异，可能导致面试时信息不一致
- 翻译 prompt 严格控制结构一致性、术语保留规则

---

## 七、使用方式

### 7.1 环境准备

```bash
# 1. 安装依赖
pip install openai python-dotenv playwright beautifulsoup4 lxml ddgs pyyaml markdown flask

# 2. 安装 Playwright 浏览器
playwright install chromium

# 3. 配置 API Key
# 在 search_config.yaml 中选择 provider，然后在 .env 中设置对应的 Key
echo "GLM_API_KEY=your_key_here" > .env

# 4. 编辑个人画像
# 修改 profiles/me.yaml 填入真实信息
```

### 7.2 运行

```bash
# 终端模式
python agent.py

# Web UI 模式
python web_app.py
# 访问 http://127.0.0.1:5000
```

### 7.3 对话示例

```text
你: 帮我找工作
    → Agent 自动调用 search_jobs + match_jobs + generate_resume(by_direction=true)

你: 按方向生成简历
    → generate_resume(by_direction=true)

你: 看看匹配结果
    → list_matched_jobs

你: 为第1个生成简历
    → generate_resume(job_index=1)

你: 生成 Solutions Engineer 方向的简历
    → generate_resume(role_direction="Solutions Engineer")

你: [粘贴一段 JD] 根据这个生成简历
    → generate_resume(jd_text="...")

你: 分析 Web3 市场行情
    → analyze_market(job_category="Web3")

你: 查看这个岗位 https://hk.jobsdb.com/job/12345678
    → fetch_job_detail(url="...")

你: quit
    → 退出程序，清理浏览器资源
```

---

## 八、项目亮点总结

1. **双入口架构**：终端 CLI + Web UI（Flask + SSE），共用同一套 Agent 和工具系统
2. **Agent 模式 + Pipeline 直连**：Web UI 支持 LLM Agent 决策模式（灵活）和直接流水线执行模式（快速）
3. **多 Provider 支持**：DeepSeek / Qwen / GLM 可配置切换，运行时动态切换不重启
4. **全量抓取 + 精准评分**：三层漏斗（扫描→清洗→全量抓取），确保匹配评分基于完整 JD
5. **数据驱动的爬虫**：通用字段提取器 + 4 层解析回退 + GraphQL edges 模式支持，适应 JobsDB 页面结构变化
6. **动态权重匹配**：5 种权重方案 + LLM 自动判断方向 + 及格线复评取平均 + 置信度标注
7. **5 种简历模式**：方向聚合（数据驱动批量投递）/ 匹配岗位 / JD 文本 / 岗位方向 / 通用简历
8. **三语输出 + 自检**：英文先行 → 审查自动重写 → 精确翻译，每次生成 7 个文件（简历 + CL × 3 + 审查报告）
9. **独立市场调研模块**：四阶段流程（采集→LLM分析→差距分析→报告），输出 5 个文件，支持批量分析
10. **全流程文件追踪**：每轮对话后自动汇总生成的文件列表
11. **双模式 emit 输出**：基于 `threading.local()` 的终端 print / Web SSE 自动切换
12. **Prompt 全配置化**：17 个提示词模板均可通过 prompts.yaml 调整，支持 `<key>` 占位符模板引擎
