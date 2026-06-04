# JobsDB 智能求职 Agent — 功能规格文档

> 面向产品经理和 UI 设计师的项目说明。涵盖完整的后端逻辑、用户交互流程、数据输入输出和 API 契约。
> 当前 UI 的实现参考见 `UI_CURRENT_REFERENCE.md`（仅供对照改代码使用，不是产品规格）。

---

## 一、项目概述

### 1.1 项目定位

一个 AI 驱动的香港 JobsDB 求职助手。用户通过自然语言与系统对话、或在界面上触发快捷操作，系统自动完成职位搜索、智能匹配评分、多模式简历生成和独立市场调研。

### 1.2 用户是谁

一位有 WaaS（Wallet-as-a-Service）支付系统经验的 Web3 后端工程师，目标岗位集中在支付工程师、方案工程师、Web3 后端开发等方向，工作地点在香港。用户画像详见配置：`profiles/me.yaml`。

### 1.3 系统能做什么（功能全景）

| 功能 | 用户怎么触发 | 系统产出 |
|------|-------------|---------|
| 找工作（全流程） | 对话「帮我找工作」或快捷按钮 | 搜索到岗位 → 匹配评分排名 → 按方向生成三语简历+CL |
| 查看匹配结果 | 对话「看看匹配结果」 | 已评分岗位的排名列表（五维分数） |
| 为特定岗位生成简历 | 对话「为第1个生成简历」 | 针对该岗位的三语简历+CL（7个文件） |
| 基于方向生成简历 | 对话「生成 SE 方向的简历」 | 面向该方向的三语简历+CL（7个文件） |
| 基于粘贴 JD 生成简历 | 粘贴 JD + 「根据这个生成简历」 | 针对该 JD 的三语简历+CL（7个文件） |
| 生成通用简历 | 对话「生成通用简历」 | 基于个人画像的通用三语简历+CL（7个文件） |
| 单类市场调研 | 对话「分析 Web3 市场行情」 | 搜索该类岗位 → 多维度分析报告+PDF+数据文件（5个文件） |
| 批量市场调研 | 对话「帮我分析 AI Agent，Web3，Java 三个方向」 | 依次执行多个单类调研 |
| 查看单个岗位详情 | 对话「查看这个岗位 [URL]」 | 该岗位的完整 JD 信息 |
| 查看用户档案 | 对话「看看我的档案」 | me.yaml 的内容 |
| 查看搜索配置 | 对话「看看搜索配置」 | search_config.yaml 的内容 |
| 联网搜索 | 对话「搜索 xxx」 | DuckDuckGo 搜索结果 |
| 切换 LLM 模型 | 界面操作或配置修改 | 实时切换 DeepSeek/Qwen/GLM |

---

## 二、用户交互模式

系统支持两种交互模式，共用同一套后端功能。

### 2.1 对话模式（Agent 模式）

用户通过自然语言描述需求。LLM 理解意图后，自动决策何时调用哪个工具、以什么参数调用。用户可以在一个对话中交替使用不同功能。

**执行方式**：`python agent.py`（终端），或 Web UI 对话框。

### 2.2 快捷模式（Pipeline 模式）

用户通过界面按钮一键触发「找工作」全流程。系统按固定顺序执行搜索→匹配→简历生成，不经过 LLM 决策，更快。

**执行方式**：Web UI 中触发 `/api/pipeline` 端点，传入 `action="search_match"`。

**对比**：

| | Agent 模式 | Pipeline 模式 |
|---|---|---|
| 触发方式 | 对话输入 | 快捷按钮 |
| 执行决策 | LLM 决定调用哪些工具 | 固定调用 search → match → resume |
| 灵活性 | 高（可单独执行某一步或组合） | 低（固定三步） |
| 速度 | 较慢（LLM 多轮决策） | 较快（直接调用函数） |
| 适用场景 | 探索式操作 | 一键出结果 |

### 2.3 实时反馈机制（SSE）

无论哪种模式，后端通过 SSE（Server-Sent Events）向界面推送实时进度：

| 事件类型 | 含义 | 数据字段 |
|---------|------|---------|
| `progress` | 后端 `emit()` 输出的日志文本 | `{"type": "progress", "text": "..."}` |
| `status` | 阶段状态提示 | `{"type": "status", "text": "正在..."}` |
| `tool_call` | 正在调用的工具 | `{"type": "tool_call", "tool": "search_jobs", "args": "{}"}` |
| `done` | 执行完成 | `{"type": "done", "reply": "...", "files": [["文件路径", "描述"], ...]}` |
| `error` | 执行出错 | `{"type": "error", "text": "..."}` |
| `ping` | 30 秒心跳 | `{"type": "ping"}` |

> **UI 设计注意**：以上事件类型是前端必需处理的 SSE 协议。`done` 事件中的 `reply` 字段是 LLM 生成的 Markdown 文本（应支持格式化渲染），`files` 数组是本次执行生成的所有文件列表。

---

## 三、功能详细说明

### 3.1 找工作（三步全流程）

用户说「帮我找工作」或点击快捷按钮后，系统按固定顺序执行三步：

#### 第一步：职位搜索

**触发条件**：无需前置条件。

**用户输入（可见行为）**：无需手动输入参数。系统从配置文件 `search_config.yaml` 读取搜索关键词组、翻页数、结果上限等。

**系统行为（底层逻辑）**：

1. 从配置读取多组搜索关键词（每组含：`keywords`、`location`、`classification` 行业分类标签、`direction` 方向标记）
2. 每组关键词在 JobsDB 搜索列表页翻页抓取（跨关键词自动按 job_id 去重）
3. 基础清洗：排除标题为空的岗位、排除用户指定的公司名单（`exclude_companies` 配置）
4. 全量抓取每个岗位的完整 JD（上限由 `max_total_results` 控制，默认 200）
5. 如果详情页抓取失败，用列表页摘要兜底（标记 `source: "snippet"`）

> **设计决策**：不做 LLM 预过滤——宁可多抓取，也不能基于不完整的标题+摘要误杀真正匹配的岗位。所有 JD 都完整保留，交给后续匹配评分做精确判断。

**输出文件**：

| 文件名 | 内容 | UI 可如何使用 |
|--------|------|--------------|
| `raw_jobs.json` | 全量完整 JD 数组（每个含 title/company/location/salary/description/url/jd_length/source/index） | 展示岗位列表 |
| `scan_listings.json` | 第一层扫描的全量列表（过滤前，含 snippet 摘要） | 调试用 |
| `rejected_jobs.json` | 被基础清洗排除的岗位 + 排除原因 | 调试用 |
| `filter_stats.json` | 各层过滤数量统计（scan_total/basic_rejected/filter_passed/jd_fetched/full_jd_count/snippet_count） | 展示搜索统计 |

---

#### 第二步：匹配评分

**前置条件**：必须先执行第一步，有 `raw_jobs.json` 文件。

**用户输入**：无需手动输入参数。

**系统行为（底层逻辑）**：

1. 从 `raw_jobs.json` 读取所有岗位，从 `me.yaml` 读取用户画像
2. 将所有岗位分批评分（每批 5 个），发给 LLM 从 5 个维度打分（0-100）：

| 维度 | 含义 | 权重可配置 |
|------|------|-----------|
| 技能匹配 | JD 要求的技术栈候选人的掌握程度 | ✅ |
| 经验匹配 | 工作年限和行业经验的对口程度 | ✅ |
| 职级匹配 | 岗位级别与候选人水平的匹配度 | ✅ |
| 行业匹配 | 所在行业与候选人背景的吻合度 | ✅ |
| 加分项 | 语言能力、认证、地点便利性等 | ✅ |

3. LLM 同时判断岗位方向（payment/solutions/web3/technical/default），基于完整 JD 内容（非标题）
4. 如果 LLM 返回的方向值无效，回退到标题关键词匹配
5. 系统根据方向自动选择对应的权重方案，用该权重重新计算总分

**5 种动态权重方案**：

| 方向 | 技能 | 经验 | 职级 | 行业 | 加分 | 适用于 |
|------|------|------|------|------|------|--------|
| default | 30% | 25% | 15% | 15% | 15% | 无法分类的通用岗位 |
| technical | 35% | 20% | 15% | 15% | 15% | 纯技术开发岗 |
| solutions | 25% | 20% | 15% | 20% | 20% | 方案/集成工程师 |
| web3 | 25% | 15% | 10% | 30% | 20% | Web3/区块链岗位 |
| payment | 25% | 20% | 10% | 25% | 20% | 支付/结算岗位 |

**及格线复评**（可配置开关）：对得分处于"及格线附近"（`min_match_score ± borderline_range`，默认 45±8=37~53 分）的岗位，用其方向对应的权重做第二次独立评分。两轮取平均，计算波动：

- 波动 ≤10 → 标注"已复评（可信）"
- 波动 >10 → 标注"评分波动大（需人工判断）"

**推荐等级划分**（基于总分）：

| 分数 | 等级 | 建议的颜色标记 |
|------|------|--------------|
| ≥ 80 | 强烈推荐 | 绿色 |
| ≥ 60 | 可考虑 | 黄色 |
| < 60 | 不推荐 | 红色 |

**输出文件**：

| 文件名 | 内容 | UI 可如何使用 |
|--------|------|--------------|
| `matched_jobs.json` | 达标岗位（≥min_match_score）的完整评分数据：五维分项、总分、方向、权重方案、置信度、skill_match（✅❌⚠️）、missing_skills、推荐理由 | 排名列表、详情卡片、筛选和排序 |
| `unmatched_jobs.json` | 未达标岗位的评分数据 | 可选展示 |
| `job_report.md` | Markdown 格式的排名报告：权重方案表 + 每个达标岗位的详情 | 对话中展示或单独页面渲染 |

**每个达标岗位包含的字段**：

- `title` / `company` / `url` — 岗位基本信息
- `total_score` — 加权总分
- `scores` — 五维分项（skill/experience/level/industry/bonus）
- `llm_direction` — LLM 判断的岗位方向
- `weight_profile` — 使用的权重方案名
- `confidence` — 评分置信度（high/verified/uncertain）
- `score_rounds` — 复评各轮分数（单轮时为单元素数组）
- `score_variance` — 复评分数波动
- `skill_match` — 技能匹配详情（如 `["Python ✅", "Go ❌", "AWS ✅"]`）
- `missing_skills` — 缺失的关键技能列表
- `reason` — LLM 的匹配分析说明
- `recommendation` — 推荐等级（强烈推荐/推荐/考虑/不推荐）

---

#### 第三步：简历生成

**前置条件**：需要先执行匹配评分（有 `matched_jobs.json`），取决于使用哪种简历生成模式。

**用户输入（5 种模式）**：

| 模式 | 用户怎么触发 | 需要的前置数据 | 适用场景 |
|------|-------------|---------------|---------|
| 方向聚合 | 对话「帮我找工作」后自动执行，或「按方向生成简历」 | matched_jobs.json（至少一个方向有 ≥2 个达标岗位） | 批量投递，按方向聚合 JD 共性生成 |
| 匹配岗位 | 对话「为第N个生成简历」 | matched_jobs.json + 指定第 N 个（1-based） | 对某个高分岗位单独定制 |
| JD 文本 | 粘贴一段 JD 文本 +「根据这个生成简历」 | 用户粘贴的 JD 文本 | 在其他平台看到的岗位 |
| 岗位方向 | 对话「生成 SE 方向的简历」 | 只有方向名称 | 没有具体 JD，只有投递方向 |
| 通用简历 | 对话「生成通用简历」 | 无（只需 me.yaml 个人画像） | 投递通用平台 |

**方向聚合模式**（最核心的模式）的底层逻辑：

1. 读取 `matched_jobs.json`，按 `llm_direction`（payment/solutions/web3/technical）分组
2. **跳过 `default` 方向的岗位**——这些岗位无法归类，JD 共性不足，聚合无意义
3. **每个方向至少需要 2 个达标岗位**，不足则跳过该方向
4. 每个方向取前 15 个岗位的 JD，发给 LLM 做聚合分析——提取共性需求并做三级技能分类：

| 分类 | 含义 | 在简历中的处理 |
|------|------|--------------|
| direct_match | 候选人具备的技能 | 简历重点展示，标熟练度 |
| quick_learnable | 候选人不直接具备但属于通用技术栈、有相近基础 | Skills 区列出但不标精通，Cover Letter 中表态 |
| hard_gap | 高门槛或完全不相关的技能 | 简历中不提及 |

5. 保存聚合分析结果到 `direction_analysis.json`
6. 对每个方向，生成一套完整的三语简历 + Cover Letter

**所有模式的共同生成流程**：

```
1. 英文简历生成（主版本）
2. 审查评分（A/B/C/D 评级）
   ├── A/B → 英文简历定稿
   └── C/D → 审查反馈注入 → 自动重写一次 → 定稿
3. 英文 Cover Letter 生成
4. 精确翻译为 繁體中文（hk）
5. 精确翻译为 简体中文（cn）
```

翻译规则：结构完全一致、技术术语保留英文、公司名称保留英文、数字和量化指标不变。

**审查维度**：6 秒可读性测试、关键词覆盖、业务/技术平衡、量化程度、弱点暴露风险、ATS 友好度。

**每次生成的文件（7 个）**：

| 文件 | 格式 | 用途 |
|------|------|------|
| `resume_{label}_{date}_en.pdf` | PDF | 英文简历（主版本，用于投递） |
| `resume_{label}_{date}_hk.pdf` | PDF | 繁體中文简历 |
| `resume_{label}_{date}_cn.pdf` | PDF | 简体中文简历 |
| `cover_letter_{label}_{date}_en.pdf` | PDF | 英文 Cover Letter |
| `cover_letter_{label}_{date}_hk.pdf` | PDF | 繁體中文 Cover Letter |
| `cover_letter_{label}_{date}_cn.pdf` | PDF | 简体中文 Cover Letter |
| `resume_review_{label}_{date}.json` | JSON | 审查报告 |

> `{label}`：安全的文件标签（取前 30 字符，特殊字符转 `_`）
> `{date}`：`YYYYMMDD` 格式

**方向聚合模式额外文件**：

| 文件 | 格式 | 内容 |
|------|------|------|
| `direction_analysis.json` | JSON | 每个方向的聚合分析结果：direct_match、quick_learnable、hard_gap 三级分类、典型岗位职责、常见加分项、简历策略建议 |

---

### 3.2 市场调研

独立于"找工作"流程。用户可以随时用任一岗位类别关键词发起市场调研。

**用户输入**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `job_category` | 字符串 | ✅ 是 | — | 岗位类别关键词，**大小写敏感**（用户输入原样传给搜索） |
| `location` | 字符串 | 否 | `"Hong Kong"` | 搜索地点 |
| `include_gap_analysis` | 布尔 | 否 | `true` | 是否包含个人差距分析 |
| `classification` | 字符串 | 否 | `""` | JobsDB 行业分类标签，**大小写敏感**。如 `"information-communication-technology"`、`"banking-financial-services"`。留空则搜索全行业 |
| `sort_by` | 字符串 | 否 | 从配置读取 | `"date"`（按发布时间，最新在前）或 `"relevance"`（按相关度） |

**系统行为（底层逻辑）**：

系统分四个阶段执行：

1. **数据采集**：在 JobsDB 搜索指定的岗位类别（翻 `max_pages` 页），全量抓取每个岗位的完整 JD（上限 `max_fetch_jd`，默认 100）。详情页抓取失败的岗位用列表页摘要兜底。

2. **LLM 市场分析**：将所有 JD 分批发给 LLM（每批 `batch_size` 条，默认 5），LLM 从以下维度提取和统计：

| 维度 | 内容 | 示例 |
|------|------|------|
| technical_skills | 技术技能排名（具体名称、分类、常用工具、说明、出现次数和占比、必须/优先/加分级别） | `"Ethers.js Web3 Library" 15次(60%)` |
| soft_skills | 软技能/业务能力（名称、说明、出现次数和占比） | `"跨团队沟通" 12次(48%)` |
| salary_overview | 薪资概况（按 Junior/Mid/Senior 级别分类，含范围和各级别岗位数） | Junior: HK$20-35K (8个岗位) |
| experience_distribution | 经验要求分布（各经验区间的岗位数和占比） | 3-5年: 15个(60%) |
| common_responsibilities | 最常见的岗位职责（完整句子描述） | `"设计和维护 RESTful API..."` |
| industry_distribution | 行业分布（各行业岗位数） | ICT: 18个, 金融: 5个 |
| key_trends | 关键趋势观察（具体趋势说明、重要性、对求职者的影响） | `"零知识证明需求上升..."` |
| language_requirements | 语言要求（英语/中文，按流利/良好/基础级别统计岗位数） | 英语流利: 20个(80%) |
| education_requirements | 学历要求分布 | 本科: 22个(88%) |
| company_profile | 公司画像（规模分布 + 知名雇主列表 Top 10） | 中小企业: 15个 |
| interview_hints | 面试线索（技术面/行为面/BQ 等类型统计） | 技术面: 18个(72%) |

3. **差距分析**（可选，`include_gap_analysis=true` 时执行）：LLM 对比市场技能需求和用户画像，输出：
   - **strengths**：候选人具备且市场需求高的优势技能（说明为什么是优势、在哪些项目中使用、比一般求职者强在哪里）
   - **gaps**：市场需求高但候选人缺失/薄弱的技能（含具体的可执行学习路径——每一步列明学什么、怎么学、做什么练习、预计多久）
   - **low_value_skills**：候选人掌握但市场需求低的技能（建议是继续深入还是转化为其他方向优势）
   - **strategic_advice**：综合策略建议（优先补什么、后补什么、为什么是这个顺序）

4. **报告撰写**：LLM 将上述结构化数据撰成专业 Markdown 报告 → 渲染为 PDF。若 LLM 报告生成失败，自动回退到 JSON dump 格式（确保分析数据不丢失）。

**输出文件（每次调研生成 5 个文件）**：

| 文件 | 格式 | 内容 |
|------|------|------|
| `market_{category}_{date}.md` | Markdown | LLM 撰写的完整市场分析报告（所有上述维度 + 差距分析） |
| `market_{category}_{date}.pdf` | PDF | 同上（专业排版，含表格样式） |
| `market_{category}_{date}.json` | JSON | 结构化分析数据（analysis + gap_analysis），供二次分析或前端可视化 |
| `market_{category}_{date}_scan.json` | JSON | 全量扫描列表（过滤前），供数据验证 |
| `market_{category}_{date}_jds.json` | JSON | 抓取的完整 JD 原文，供深入分析 |

> `{category}`：岗位类别（空格和 `/` 转 `_`，截断至 30 字符）
> `{date}`：`YYYYMMDD_HHMMSS` 格式

**批量市场调研**：用户可以一次性提交多个岗位类别（每个可带独立的 `classification`），系统依次执行上述四阶段流程，最后汇总所有结果。

---

### 3.3 辅助功能

#### 3.3.1 查看匹配结果

用户说「看看匹配结果」→ 系统返回最近一次匹配的前 8 名岗位摘要（含总分、五维分、复评状态、技能匹配详情）。如果有超过 8 个达标岗位，提示用户查看完整的 `job_report.md` 文件。

#### 3.3.2 查看用户档案/搜索配置

用户说「看看我的档案」或「看看搜索配置」→ 系统返回对应 YAML 配置文件的内容（以 JSON 格式化，对 LLM 更友好）。

#### 3.3.3 单岗位抓取

用户提供一个 JobsDB 岗位 URL → 系统抓取该岗位的完整 JD（标题、公司、地点、薪资、JD 文本长度、完整描述）。

#### 3.3.4 联网搜索

用户说「搜索 xxx」→ 系统通过 DuckDuckGo 搜索，返回格式化结果（标题+摘要+链接），默认 5 条。

#### 3.3.5 LLM 模型切换

用户可在 DeepSeek、Qwen（千问）、GLM（智谱）之间实时切换。切换立即生效，无需重启。每个 provider 有预设的 API 端点和默认模型：

| Provider | 当前默认模型 |
|----------|------------|
| deepseek | deepseek-chat |
| qwen | qwen3.6-plus |
| glm | glm-5.1 |

切换行为是全局的——当前会话中后续所有 LLM 调用都使用新模型。

#### 3.3.6 文件管理

系统每次执行任务都会生成一系列输出文件。文件按**运行（Run）**分组：

- **找工作流程**：每次搜索创建一个以时间戳命名的 run 目录（如 `run_20260604_143000/`），该次搜索及后续的匹配评分、简历生成的所有文件都存入该目录
- **市场调研**：所有输出存入 `output/market/` 共享目录

用户需要能够：
- 查看所有历史 run 列表（含时间、当前阶段、岗位数量、匹配数量）
- 浏览每个 run 下的所有文件（含子目录递归）
- 浏览市场调研文件
- 下载任意文件
- 区分当前活跃的 run 和已完成的 run

---

## 四、API 接口规范

> 以下接口是后端提供给前端的契约。前端必须通过以下接口与系统交互。每个接口的请求格式和响应格式是固定的。

### 4.1 POST /api/session — 创建会话

每个浏览器会话需要先创建 sid，后续所有请求携带 sid。

**Request**：`{}`（空 body）

**Response**：`{"sid": "a1b2c3d4"}`

`sid` 为 8 位十六进制字符串。

---

### 4.2 POST /api/chat — LLM Agent 对话

**Request**：
```json
{
  "sid": "a1b2c3d4",
  "message": "帮我找工作"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sid` | string | ✅ | 会话 ID |
| `message` | string | ✅ | 用户的自然语言输入 |

**Response**（立即返回）：`{"status": "started"}`

**SSE 事件流**（通过 `/stream/{sid}` 获取）：实时推送 `progress` / `status` / `tool_call` / `done` / `error` / `ping` 事件。

**并发控制**：同一时间只允许一个 Agent 执行。如果已有任务在运行，新请求返回 HTTP 429。

---

### 4.3 POST /api/pipeline — 快捷流水线

**Request**：
```json
{
  "sid": "a1b2c3d4",
  "action": "search_match",
  "sort_by": "date"
}
```

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `sid` | string | ✅ | — | 会话 ID |
| `action` | string | ✅ | — | 当前仅支持 `"search_match"` |
| `sort_by` | string | 否 | 从配置文件读取 | `"date"`（按发布时间）/ `"relevance"`（按相关度） |

**Response**（立即返回）：`{"status": "started"}`

**SSE 事件流**：同 `/api/chat`，但 `status` 事件会依次显示 "Starting job search..." → "Starting match analysis..." → "Generating direction-based resumes..."。

**并发控制**：同 `/api/chat`。

---

### 4.4 GET /stream/{sid} — SSE 事件流

浏览器通过 `EventSource` 连接此端点获取实时推送。

**Response**：`Content-Type: text/event-stream`，每条事件格式为 `data: {JSON}\n\n`。

**自动断连**：当 session 不再 busy 且事件队列为空时，流自动关闭。

---

### 4.5 GET /api/runs — 获取运行历史

**Response**：
```json
[
  {
    "id": "run_20260604_143000",
    "path": "run_20260604_143000",
    "time": "2026-06-04 14:30",
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

| 字段 | 类型 | 含义 |
|------|------|------|
| `id` | string | Run 目录名 |
| `time` | string | 创建时间（格式化为可读字符串） |
| `stage` | string | `"empty"` / `"searched"`（有岗位） / `"matched"`（有匹配结果） |
| `has_raw` | bool | 是否有搜索数据 |
| `has_matched` | bool | 是否有匹配结果 |
| `has_resumes` | bool | 是否有生成的简历 |
| `job_count` | int | 搜索到的岗位总数（0 如果无数据） |
| `match_count` | int | 达标岗位数量（0 如果无数据） |
| `is_current` | bool | 是否为当前活跃 run |

---

### 4.6 GET /api/runs/{run_id}/files — 查看 Run 文件

**Response**：
```json
[
  {
    "name": "raw_jobs.json",
    "path": "run_20260604_143000/raw_jobs.json",
    "size": 12345,
    "mtime": 1717500000.0
  }
]
```

递归遍历 run 目录下所有文件（含 `resumes/` 子目录），按修改时间倒序排列。

`run_id` 不以 `run_` 开头或目录不存在时返回 404。

---

### 4.7 GET /api/files — 浏览所有输出文件

递归遍历整个 `output/` 目录。返回格式同上。

---

### 4.8 GET /api/market/files — 浏览市场调研文件

列出 `output/market/` 下所有文件（不递归子目录）。返回格式同上。

---

### 4.9 GET /api/config/model — 获取 LLM 配置

**Response**：
```json
{
  "current_provider": "glm",
  "current_model": "glm-5.1",
  "presets": {
    "deepseek": "deepseek-chat",
    "qwen": "qwen3.6-plus",
    "glm": "glm-5.1"
  }
}
```

---

### 4.10 POST /api/config/model — 切换 LLM 模型

**Request**：
```json
{
  "provider": "qwen",
  "model": "qwen3.6-plus"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `provider` | string | ✅ | `"deepseek"` / `"qwen"` / `"glm"` |
| `model` | string | 否 | 不传则使用该 provider 的默认模型 |

**Response**（成功）：`{"provider": "qwen", "model": "qwen3.6-plus"}`
**Response**（失败）：`{"error": "环境变量 DASHSCOPE_API_KEY 未设置"}`（HTTP 400）

切换立即生效，同时持久化到配置文件。

---

### 4.11 GET /download/{path} — 文件下载

下载 `output/` 目录下的文件。`path` 参数为相对路径（如 `run_20260604_143000/resumes/resume_web3_20260604_en.pdf`）。

---

## 五、配置项说明

用户可通过配置文件调整系统行为（无需修改代码）。所有配置文件位于 `profiles/` 目录。

### 5.1 profiles/me.yaml — 用户画像

| 配置项 | 类型 | 说明 |
|--------|------|------|
| 基本信息 | — | 姓名、联系方式、所在地 |
| 战略定位 | — | 核心画像描述、方向优先级、关键约束（英语水平、算法能力、经验年限） |
| 求职意向 | — | 目标岗位列表（优先级排序）、目标行业、薪资期望、到岗时间 |
| 专业技能 | 分组列表 | 数据库/API/编程语言/框架/区块链/DevOps/AI 工具/语言能力等 |
| 工作经历 | 数组 | 公司/职位/时间/描述/技术栈/亮点/核心业务模块详情 |
| 教育背景/证书 | — | 学历、证书列表 |

此文件的准确性直接影响匹配评分和简历生成的质量。

### 5.2 profiles/search_config.yaml — 核心配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `llm.provider` | string | `"glm"` | LLM 提供商 |
| `llm.model` | string | `"glm-5.1"` | 模型名称 |
| `sort_mode` | string | `"date"` | 全局排序方式 |
| `search_queries` | 数组 | — | 搜索关键词组（每项含 keywords/location/classification/direction/sort_by） |
| `filters.exclude_companies` | 字符串数组 | `[]` | 排除的公司名（大小写不敏感） |
| `max_pages_per_query` | int | `3` | 每组关键词翻几页 |
| `max_total_results` | int | `200` | 最终抓取 JD 上限 |
| `matching.min_match_score` | int | `45` | 最低达标分数 |
| `matching.top_n` | int | `999` | 保留前 N 名 |
| `matching.borderline_rescore` | bool | `true` | 及格线复评开关 |
| `matching.borderline_range` | int | `8` | 复评区间（±8 分） |
| `matching.weight_profiles` | 对象 | 5 种方案 | 见 §3.1 第二步权重表 |
| `matching.weight_rules` | 对象 | 4 类关键词 | 标题关键词 → 权重方案映射 |
| `market_analysis.max_pages` | int | `4` | 市场调研翻页数 |
| `market_analysis.max_fetch_jd` | int | `100` | 最多抓取 JD 数 |
| `market_analysis.batch_size` | int | `5` | LLM 每批分析条数 |
| `market_analysis.jd_max_chars` | int | `6000` | 单条 JD 截断长度 |

### 5.3 profiles/prompts.yaml — LLM 提示词

所有 LLM 提示词可通过此文件定制（共 17 个模板）。文件不存在或某 key 缺失时，系统回退到内置默认值。详细列表见 `CONFIG_GUIDE.md`。

### 5.4 profiles/resume_template.yaml — 简历模板

控制简历输出格式：章节顺序（summary/skills/work_experience/projects/education/certifications）、页数限制（默认 2 页 A4）、是否自动按 JD 重排技能顺序和调整 Summary。

### 5.5 profiles/resume_guide.yaml — 简历撰写规则

ATS 友好规则、各段落内容规范、弱点处理策略（如不写精确工作年限、不夸大语言能力）、香港市场特殊要求。通过模板注入到简历生成提示词中。

---

## 六、完整输出文件清单

### 6.1 找工作流程 — 每个 run 目录

```
output/run_{YYYYmmdd_HHMMSS}/
│
├── scan_listings.json        # 搜索阶段：第一层扫描的全量列表（过滤前）
│                             #   字段：title, company, salary, snippet, url, job_id
│
├── rejected_jobs.json        # 搜索阶段：被基础清洗排除的岗位
│                             #   字段：title, company, url, snippet, reject_reasons, reject_stage
│
├── filter_stats.json         # 搜索阶段：过滤统计数字
│                             #   字段：scan_total, basic_rejected, filter_passed,
│                             #         jd_fetched, full_jd_count, snippet_count
│
├── raw_jobs.json             # 搜索阶段：全量完整 JD（清洗后）
│                             #   字段：title, company, location, salary, description,
│                             #         url, jd_length, posted_date, classification, source, index
│
├── matched_jobs.json         # 匹配阶段：达标岗位的完整评分
│                             #   字段见 §3.1 第二步
│
├── unmatched_jobs.json       # 匹配阶段：未达标岗位（低于 min_match_score）
│
├── job_report.md             # 匹配阶段：Markdown 排名报告
│
├── direction_analysis.json   # 简历阶段：各方向 JD 聚合分析（仅方向聚合模式生成）
│                             #   结构：{"payment": {...}, "web3": {...}, ...}
│                             #   每个方向含：direct_match / quick_learnable / hard_gap /
│                             #             typical_responsibilities / common_bonus / resume_strategy
│
└── resumes/                  # 简历阶段：生成的全部文件
    ├── resume_{label}_{date}_en.pdf           # 英文简历（主版本）
    ├── resume_{label}_{date}_hk.pdf           # 繁體中文简历
    ├── resume_{label}_{date}_cn.pdf           # 简体中文简历
    ├── cover_letter_{label}_{date}_en.pdf     # 英文 Cover Letter
    ├── cover_letter_{label}_{date}_hk.pdf     # 繁體中文 Cover Letter
    ├── cover_letter_{label}_{date}_cn.pdf     # 简体中文 Cover Letter
    └── resume_review_{label}_{date}.json      # 审查报告
```

### 6.2 市场调研流程

```
output/market/
│
├── market_{category}_{date}.md         # LLM 撰写的专业分析报告（Markdown）
├── market_{category}_{date}.pdf        # 分析报告（PDF）
├── market_{category}_{date}.json       # 结构化分析数据（含 analysis + gap_analysis）
├── market_{category}_{date}_scan.json  # 全量扫描列表（过滤前）
└── market_{category}_{date}_jds.json   # 抓取的完整 JD 原文
```

---

## 七、关键业务规则

### 7.1 大小写敏感规则

| 场景 | 规则 |
|------|------|
| 市场调研 `job_category` 参数 | **保留用户原始输入**。用户说「Web3」→ 传 `"Web3"`（不变小写） |
| 市场调研 `classification` 参数 | **保留用户原始输入**。`"science-technology"` 不变更大小写 |
| 岗位分类（标题关键词匹配） | **大小写不敏感**（title.lower() 比较） |
| 公司排除 | **大小写不敏感** |

### 7.2 错误处理与降级

| 场景 | 系统行为 |
|------|---------|
| LLM API 限流（429）/超时/5xx | 自动指数退避重试（1s→2s→上限 30s），最多 2 次 |
| LLM 认证错误（401/403） | 直接报错，不浪费重试（可能是 Key 过期） |
| 详情页抓取失败 | 用列表页摘要兜底（标记 `source: "snippet"`） |
| 匹配评分某批次失败 | 跳过该批次，继续处理其余岗位 |
| 简历审查失败 | 跳过审查，使用原始英文简历 |
| 简历审查 C/D → 重写失败 | 使用原始英文简历 |
| 简历翻译某语言失败 | 跳过该语言，继续其他语言 |
| 市场分析某批次失败 | 跳过该批次，继续其他批次 |
| 市场报告撰写失败 | 回退到 JSON dump（数据不丢） |
| 所有重试耗尽 | 抛出错误，由上层捕获并展示给用户 |

### 7.3 方向判断逻辑

岗位方向（决定权重方案和简历聚合分组）的判断流程：

1. LLM 基于完整 JD 内容返回 `direction` 字段
2. 如果值有效（在 {payment, solutions, web3, technical, default} 中）→ 采用为 `llm_direction`
3. 如果值无效或未返回 → **回退到标题关键词匹配**，按顺序检查：
   ```
   payment → solutions → web3 → technical → default
   ```
   匹配到第一个包含该分类关键词的即停止（更具体的类别在前，防止误匹配）

### 7.4 方向聚合的过滤规则

- `default` 方向的岗位**不参与聚合**（无法归类，JD 共性不足）
- 每个方向**至少需要 2 个达标岗位**，不足则跳过该方向
- 每个方向最多取前 15 个岗位的 JD 做聚合分析
- LLM 提取的 JD 截断至 2000 字符（减少 token 消耗）

### 7.5 排序控制

搜索排序由三重优先级决定（从高到低）：

1. **调用时传入的 `sort_by` 参数**（Web UI 排序切换或对话中的指令）
2. **全局 `sort_mode` 配置**（search_config.yaml）
3. **默认值** `"date"`（按发布时间，最新在前）

`"date"` → JobsDB 搜索参数 `?sortmode=ListedDate`
`"relevance"` → 不传 sortmode（使用 JobsDB 默认相关度排序）

---

## 八、技术背景（供产品团队了解约束）

### 8.1 为什么搜索慢？

全量抓取每个岗位的 JD 需要 150~350 秒（100 个岗位）。这是设计决策——宁可慢也要确保匹配评分基于完整信息，而非只看标题和两行摘要。

### 8.2 为什么同一时间只能一个任务？

系统使用浏览器自动化抓取网页，Playwright 不支持并发操作。这是硬件约束，不是架构设计的限制。

### 8.3 为什么会失败？

JobsDB 网站结构会不定期更新，爬虫的网页解析可能失效。此时搜索会返回错误提示（而非静默返回空结果），需要人工介入修复爬虫选择器。

### 8.4 LLM 为什么有时返回不一致？

LLM 本质上是概率模型。匹配评分引入了及格线复评机制来减少偶然性——对边界分数做两次独立评分取平均。简历审查也有自动重写机制来保证质量。
