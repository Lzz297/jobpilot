# 配置使用手册

本项目使用 **SQLite + YAML** 混合存储。业务配置（画像、策略、Campaign、系统参数）全部在 SQLite 中，通过 Web UI 管理；LLM 提示词和简历规范保留为 YAML 文件。

**核心原则：所有业务配置通过 Web UI 操作，无需编辑文件。**

---

## 目录

| 存储位置 | 控制什么 | 修改方式 | 改动频率 |
|---------|---------|---------|---------|
| [`.env`](#0-env--环境变量) | API 密钥 | 编辑文件 | 极低 |
| [SQLite `user_profiles`](#1-用户画像) | 你是谁、会什么、想找什么 | **Web UI 设置面板** | 低 |
| [SQLite `search_config`](#2-系统配置) | LLM 供应商、过滤条件、市场/搜索参数 | **Web UI 设置面板** | 低 |
| [SQLite `strategies`](#3-策略) | 五维权重 + 关键词分类规则 | **Web UI 设置 → 策略 Tab** | 中 |
| [SQLite `campaigns`](#4-campaign) | 搜索词 + 策略绑定 | **Web UI 设置 → Campaign Tab** | 高 |
| [`profiles/prompts.yaml`](#5-promptsyaml) | LLM 提示词（评分/简历/市场分析） | 编辑文件 | 中 |
| [`profiles/resume_guide.yaml`](#6-resume_guideyaml) | 简历内容怎么写 | 编辑文件 | 低 |
| [`profiles/resume_template.yaml`](#7-resume_templateyaml) | 简历段落顺序和格式 | 编辑文件 | 低 |

---

## 0. `.env` — 环境变量

**作用：** 存放 API 密钥。

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
| 切换到其他 LLM 供应商 | 添加对应的 API Key，然后在 Web UI 侧边栏 LLM 下拉菜单切换 |
| API 调用报错 "key not set" | 检查 `.env` 文件中对应的 Key 是否正确填写 |

**安全提醒：** 不要把 `.env` 文件提交到 git。

### 其他环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `JOB_AGENT_DIAGNOSE` | 未设置（关闭） | 设为 `1`/`true`/`yes`/`verbose` 开启诊断模式，恢复 LLM prompt 全文和原始返回的 SSE 输出 |
| `FLASK_SECRET_KEY` | 自动生成 | Flask session 加密密钥。不设置则每次重启 session 失效 |

---

## 1. 用户画像

**作用：** 这是 Agent 认识你的唯一来源。搜索过滤、匹配评分、简历生成全部依赖它。

**存储位置：** SQLite `user_profiles` 表（`data` 字段存完整 JSON）。通过 `is_current = 1` 标记当前活跃画像。

**修改方式：** Web UI → 设置 → 个人画像 Tab。侧边栏画像下拉框可切换不同用户（更新 `is_current` 标记）。

### 画像字段全览（由 Schema 驱动）

画像结构由 SQLite `field_schemas` 表中 `name='user_field'` 的 JSON Schema 定义。前端根据 Schema 动态渲染表单控件。

#### 分组 1：基本信息 (`basic_info`)

| 字段 key | 显示标签 | 控件类型 |
|----------|----------|----------|
| `name` | 姓名 | 单行文本 |
| `name_en` | 英文名 | 单行文本 |
| `location` | 所在地 | 单行文本 |
| `phone` | 电话 | 单行文本 |
| `email` | 邮箱 | 单行文本 |
| `linkedin` | LinkedIn | 单行文本 |
| `github` | GitHub | 单行文本 |
| `hk_permanent_resident` | 工作权利 / 居留身份 | 下拉单选（香港永久居民/持有工作签证/需要工作签证/其他） |

#### 分组 2：自我评价与定位 (`profile_summary`)

| 字段 key | 显示标签 | 控件类型 | 用途 |
|----------|----------|----------|------|
| `strategic_positioning` | 战略定位 | 多行文本 (15 行) | LLM 用于匹配 JD 方向 |
| `summary` | 自我评价 | 多行文本 (18 行) | LLM 用于判断岗位匹配度 + 简历 Summary 素材 |

#### 分组 3：求职意向 (`job_intent`)

| 字段 key | 显示标签 | 控件类型 | 说明 |
|----------|----------|----------|------|
| `target_titles` | 目标岗位 | 多行文本 | 换行/逗号分隔 |
| `target_industries` | 目标行业 | 多行文本 | 换行/逗号分隔 |
| `job_type` | 工作类型 | 下拉单选 | 全职/兼职/合同/实习 |
| `salary_expectation.min` | 最低薪资 | 数字 | — |
| `salary_expectation.max` | 最高薪资 | 数字 | — |
| `salary_expectation.currency` | 货币 | 下拉单选 | HKD/CNY/USD |
| `salary_expectation.note` | 备注 | 单行文本 | — |
| `notice_period` | 到岗时间 | 下拉单选 | 即时到岗/1个月内/3个月内/面议 |
| `location_preference` | 目标城市 | 单行文本 | — |

#### 分组 4：语言能力 (`languages`)

表格控件，每行 3 列：

| 列 key | 显示标签 | 控件类型 | 选项 |
|--------|----------|----------|------|
| `language` | 语言 | 单行文本 | — |
| `proficiency` | 熟练度 | 下拉单选 | 母语/流利/良好/基础 |
| `certificate` | 证书 / 考试 | 单行文本 | — |

#### 分组 5：专业技能 (`skills`)

分类标签组控件（`map` 类型）。key 是技能类别名（如 `programming_languages`、`frameworks`、`blockchain`、`business_skills` 等），每个类别下是表格：

| 子列 key | 显示标签 | 控件类型 | 选项 |
|----------|----------|----------|------|
| `name` | 技能名 | 单行文本 | — |
| `level` | 熟练度 | 下拉单选 | 精通/熟练/掌握/了解 |
| `detail` | 说明 | 单行文本 | — |

#### 分组 6：工作经历 (`work_experience`)

卡片表格控件，每条经历一张卡片。列定义：

| 列 key | 显示标签 | 控件类型 | 说明 |
|--------|----------|----------|------|
| `company` | 公司 | 单行文本 | — |
| `title` | 职位 | 单行文本 | — |
| `period` | 时间段 | 单行文本 | 如：2024.08 - 2026.05 |
| `company_description` | 公司简介 | 多行文本 | 评估行业匹配度 |
| `company_size` | 公司规模 | 下拉单选 | 初创/中小/中大型/大型 |
| `overview` | 工作概述 | 多行文本 | 职责范围和技术环境 |
| `tech_stack` | 技术栈 | 标签输入 | 数组，按回车添加 |
| `highlights` | 工作亮点 | 多行列表 | 数组，每条一个要点 |
| `key_achievements` | 关键成就 | 子表格 | 见下方 |

**子表：关键成就** (`key_achievements`)：

| 子列 key | 显示标签 | 控件类型 | 说明 |
|----------|----------|----------|------|
| `id` | ID | 单行文本 | 唯一标识（checker 溯源用） |
| `category` | 类别 | 单行文本 | — |
| `title` | 标题 | 单行文本 | — |
| `resume_bullet` | 简历描述 | 多行文本 | STAR 法则，LLM 直接植入简历 |
| `interview_keywords` | 面试关键词 | 标签输入 | — |
| `story` | 详细故事 | 大文本弹窗 | 面试追问用 |

#### 分组 7：项目经历 (`projects`)

表格控件：

| 列 key | 显示标签 | 控件类型 |
|--------|----------|----------|
| `name` | 项目名 | 单行文本 |
| `role` | 角色 | 单行文本 |
| `tech_stack` | 技术栈 | 标签输入 |
| `description` | 描述 | 多行文本 |
| `resume_bullets` | 简历要点 | 子表格（id + text） |

#### 分组 8：教育背景 (`education`)

表格控件：

| 列 key | 显示标签 | 控件类型 |
|--------|----------|----------|
| `degree` | 学位 | 单行文本 |
| `major` | 专业 | 单行文本 |
| `school` | 学校 | 单行文本 |
| `period` | 时间段 | 单行文本（如：2020-2024） |
| `school_en` | 学校 (英文) | 单行文本 |

#### 分组 9：证书 (`certifications`)

标签集合控件（字符串数组）。

### 评分时实际使用的字段

`job_match.py:_build_profile_summary()` 只提取以下顶层 key 传给 LLM：

- `job_intent`
- `skills`
- `work_experience`
- `education`
- `certifications`
- `summary`

`basic_info`、`profile_summary.strategic_positioning`、`projects`、`languages` 不会传入评分 prompt。

### 注意事项

- 工作经历中的 `highlights` 和 `key_achievements[].resume_bullet` 是简历 bullet 的主要素材
- 所有字段无硬性必填校验，但关键字段（如 `skills`、`work_experience`、`summary`）填写越完整，LLM 评分和简历质量越高
- 前端有脏字段追踪：未保存的修改会显示琥珀色标记 + 「已修改 N 个字段」悬浮条

---

## 2. 系统配置

**存储位置：** SQLite `search_config` 表（`data` 字段存完整 JSON，单行）。

**修改方式：** Web UI → 设置 → 找工作配置 Tab / 市场调研配置 Tab。LLM 模型可通过侧边栏下拉菜单实时切换。

### 当前字段全览

```json
{
  "filters": { "exclude_companies": [] },
  "llm": { "provider": "deepseek", "model": "deepseek-v4-pro", "max_concurrency": 20 },
  "market_analysis": { "max_pages": 10, "max_fetch_jd": 200, "batch_size": 3, "jd_max_chars": 6000 },
  "market_presets": { "job_categories": [], "classifications": [] },
  "matching": { "direction_batch_size": 1, "score_batch_size": 5, "rescore_batch_size": 1 },
  "resume_gen": { "jd_max_chars": 3000 },
  "search": { "max_pages": 1, "max_total_results": 15, "jd_max_chars": 6000 },
  "sort_mode": "date"
}
```

### 字段说明

| 配置段 | 配置项 | 默认值 | 说明 |
|--------|--------|--------|------|
| `llm.provider` | — | `"deepseek"` | `deepseek` / `qwen` / `glm` |
| `llm.model` | — | `"deepseek-v4-pro"` | 模型名称 |
| `llm.max_concurrency` | — | 20（deepseek）/ 10（qwen/glm） | 同时发送给 LLM 的最大请求数。设 1 退化为完全串行。切换 Provider 时若未显式设置则自动跟随新默认值 |
| `sort_mode` | — | `"date"` | `"date"`（最新在前）/ `"relevance"`（相关度） |
| `filters.exclude_companies` | `[]` | 排除的公司名（大小写不敏感） |
| `search.max_pages` | 1 | 每组搜索词翻页数 |
| `search.max_total_results` | 15 | JD 抓取上限 |
| `search.jd_max_chars` | 6000 | LLM 评分时单条 JD 截断长度 |
| `matching.direction_batch_size` | 1 | 方向分类每批发给 LLM 的 JD 数量 |
| `matching.score_batch_size` | 5 | 评分每批发给 LLM 的 JD 数量 |
| `matching.rescore_batch_size` | 1 | 复评每批发给 LLM 的 JD 数量 |
| `market_analysis.max_pages` | 10 | 市场调研翻页数 |
| `market_analysis.max_fetch_jd` | 200 | 市场调研 JD 抓取上限 |
| `market_analysis.batch_size` | 3 | 市场调研 LLM 每批分析条数 |
| `market_analysis.jd_max_chars` | 6000 | 市场调研单条 JD 截断长度 |
| `market_presets.job_categories` | `[]` | 市场调研页面的预设岗位类别 |
| `market_presets.classifications` | `[]` | 市场调研页面的预设行业分类 |
| `resume_gen.jd_max_chars` | 3000 | 方向聚合时每条 JD 截断长度 |

> **注意：** `search_config` 表**没有 `user` 字段**。当前活跃画像由 `user_profiles.is_current = 1` 标记决定，通过 Web UI 侧边栏画像下拉框切换。

---

## 3. 策略

**存储位置：** SQLite `strategies` 表。每个策略定义五维匹配权重 + 标题关键词分类规则。

**修改方式：** Web UI → 设置 → 策略 Tab。支持新建/编辑/删除。

### 策略包含的字段

| 字段 | 说明 | 示例 |
|------|------|------|
| `name` | 策略名称（标识符） | `web3` |
| `description` | 描述文本 | "Web3/区块链方向" |
| `weight_profile` | 五维权重（必须和为 100） | `{skill:35, experience:20, level:15, industry:15, bonus:15}` |
| `weight_rules_keywords` | 标题关键词列表（用于 `classify_job()` 回退匹配） | `["blockchain", "crypto", "web3"]` |
| `min_match_score` | 最低达标分数（默认 45） | 45 |
| `top_n` | 保留 Top N（默认 999=全部） | 999 |
| `borderline_rescore` | 是否启用及格线复评 | `true` |
| `borderline_range` | 复评区间（分） | 8 |

### 当前策略一览

| 策略名 | 权重 (技能/经验/职级/行业/加分) | 适用场景 |
|--------|-------------------------------|----------|
| `default` | 30 / 25 / 15 / 15 / 15 | 无法分类的通用岗位 |
| `technical` | 35 / 20 / 15 / 15 / 15 | 纯技术开发岗 |
| `solutions` | 25 / 20 / 15 / 20 / 20 | 方案/集成工程师 |
| `web3` | 35 / 20 / 15 / 15 / 15 | Web3/区块链岗位 |
| `payment` | 25 / 20 / 10 / 25 / 20 | 支付/结算岗位 |
| `business_sales` | 20 / 20 / 15 / 25 / 20 | 纯商务销售岗 |

### 权重校验

- 后端 `POST/PUT /api/strategies` 校验五维之和必须等于 100
- `config_assembler.py` 加载时也会校验并打印警告

---

## 4. Campaign

**存储位置：** SQLite `campaigns` 表。每个 Campaign 绑定一个策略 + 一组搜索关键词。

**修改方式：** Web UI → 设置 → Campaign Tab。侧边栏 Campaign 下拉框切换当前激活的 Campaign（通过 `/api/session/campaign` 设置 session 级别）。

### Campaign 包含的字段

| 字段 | 说明 |
|------|------|
| `name` | Campaign 名称（如 `web3_hunt`） |
| `strategy` | 绑定的策略名（如 `web3`） |
| `search_queries` | 搜索关键词组数组，每组含 `keywords` / `location` / `classification` |

### 使用方式

```bash
# 终端模式 — 加载 campaign（通过 config_assembler.py 组装）
python agent.py --campaign web3_hunt

# Web UI 模式 — 侧边栏「求职方向」下拉框选择
python web_app.py
```

`config_assembler.load_campaign()` 的组装流程：
1. 从 SQLite `campaigns` 表读取 campaign
2. 从 SQLite `user_profiles` 表读取当前活跃画像（`is_current=1`）
3. 从 SQLite `strategies` 表读取全部用户策略 + 当前 campaign 绑定的策略
4. 从 SQLite `search_config` 表读取通用配置
5. 从 `profiles/` 加载 prompts.yaml / resume_template.yaml / resume_guide.yaml
6. 合并输出完整配置字典

---

## 5. `prompts.yaml`

**作用：** 所有 LLM 提示词的唯一来源。共 15 个 prompt 模板。

**存储位置：** `profiles/prompts.yaml`（YAML 文件，不从 SQLite 读取）。

### 结构总览

| 段落 | 用途 | 影响什么功能 |
|------|------|------------|
| `agent.system_prompt` | Agent 的身份和行为规则 | 对话交互 |
| `job_match.direction_classification_prompt` | LLM 方向分类规则 | 匹配 — 方向判定 |
| `job_match.scoring_system_prompt` | LLM 五维评分指导 | 匹配 — 评分 |
| `market_analysis.analysis_system_prompt` | JD 数据提取规则 | 市场分析 |
| `market_analysis.gap_analysis_prompt` | 候选人差距分析 | 市场分析 |
| `market_analysis.report_prompt` | 报告撰写指令 | 市场分析 |
| `resume.base_rules` | 简历通用基础规则 | 所有简历模式 |
| `resume.prompt_for_job` | 匹配岗位模式指令 | 简历 — 匹配岗位 |
| `resume.prompt_for_jd_text` | JD 文本模式指令 | 简历 — JD 文本 |
| `resume.cover_letter_prompt` | Cover Letter 指令 | 求职信 |
| `resume.resume_review_prompt` | 简历审查定稿 | 简历审查 |
| `resume.aggregate_system_prompt` | 方向聚合 + 三级技能分类 | 简历 — 方向聚合 |
| `resume.prompt_for_direction_data` | 基于聚合数据生成简历 | 简历 — 方向聚合 |
| `resume.cl_for_direction_data` | 方向通用 Cover Letter | 简历 — 方向聚合 |
| `resume.translate_resume_prompt` | 简历翻译 | 所有模式翻译 |
| `resume.translate_cl_prompt` | Cover Letter 翻译 | 所有模式翻译 |

### 占位符说明

| 占位符 | 出现在 | 替换为什么 |
|--------|-------|-----------|
| `<profile_summary>` | job_match, aggregate | 候选人档案 JSON（从画像提取） |
| `<weights_text>` | job_match | 五维权重描述（自动生成） |
| `<score_formula>` | job_match | 总分计算公式（自动生成） |
| `<direction_list>` | direction_classification | 可用方向列表 |
| `<job_category>` | market_analysis | 用户指定的岗位类别 |
| `<guide>` | resume.base_rules | 简历指南（resume_guide.yaml） |
| `<template>` | resume.prompt_for_* | 简历模板（resume_template.yaml） |
| `<base_rules>` | resume.prompt_for_* | 渲染后的基础规则文本 |
| `<direction>` | direction_data, cl_direction | 方向名称 |
| `<target_lang>` | translate | 目标语言 |

### 修改原则

- **可以改：** 角色设定、判断规则、评分标准、写作风格
- **不要改：** `<占位符>` 名称、JSON 输出格式中的字段名

---

## 6. `resume_guide.yaml`

**作用：** 告诉 LLM 怎么写简历内容。通过 `<guide>` 占位符注入到简历生成 prompt。

**存储位置：** `profiles/resume_guide.yaml`。

包含章节：`general`（页数/市场）、`ats_rules`（ATS 友好）、`content_rules`（段落写法）、`weakness_handling`（弱点处理）、`hk_specific`（香港市场）、`cover_letter`（Cover Letter 规则）。

---

## 7. `resume_template.yaml`

**作用：** 控制简历的段落顺序和输出格式。

**存储位置：** `profiles/resume_template.yaml`。

```yaml
format: "markdown"
output_style: "professional"
sections_order: [summary, skills, work_experience, projects, education, certifications]
customization:
  auto_reorder_skills: true
  auto_adjust_summary: true
  max_pages: 2
```

---

## 常见操作速查

### 场景 1：换一个求职方向

1. **Web UI 设置 → Campaign Tab** → 新建或编辑 Campaign（绑定策略 + 搜索词）
2. **Web UI 侧边栏** → 切换到新 Campaign
3. （可选）**Web UI 设置 → 个人画像 Tab** → 调整求职意向和目标岗位
4. （可选）编辑 `prompts.yaml` → 调整评分规则

### 场景 2：搜索结果太少

1. **Web UI 设置 → 找工作配置 Tab** → 调大 `max_pages` 和 `max_total_results`
2. **Web UI 设置 → Campaign Tab** → 增加更多搜索关键词组
3. **Web UI 设置 → 策略 Tab** → 降低 `min_match_score`

### 场景 3：搜索结果噪音太多

1. **Web UI 设置 → Campaign Tab** → 用更精确的关键词
2. **Web UI 设置 → 策略 Tab** → 提高 `min_match_score`，调整权重

### 场景 4：简历不够突出

1. **Web UI 设置 → 个人画像 Tab** → 优化工作经历的 `highlights` 和 `key_achievements`
2. 编辑 `resume_guide.yaml` → 调整 `content_rules`
3. （可选）编辑 `prompts.yaml` → 添加更具体的写作要求

### 场景 5：切换 LLM 模型

**Web UI 侧边栏 LLM 下拉菜单** → 直接选择，**即时生效**，自动回写 SQLite。

### 场景 6：切换搜索结果排序

**Web UI 侧边栏排序按钮** → 按发布时间 / 按相关度。或 Web UI 设置 → 找工作配置 Tab → 修改 `sort_mode`。

---

## 配置体系架构图

```
SQLite (job_agent.db)
├── user_profiles     ← 用户画像（is_current=1 为当前活跃）
├── search_config     ← 系统基础设施（LLM/过滤/市场/搜索参数）
├── strategies        ← 五维权重 + 关键词规则（每人一套副本）
├── campaigns         ← 搜索词 + 策略绑定（每人多个）
└── field_schemas     ← 画像字段 Schema（驱动前端表单渲染）

YAML 文件 (profiles/)
├── prompts.yaml          ← 15 个 LLM 提示词模板
├── resume_template.yaml  ← 简历结构
└── resume_guide.yaml     ← 简历撰写规范

.env                     ← API 密钥

组装流程（config_assembler.py）:
  search_config (SQLite) + user_profiles (SQLite) + strategies (SQLite)
  + campaigns (SQLite) + prompts.yaml + resume_template.yaml + resume_guide.yaml
  → 完整配置字典 → search_jobs / match_jobs / resume_gen
```
