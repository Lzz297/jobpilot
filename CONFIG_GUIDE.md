# 配置使用手册

本项目有两套配置体系，可独立使用也可组合使用：

- **系统基础设施（`profiles/`）**：LLM 供应商、过滤条件、市场调研参数、画像选择。不随求职方向变化。支持 Web UI 直接编辑。
- **业务配置（`instances/`）**：三层组装架构（User × Strategy × Campaign）— 搜索词、匹配权重、数量控制。换方向时主要改这里。通过 `python agent.py --campaign <name>` 启动。

无论哪种方式，均**无需改动任何代码**。

---

## 目录

| 配置文件 | 控制什么 | 修改方式 | 改动频率 |
|---------|---------|---------|---------|
| [`.env`](#0-env--环境变量) | API 密钥 | 仅文件 | 极低（换供应商时改） |
| [`instances/users/{user}.yaml`](#1-用户画像--个人档案) | 你是谁、会什么、想找什么 | 文件 / Web UI 设置面板 | 低（换方向时改） |
| [`profiles/search_config.yaml`](#2-search_configyaml--系统基础设施) | LLM 供应商、过滤、市场参数、画像选择 | 文件 / Web UI 设置面板 | 低 |
| [`instances/campaigns/` + `strategies/`](#6-instances--三层配置组装) | 搜索词、匹配权重、翻页数、JD 上限 | 仅文件 | 高（每次调方向都改） |
| [`profiles/resume_guide.yaml`](#3-resume_guideyaml--简历撰写规范) | 简历内容怎么写 | 仅文件 | 低（基本不用动） |
| [`profiles/resume_template.yaml`](#4-resume_templateyaml--简历模板结构) | 简历段落顺序和格式 | 仅文件 | 低（微调排版时改） |
| [`profiles/prompts.yaml`](#5-promptsyaml--llm-提示词) | 教 LLM 怎么筛选、评分、分析、写简历 | 仅文件 | 中（优化判断逻辑时改） |

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

## 1. 用户画像 — 个人档案

**作用：** 这是 Agent 认识你的唯一来源。搜索过滤、匹配评分、简历生成全部依赖它。

**文件位置：** `instances/users/{user}.yaml`（由 `search_config.yaml` 的 `user` 字段指定，如 `user: "li_ming"` → 加载 `instances/users/li_ming.yaml`）。

> **💡 修改方式：** 除了直接编辑文件外，也可在 Web UI 侧边栏点击「设置」进入编辑面板（实际读写 `instances/users/` 目录），或通过画像下拉框切换不同用户。

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

## 2. `search_config.yaml` — 系统基础设施

**作用：** 存放不随求职方向变化的系统级配置——LLM 供应商、公司过滤、市场调研参数、当前画像选择。**换方向时主要改 `instances/campaigns/` 和 `instances/strategies/`，而非此文件。**

> **💡 修改方式：** 除了直接编辑文件外，也可在 Web UI 侧边栏进行快速操作——「设置」面板可编辑完整 YAML 内容，LLM 下拉菜单可一键切换模型，排序按钮可切换按时间/按相关度。

当前文件完整内容：

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

### 2.2 `user` — 当前用户画像

```yaml
user: li_ming
```

指定当前使用的用户画像文件名（不含 `.yaml` 后缀）。`load_profile()` 和 Web UI 的 `/api/config/yaml/me` 均通过此字段定位 `instances/users/{user}.yaml`。Web UI 侧边栏画像下拉框可切换，切换即时生效。

### 2.3 `filters` — 过滤条件

```yaml
filters:
  exclude_companies: [] # 排除特定公司
```

基础清洗阶段会排除空标题和 `exclude_companies` 中列出的公司。精确过滤交给 match_jobs 的五维评分完成。

| 你想达到的效果 | 怎么改 |
|--------------|-------|
| 排除特定公司 | 在 `exclude_companies` 加公司名 |

### 2.4 `market_analysis` — 市场调研设置

```yaml
market_analysis:
  max_pages: 4            # 翻几页列表（代码级 fallback: 3）
  max_fetch_jd: 100       # 最多抓几条 JD（代码级 fallback: 40）
  batch_size: 5            # LLM 每批分析几条（代码级 fallback: 10）
  jd_max_chars: 6000       # 每条 JD 截断长度（代码级 fallback: 2000）
```

**作用：** 仅在调用 `analyze_market` 工具时使用，与找工作流程独立。

### 2.5 `sort_mode` — 排序设置

```yaml
sort_mode: "date"      # "date" = 按发布时间排序（最新在前）
                       # "relevance" = 按相关度排序（JobsDB 默认）
```

**原理：** 控制 JobsDB 搜索结果的排序方式。Web UI 侧边栏排序切换按钮可临时覆盖，不写入配置文件。

---

### ⚠️ 已迁移的配置项

以下字段原本在 `search_config.yaml` 中，现已迁移至 `instances/` 三层架构：

| 原字段 | 现位置 | 说明 |
|--------|--------|------|
| `search_queries` | `instances/campaigns/{name}.yaml` | 搜索关键词组 |
| `max_pages_per_query` | `instances/campaigns/{name}.yaml` → `overrides` 段 | 每组关键词翻页数 |
| `max_total_results` | `instances/campaigns/{name}.yaml` → `overrides` 段 | JD 抓取上限 |
| `matching.weight_profiles` | `instances/strategies/{name}.yaml` | 五维权重方案 |
| `matching.weight_rules` | `instances/strategies/{name}.yaml` | 标题关键词分类规则 |
| `matching.min_match_score` | `instances/strategies/{name}.yaml` | 最低达标分数 |
| `matching.borderline_rescore` | `instances/strategies/{name}.yaml` | 及格线复评开关 |
| `matching.borderline_range` | `instances/strategies/{name}.yaml` | 复评区间 |
| `matching.top_n` | `instances/strategies/{name}.yaml` | 保留 Top N |

详见 [§6 — `instances/` 三层配置组装](#6-instances--三层配置组装)。

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
| `resume.prompt_for_job` | 基于匹配岗位生成简历的指令 | 匹配岗位 |
| `resume.prompt_for_jd_text` | 基于粘贴 JD 生成简历的指令 | JD 文本 |
| `resume.cover_letter_prompt` | Cover Letter 撰写指令 | 求职信生成 |
| `resume.resume_review_prompt` | 英文简历自检（审查定稿） | 简历审查 |
| `resume.aggregate_system_prompt` | 方向聚合分析 + 三级技能分类 | 方向聚合（一键找工作） |
| `resume.prompt_for_direction_data` | 基于聚合数据生成方向简历 | 方向聚合（一键找工作） |
| `resume.cl_for_direction_data` | 方向通用 Cover Letter | 方向聚合（一键找工作） |
| `resume.translate_resume_prompt` | 简历翻译（英→繁中/简中） | 所有模式翻译阶段 |
| `resume.translate_cl_prompt` | Cover Letter 翻译 | 所有模式翻译阶段 |

### 占位符说明

提示词中用 `<name>` 格式的占位符表示运行时自动替换的变量。

| 占位符 | 出现在 | 替换为什么 |
|--------|-------|-----------|
| `<profile_summary>` | job_match, aggregate_system_prompt | 候选人完整档案的 YAML 文本 |
| `<weights_text>` | job_match | 5 维度权重说明（自动从 Campaign 配置的 weight_profile 生成） |
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
- 总分由系统根据策略权重自动计算，你不需要输出 total_score
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

1. **用户画像** → 修改 `job_intent.target_titles` 和 `target_industries`
2. **Campaign / Strategy** → 新建或修改 `instances/campaigns/{name}.yaml`（搜索词）和 `instances/strategies/{name}.yaml`（权重方案）
3. （可选）用户画像 → 调整 `summary` 和 `highlights` 以突出新方向相关经验
4. （可选）`prompts.yaml` → 在 `job_match.scoring_system_prompt` 中调整评分规则

### 场景 2：搜索结果太少

1. `instances/campaigns/{name}.yaml` → 增加更多 `search_queries` 关键词组
2. `instances/campaigns/{name}.yaml` → 在 `overrides` 段调大 `max_pages_per_query`
3. `instances/strategies/{name}.yaml` → 降低 `min_match_score`

### 场景 3：搜索结果噪音太多

1. `instances/campaigns/{name}.yaml` → 用更精确的关键词
2. `instances/strategies/{name}.yaml` → 提高 `min_match_score`
3. `instances/strategies/{name}.yaml` → 调整 `weight_profile` 增加相关维度的权重

### 场景 4：简历不够突出

1. 用户画像 → 优化 `work_experience.highlights`（用数据量化成果）
2. 用户画像 → 完善 `summary`（突出核心竞争力）
3. `resume_guide.yaml` → 调整 `content_rules.work_experience.good_examples` 给 LLM 更好的示范
4. （可选）`prompts.yaml` → 在 `resume.base_rules` 中添加更具体的写作要求

### 场景 5：投不同城市

1. 用户画像 → 修改 `location` 和 `job_intent.location_preference`
2. `instances/campaigns/{name}.yaml` → 修改每组 `search_queries` 的 `location`

### 场景 6：切换搜索结果排序

1. **全局切换** → `search_config.yaml` 修改 `sort_mode` 为 `"relevance"`（按相关度）或 `"date"`（按发布时间）
2. **单个搜索词** → 在对应 Campaign 的 `search_queries` 条目中加 `sort_by: "relevance"` 覆盖全局设置
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
       1. 加载 profiles/search_config.yaml 获取通用配置（llm / filters / 市场参数）
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

# Web UI 模式 — 通过侧边栏「求职方向」下拉框选择 campaign
python web_app.py
```

### 6.5 新旧体系对比

| 维度 | 系统基础设施（profiles/） | 业务配置（instances/） |
|------|-------------------|---------------------|
| 用户画像 | `instances/users/{user}.yaml`（通过 `search_config.yaml` 的 `user` 字段选择） | 同左（同一套画像文件） |
| 权重方案 | —（已迁移） | `instances/strategies/*.yaml`（独立文件，5 种预设） |
| 搜索词 | —（已迁移） | `instances/campaigns/*.yaml`（显式声明） |
| 数量控制 | —（已迁移） | `instances/campaigns/*.yaml` 的 `overrides` 段 |
| LLM / 过滤 / 市场参数 | `search_config.yaml` | —（沿用 profiles/） |
| 配置覆盖 | 直接修改 YAML | `overrides` 字段 + 深度合并 |
| Web UI 支持 | ✅ 侧边栏设置面板、LLM 切换、排序切换 | ✅ 侧边栏 Campaign 下拉框、画像下拉框 |
| 适用场景 | 个人日常使用（不改动的系统参数） | 换方向、批量实验、多用户 |

---

## 配置文件之间的关系

### 系统基础设施（profiles/）

```
.env (API 密钥)
  └──→ config.py 初始化 LLM client

search_config.yaml (LLM / 过滤 / 市场参数 / 画像选择)
  │
  ├──→ job_search.py   读取 filters
  ├──→ market_analysis.py  读取 market_analysis 段
  ├──→ config.py       读取 llm 段初始化客户端
  └──→ config.py       load_profile() 通过 user 字段定位画像

instances/users/{user}.yaml (你是谁)
  │
  ├──→ job_match.py    读取完整档案 → 作为 LLM 评分的参考基准
  ├──→ resume_gen.py   读取全部字段 → 作为简历内容的唯一素材来源
  └──→ market_analysis.py  读取技能 → 用于差距分析对比

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

### 三层组装体系（instances/）

```
instances/users/{user}.yaml         # 用户画像
        │
instances/strategies/{strategy}.yaml # 权重方案 + 匹配参数 + 关键词规则
        │
instances/campaigns/{name}.yaml     # 搜索词 + overrides
        │
        ├──→ config_assembler.py  合并组装
        │         │
        │         ├── base: profiles/search_config.yaml（llm / filters / 市场参数）
        │         ├── + profiles/prompts.yaml
        │         ├── + profiles/resume_template.yaml + resume_guide.yaml
        │         └── → 输出完整配置字典
        │
        └──→ search_jobs / match_jobs 接收 config 参数（通过 _CONFIG_AWARE_TOOLS 自动注入）
```
