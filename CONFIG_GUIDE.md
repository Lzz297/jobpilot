# 配置使用手册

本项目有两套配置体系，可独立使用也可组合使用：

- **旧体系（`profiles/`）**：单用户配置文件，适合个人日常使用。支持 Web UI 直接编辑。
- **新体系（`instances/`）**：三层组装架构（User × Strategy × Campaign），适合多用户、多策略的批量实验和评估场景。通过 `python agent.py --campaign <name>` 启动。

无论哪种方式，均**无需改动任何代码**。

---

## 目录

| 配置文件 | 控制什么 | 修改方式 | 改动频率 |
|---------|---------|---------|---------|
| [`.env`](#0-env--环境变量) | API 密钥 | 仅文件 | 极低（换供应商时改） |
| [`profiles/me.yaml`](#1-meyaml--个人档案) | 你是谁、会什么、想找什么 | 文件 / Web UI 设置面板 | 低（换方向时改） |
| [`profiles/search_config.yaml`](#2-search_configyaml--搜索与匹配策略) | 搜什么词、怎么过滤、怎么评分 | 文件 / Web UI 设置面板 | 高（每次调方向都改） |
| [`profiles/resume_guide.yaml`](#3-resume_guideyaml--简历撰写规范) | 简历内容怎么写 | 仅文件 | 低（基本不用动） |
| [`profiles/resume_template.yaml`](#4-resume_templateyaml--简历模板结构) | 简历段落顺序和格式 | 仅文件 | 低（微调排版时改） |
| [`profiles/prompts.yaml`](#5-promptsyaml--llm-提示词) | 教 LLM 怎么筛选、评分、分析、写简历 | 仅文件 | 中（优化判断逻辑时改） |
| [`instances/` 新配置架构](#6-instances--三层配置组装) | 多用户 × 多策略 × 多 Campaign 的灵活组合 | 仅文件 | 中（新增策略/用户时改） |

---

## 0. `.env` — 环境变量

**作用：** 存放 API 密钥，不同的 LLM 供应商需要不同的密钥。

```env
# DeepSeek
DEEPSEEK_API_KEY=sk-your-key-here

# 阿里云（Qwen）
DASHSCOPE_API_KEY=sk-your-key-here

# 智谱 AI（GLM）
GLM_API_KEY=sk-your-key-here
```

| 你想达到的效果 | 怎么改 |
|--------------|-------|
| 切换到其他 LLM 供应商 | 添加对应的 API Key，然后在 `search_config.yaml` 的 `llm` 段切换 `provider` |
| API 调用报错 "key not set" | 检查 `.env` 文件中对应的 Key 是否正确填写 |

**安全提醒：** 不要把 `.env` 文件提交到 git。

---

## 1. `me.yaml` — 个人档案

**作用：** 这是 Agent 认识你的唯一来源。搜索过滤、匹配评分、简历生成全部依赖它。

> **💡 修改方式：** 除了直接编辑文件外，也可在 Web UI 侧边栏点击「设置」进入编辑面板，或在侧边栏点击「me.yaml」按钮预览 YAML 原文。

### 结构一览

```yaml
# 基本信息
name / phone / email / linkedin / github / location

# 求职意向
job_intent:
  target_titles: [...]      # 目标岗位列表
  target_industries: [...]  # 目标行业列表
  location_preference: [...]
  salary_expectation: { min, max, currency, note }
  job_type / notice_period

# 专业技能
skills:
  programming_languages: [{ name, level, years }]
  frameworks / databases / tools / blockchain / business_skills
  languages: [{ name, level, note }]

# 工作经历
work_experience:
  - company / title / period / description / tech_stack / highlights

# 教育 / 项目 / 证书 / 自我评价
education / projects / certifications / summary
```

### 使用场景

| 你想达到的效果 | 怎么改 |
|--------------|-------|
| **转换求职方向**（如从后端开发转 Web3 产品） | 修改 `job_intent.target_titles` 和 `target_industries` |
| **匹配评分偏向特定技能** | 在 `skills` 中添加/突出相关技能，评分时 LLM 会据此判断技能匹配度 |
| **简历突出不同的工作亮点** | 修改 `work_experience.highlights` 和 `description`，简历生成会优先引用这些内容 |
| **投不同城市的岗位** | 修改 `location` 和 `job_intent.location_preference` |
| **薪资预期调整** | 修改 `salary_expectation`（目前未用于自动过滤，但 Agent 对话时会参考） |

### 注意事项

- `target_titles` 的顺序代表优先级，排在前面的是首选方向
- `summary` 会被直接用于简历的 Summary 段落参考，所以要写得像简历而非日记
- 工作经历中的 `highlights` 是简历 bullet points 的主要素材，**格式要求：动词开头 + 做了什么 + 量化结果**
- `skills.blockchain` 等特定领域字段是自定义的，LLM 会读取但不会硬性匹配字段名

---

## 2. `search_config.yaml` — 搜索与匹配策略

**作用：** 控制整条流水线——搜什么、过滤什么、怎么评分。**换方向时主要改这个文件。**

> **💡 修改方式：** 除了直接编辑文件外，也可在 Web UI 侧边栏进行快速操作——「设置」面板可编辑完整 YAML 内容，LLM 下拉菜单可一键切换模型，排序按钮可切换按时间/按相关度。

### 2.1 `llm` — LLM 供应商

```yaml
llm:
  provider: deepseek          # 可选: deepseek | qwen | glm
  model: deepseek-v4-pro      # 对应供应商的模型名
```

| 你想达到的效果 | 怎么改 |
|--------------|-------|
| 换模型供应商 | 改 `provider`，确保 `.env` 中有对应 Key |
| 用更便宜/更强的模型 | 改 `model` 为供应商支持的模型名 |
| **不编辑文件，一键切换** | Web UI 侧边栏 LLM 下拉菜单直接选择，切换**即时生效**并自动回写配置 |

### 2.2 `search_queries` — 搜索关键词

```yaml
search_queries:
  - keywords: "Web3"
    location: "Hong Kong"
  - keywords: "Solutions Engineer"
    location: "Hong Kong"
    classification: "science-technology"   # 可选：限定行业分类
```

**原理：** 每组生成一次 JobsDB 搜索请求，然后翻页抓取列表。
- 不填 `classification`：`hk.jobsdb.com/{keywords}-jobs`（搜索全部行业）
- 填 `classification`：`hk.jobsdb.com/{keywords}-jobs-in-{classification}`（限定行业）
- 可选填 `sort_by`：覆盖全局 `sort_mode`，`"date"` = 按发布时间，`"relevance"` = 按相关度

| 你想达到的效果 | 怎么改 |
|--------------|-------|
| 搜索范围更广 | 增加更多关键词组（如加上 "Crypto", "DeFi"） |
| 搜索更精准、减少噪音 | 用更具体的词，或者加 `classification` 限定行业 |
| 搜其他城市 | 修改 `location`（如 "Singapore"、"Remote"） |
| 某组搜索词用不同排序 | 在该组加 `sort_by: "relevance"` |

**建议：** 宽泛词（Web3）和精确词（Web3 Product）搭配使用，5-8 组为宜。对于含义很广的岗位名称（如 Solutions Engineer），建议加 `classification` 缩小范围。`classification` 的值直接对应 JobsDB URL 中 `-in-` 后面的部分，自行在 JobsDB 上确认即可。

---

### 2.3 `filters` — 过滤条件

```yaml
filters:
  exclude_companies: [] # 排除特定公司
```

基础清洗阶段会排除空标题和 `exclude_companies` 中列出的公司。精确过滤交给 match_jobs 的五维评分完成。

| 你想达到的效果 | 怎么改 |
|--------------|-------|
| 排除特定公司 | 在 `exclude_companies` 加公司名 |
| 提高匹配精度 | 调整 `matching.min_match_score` |

---

### 2.4 数量控制

```yaml
max_pages_per_query: 3     # 每组搜索词翻几页（每页约30条）
max_total_results: 200     # 进入 JD 抓取阶段的上限
```

| 你想达到的效果 | 怎么改 |
|--------------|-------|
| 看到更多候选岗位 | 调大 `max_total_results`（如 50），但会更慢 |
| 搜索更快 | 减小 `max_pages_per_query`（如 2）和 `max_total_results`（如 15） |

**经验值：**
- 快速扫一下：`max_pages=2, max_total=50` → 约 2 分钟
- 正常搜索：`max_pages=3, max_total=200` → 约 5-10 分钟
- 深度搜索：`max_pages=6, max_total=300` → 约 15 分钟

---

### 2.5 `matching` — 匹配评分

这是最核心的部分，控制 LLM 如何给每个岗位打分。

#### 基础设置

```yaml
matching:
  min_match_score: 45    # 及格线
  top_n: 999             # 达标岗位全部保留（不限数量）
```

#### 及格线复评

```yaml
  borderline_rescore: true   # 开启二次评分
  borderline_range: 8        # ±8 分内做复评
```

#### `weight_profiles` — 权重模板

```yaml
  weight_profiles:
    web3:
      skill: 25         # 技能匹配
      experience: 15    # 经验年限
      level: 10         # 职级匹配
      industry: 30      # 行业对口
      bonus: 20         # 加分项
```

**5 个维度必须加起来 = 100。**

| 维度 | LLM 评分依据 | 什么时候给高权重 |
|-----|-------------|---------------|
| `skill` | JD 要求的语言/框架/工具，你会多少 | 技术岗、JD 技能要求明确时 |
| `experience` | 工作年限是否达标 | 要求资深经验的岗位 |
| `level` | 岗位级别 vs 你的级别 | 职级明确的大公司岗位 |
| `industry` | 行业是否对口 | 行业壁垒高的岗位（如 Web3、金融） |
| `bonus` | 双语、AI 工具、沟通能力等软技能 | 复合型/非纯技术岗位 |

#### `weight_rules` — 岗位分类（备用）

```yaml
  weight_rules:
    web3:
      - "web3"
      - "blockchain"
    technical:
      - "developer"
      - "engineer"
```

**原理：** 岗位方向主要由 LLM 评分时根据完整 JD 判断（`llm_direction` 字段），比标题关键词匹配更准确。`weight_rules` 仅在 LLM 未返回有效方向时作为备用分类方案。

---

### 2.6 `market_analysis` — 市场调研设置

```yaml
market_analysis:
  max_pages: 4            # 翻几页列表
  max_fetch_jd: 100       # 最多抓几条 JD
  batch_size: 5            # LLM 每批分析几条
  jd_max_chars: 6000       # 每条 JD 截断长度
```

**作用：** 仅在调用 `analyze_market` 工具时使用，与找工作流程独立。

---

### 2.7 `sort_mode` — 排序设置

```yaml
sort_mode: "date"      # "date" = 按发布时间排序（最新在前）
                       # "relevance" = 按相关度排序（JobsDB 默认）
```

**原理：** 控制 JobsDB 搜索结果的排序方式。`"date"` 对应 URL 参数 `?sortmode=ListedDate`，`"relevance"` 则不传 `sortmode` 参数（走 JobsDB 默认相关度排序）。

**单个搜索词覆盖：** 如果某个关键词组需要不同的排序方式，可以在 `search_queries` 条目中加 `sort_by` 字段：

```yaml
search_queries:
  - keywords: "Web3"
    location: "Hong Kong"
    sort_by: "relevance"   # 覆盖全局 sort_mode，按相关度搜索
```

**Web UI：** 侧边栏 "Find & Match Jobs" 区域有排序切换按钮（按发布时间 / 按相关度），点击即切换。**注意：此操作仅影响当次请求的 `sort_by` 参数，不会写入配置文件。** 要永久生效仍需修改 `sort_mode` 配置项。

---

## 3. `resume_guide.yaml` — 简历撰写规范

**作用：** 告诉 LLM 怎么写简历内容。生成简历时会被注入到 LLM 的 system prompt 中。

### 结构一览

```yaml
general:              # 总体规则（页数、是否放照片、目标市场）
ats_rules:            # ATS（简历解析系统）友好规则
content_rules:        # 每个段落的内容写法
  summary:            # Summary 段落：最多几句、侧重点
  work_experience:    # 工作经历：每角色几个 bullet、好/坏示例
  skills:             # 技能：分组方式、每组上限
  education:          # 教育
  certifications:     # 证书
weakness_handling:    # 弱点处理策略（如何避免暴露年限不足、英语短板等）
hk_specific:          # 香港市场特殊要求
cover_letter:         # Cover Letter 规则
```

| 你想达到的效果 | 怎么改 |
|--------------|-------|
| 简历从 2 页改为 1 页 | `general.max_pages: 1`，同时减少 `work_experience.max_bullet_points_per_role` |
| 改变 bullet point 风格 | 修改 `content_rules.work_experience.style` 和 `good_examples` |
| 投非香港市场 | 修改 `general.target_market`、`hk_specific` 中的规则 |

---

## 4. `resume_template.yaml` — 简历模板结构

**作用：** 控制简历的段落顺序和输出格式。

```yaml
format: "markdown"
output_style: "professional"

sections_order:       # 段落排列顺序（从上到下）
  - "summary"
  - "skills"
  - "work_experience"
  - "projects"
  - "education"
  - "certifications"

customization:
  auto_reorder_skills: true    # 自动按 JD 相关性重排技能
  auto_adjust_summary: true    # 自动根据目标岗位调整 Summary
  max_pages: 2
```

| 你想达到的效果 | 怎么改 |
|--------------|-------|
| Skills 放在 Work Experience 后面 | 交换 `sections_order` 中的顺序 |
| 不展示 Projects 段落 | 从 `sections_order` 中删除 "projects" |
| 不要自动重排技能 | `auto_reorder_skills: false` |

---

## 5. `prompts.yaml` — LLM 提示词

**作用：** 这是本项目最关键的可调文件之一。它包含了**所有发送给 LLM 的指令**，决定了 LLM 如何筛选岗位、评分、分析市场、撰写简历。

### 结构总览

| 段落 | 用途 | 影响什么功能 |
|------|------|------------|
| `agent.system_prompt` | Agent 的身份和行为规则 | 对话交互 |
| `job_match.scoring_system_prompt` | 教 LLM 怎么从 5 个维度打分 | 匹配评分阶段 |
| `market_analysis.analysis_system_prompt` | 教 LLM 怎么从 JD 中提取市场数据 | 市场分析 |
| `market_analysis.report_prompt` | 教 LLM 怎么撰写市场分析报告 | 市场分析 → 报告撰写 |
| `market_analysis.gap_analysis_prompt` | 教 LLM 怎么做候选人差距分析 | 市场分析 → 差距分析 |
| `resume.base_rules` | 简历撰写的通用基础规则 | 所有简历生成模式 |
| `resume.prompt_for_job` | 基于匹配岗位生成简历的指令 | 简历模式 2 |
| `resume.prompt_for_jd_text` | 基于粘贴 JD 生成简历的指令 | 简历模式 3 |
| `resume.prompt_for_role` | 基于岗位方向生成简历的指令 | 简历模式 4 |
| `resume.prompt_for_general` | 生成通用简历的指令 | 简历模式 5 |
| `resume.cover_letter_prompt` | Cover Letter 撰写指令 | 求职信生成 |
| `resume.resume_review_prompt` | 英文简历自检（审查定稿） | 简历审查 |
| `resume.aggregate_system_prompt` | 方向聚合分析 + 三级技能分类 | 简历模式 1（方向聚合） |
| `resume.prompt_for_direction_data` | 基于聚合数据生成方向简历 | 简历模式 1 |
| `resume.cl_for_direction_data` | 方向通用 Cover Letter | 简历模式 1 |
| `resume.translate_resume_prompt` | 简历翻译（英→繁中/简中） | 所有模式翻译阶段 |
| `resume.translate_cl_prompt` | Cover Letter 翻译 | 所有模式翻译阶段 |

### 占位符说明

提示词中用 `<name>` 格式的占位符表示运行时自动替换的变量。

| 占位符 | 出现在 | 替换为什么 |
|--------|-------|-----------|
| `<profile_summary>` | job_match, aggregate_system_prompt | 候选人完整档案的 YAML 文本 |
| `<weights_text>` | job_match | 5 维度权重说明（自动从 search_config 生成） |
| `<score_formula>` | job_match | 总分计算公式（自动生成） |
| `<job_category>` | market_analysis | 用户指定的岗位类别（如 "Web3"） |
| `<location>` | market_analysis.report | 搜索地点（如 "Hong Kong"） |
| `<sample_size>` | market_analysis.report | 分析的 JD 样本数量 |
| `<analysis_json>` | market_analysis.report | 市场分析结构化数据（JSON） |
| `<gap_analysis_json>` | market_analysis.report | 差距分析结构化数据（JSON） |
| `<technical_skills>` | market_analysis.gap | 市场技术技能需求列表（JSON） |
| `<profile>` | market_analysis.gap | 候选人技能画像（JSON） |
| `<guide>` | resume.base_rules | 简历撰写指南（来自 resume_guide.yaml） |
| `<template>` | resume.prompt_for_* | 简历模板配置（来自 resume_template.yaml） |
| `<base_rules>` | resume.prompt_for_* | 渲染后的基础规则文本 |
| `<role>` | resume.prompt_for_role | 岗位方向名称（如 "Solutions Engineer"） |
| `<direction>` | prompt_for_direction_data, cl_for_direction_data | 方向名称（如 "payment"） |
| `<target_lang>` | translate_resume_prompt, translate_cl_prompt | 目标语言（如 "繁體中文（香港用語）"） |

### 哪些可以改、哪些不能改

文件中用注释标注了：

- **✏️ 可以自由修改的部分：** 角色设定、判断规则、评分标准、写作风格
- **⚠️ 不要修改的部分：** `<占位符>` 名称、JSON 输出格式中的字段名

**经验法则：** 中文自然语言描述的"规则""要求""注意"部分都可以改；花括号 `{}` 包裹的 JSON 结构不要改。

### 常见编辑场景

#### 场景 A：让评分更关注行业匹配

找到 `job_match.scoring_system_prompt` 中的「注意」部分，添加额外评分指导：

```yaml
注意：
- total_score = <score_formula>（四舍五入取整）
- 如果岗位属于 Web3/区块链行业，industry 维度应该给予额外加分
- 候选人有粤语母语优势，如果 JD 提到需要粤语/广东话，bonus 应给高分
```

#### 场景 B：调整市场分析的侧重点

找到 `market_analysis.analysis_system_prompt`，修改分析要求：

```yaml
# 在「注意」部分添加：
- 特别关注 AI/LLM 相关的技能需求，即使出现频次低也要列出
- 对于远程工作岗位，单独标注
```

#### 场景 C：改变简历写作风格

找到 `resume.base_rules` 或具体模式的 prompt，修改风格要求：

```yaml
# 例如在 base_rules 中修改：
# 原来：9. Summary 最多3句话
# 改为：9. Summary 最多2句话，第一句必须包含最核心的技术关键词
```

### 多语言注意事项

多语言简历采用「英文先行 + 翻译」机制：英文为主版本（审查定稿后），繁中/简中由 `resume.translate_resume_prompt` 和 `resume.translate_cl_prompt` 精确翻译生成。修改 resume prompt 只需关注英文版本即可。翻译规则也可在 `prompts.yaml` 中调整。

---

## 常见操作速查

### 场景 1：换一个求职方向（如从后端开发转 Web3 产品）

1. **`me.yaml`** → 修改 `job_intent.target_titles` 和 `target_industries`
2. **`search_config.yaml`** → 修改 `search_queries` 关键词、调整 `filters`、修改 `weight_profiles` 权重
3. （可选）`me.yaml` → 调整 `summary` 和 `highlights` 以突出新方向相关经验
4. （可选）`prompts.yaml` → 在 `job_match.scoring_system_prompt` 中调整评分规则

### 场景 2：搜索结果太少

1. `search_config.yaml` → 增加更多 `search_queries` 关键词组
2. `search_config.yaml` → 调大 `max_pages_per_query`
3. `search_config.yaml` → 降低 `matching.min_match_score`

### 场景 3：搜索结果噪音太多

1. `search_config.yaml` → 用更精确的关键词（如 "Web3 Product Manager" 而非 "Web3"）
2. `search_config.yaml` → 提高 `matching.min_match_score`
3. `search_config.yaml` → 调整 `weight_profiles` 增加相关维度的权重

### 场景 4：简历不够突出

1. `me.yaml` → 优化 `work_experience.highlights`（用数据量化成果）
2. `me.yaml` → 完善 `summary`（突出核心竞争力）
3. `resume_guide.yaml` → 调整 `content_rules.work_experience.good_examples` 给 LLM 更好的示范
4. （可选）`prompts.yaml` → 在 `resume.base_rules` 中添加更具体的写作要求

### 场景 5：投不同城市

1. `me.yaml` → 修改 `location` 和 `job_intent.location_preference`
2. `search_config.yaml` → 修改每组 `search_queries` 的 `location`

### 场景 6：切换搜索结果排序

1. **全局切换** → `search_config.yaml` 修改 `sort_mode` 为 `"relevance"`（按相关度）或 `"date"`（按发布时间）
2. **单个搜索词** → 在对应的 `search_queries` 条目中加 `sort_by: "relevance"` 覆盖全局设置
3. **临时切换** → Web UI 侧边栏排序切换按钮直接选择

---

## 6. `instances/` — 三层配置组装（新架构）

**作用：** 将配置按变化轴拆分为 User（谁）、Strategy（怎么评）、Campaign（搜什么）三层，支持灵活组合。通过 `config_assembler.py` 在运行时组装成完整配置。

### 6.1 目录结构

```text
instances/
├── campaigns/       # Campaign 定义：绑定 user + strategy + search_queries
│   └── web3_hunt.yaml
├── strategies/      # 策略文件：权重方案 + 关键词规则
│   ├── default.yaml
│   ├── payment.yaml
│   ├── solutions.yaml
│   ├── technical.yaml
│   └── web3.yaml
├── users/           # 用户画像（替代 profiles/me.yaml 的用户维度）
│   └── li_ming.yaml
└── eval/            # 评估数据集 + 标注规范
    ├── all_cases.json
    ├── dev_set.json
    ├── holdout.json
    ├── checker_test_cases.json
    ├── ANNOTATION_GUIDE.md
    └── ANNOTATION_TODO.md
```

### 6.2 三层组装流程

```
campaigns/web3_hunt.yaml
  │
  ├── user: li_ming     → 加载 instances/users/li_ming.yaml
  ├── strategy: web3    → 加载 instances/strategies/web3.yaml（含 weight_profile + weight_rules_keywords）
  │
  └── 组装逻辑（config_assembler.py）：
       1. 加载 profiles/search_config.yaml 获取通用配置（llm / filters / 数量控制）
       2. 加载 profiles/prompts.yaml 获取 prompt 模板
       3. 加载 profiles/resume_template.yaml + resume_guide.yaml
       4. 从 strategy 构建 matching 段（weight_profiles + weight_rules）
       5. 合并 campaign.overrides（如 max_total_results / min_match_score 覆盖）
       → 输出完整配置字典
```

### 6.3 Campaign 文件格式

```yaml
# instances/campaigns/web3_hunt.yaml
user: "li_ming"               # 必填：用户 ID
strategy: "web3"              # 必填：策略 ID
search_queries:               # 必填：搜索关键词组
  - keywords: "Web3"
    location: "Hong Kong"
  - keywords: "Blockchain Developer"
    location: "Hong Kong"
sort_mode: "date"             # 可选：覆盖全局 sort_mode
overrides:                    # 可选：覆盖通用配置
  max_total_results: 200
  min_match_score: 45
```

### 6.4 使用方式

```bash
# 终端模式 — 加载 campaign
python agent.py --campaign web3_hunt

# Web UI 模式 — 目前仅支持 profiles/ 配置
python web_app.py
```

### 6.5 新旧体系对比

| 维度 | 旧体系（profiles/） | 新体系（instances/） |
|------|-------------------|---------------------|
| 用户画像 | `profiles/me.yaml`（单用户） | `instances/users/*.yaml`（多用户） |
| 权重方案 | `search_config.yaml` 内嵌 5 种 | `instances/strategies/*.yaml`（独立文件） |
| 搜索词 | `search_config.yaml` 内嵌注释切换 | `instances/campaigns/*.yaml`（显式声明） |
| 配置覆盖 | 直接修改 YAML | `overrides` 字段 + 深度合并 |
| Web UI 支持 | ✅ 支持 | ❌ 不支持（仅 CLI） |
| 适用场景 | 个人日常使用 | 批量实验、评估、多用户 |

---

## 配置文件之间的关系

### 旧体系（profiles/）

```
.env (API 密钥)
  └──→ config.py 初始化 LLM client

me.yaml (你是谁)
  │
  ├──→ job_match.py    读取完整档案 → 作为 LLM 评分的参考基准
  ├──→ resume_gen.py   读取全部字段 → 作为简历内容的唯一素材来源
  └──→ market_analysis.py  读取技能 → 用于差距分析对比

search_config.yaml (搜什么、怎么筛、怎么评分)
  │
  ├──→ job_search.py   读取 search_queries + filters + 数量控制
  ├──→ job_match.py    读取 matching（权重、及格线、复评）
  └──→ market_analysis.py  读取 market_analysis 段

resume_guide.yaml (简历怎么写)
  └──→ resume_gen.py   注入 LLM system prompt，指导内容写法

resume_template.yaml (简历什么结构)
  └──→ resume_gen.py   注入 LLM system prompt，控制段落顺序和格式

prompts.yaml (教 LLM 怎么判断)
  │
  ├──→ agent.py / web_app.py   Agent 系统身份
  ├──→ job_match.py            匹配评分指导
  ├──→ market_analysis.py      市场分析 + 差距分析
  └──→ resume_gen.py           简历撰写 + Cover Letter
```

### 新体系（instances/）— 三层组装

```
instances/users/{user}.yaml         # 用户画像
        │
instances/strategies/{strategy}.yaml # 权重方案 + 关键词规则
        │
instances/campaigns/{name}.yaml     # 搜索词 + overrides
        │
        ├──→ config_assembler.py  合并组装
        │         │
        │         ├── base: profiles/search_config.yaml（llm / filters / 数量）
        │         ├── + profiles/prompts.yaml
        │         ├── + profiles/resume_template.yaml + resume_guide.yaml
        │         └── → 输出完整配置字典
        │
        └──→ job_search / job_match / resume_gen 等模块接收 config 参数
```
