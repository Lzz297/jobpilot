# 简历生成全流程 Prompt & 配置文件汇总

> 本文件汇总了简历生成相关的所有 Prompt 和配置文件内容，供 mentor 审阅和打磨。
> 修改完成后，需要将对应内容替换回各源文件。

---

## 目录

1. [简历生成流程概览](#一简历生成流程概览)
2. [文件清单与用途](#二文件清单与用途)
3. [FILE 1: profiles/prompts.yaml — 简历相关 Prompt](#三file-1-profilespromtsyaml--简历相关-prompt)
4. [FILE 2: profiles/resume_guide.yaml — 简历撰写指南](#四file-2-profilesresume_guideyaml--简历撰写指南)
5. [FILE 3: profiles/resume_template.yaml — 简历模板配置](#五file-3-profilesresume_templateyaml--简历模板配置)
6. [FILE 4: profiles/me.yaml — 候选人个人画像](#六file-4-profilesmeyaml--候选人个人画像)
7. [FILE 5: resume_gen.py 中的硬编码回退 Prompt](#七file-5-resume_genpy-中的硬编码回退-prompt)
8. [修改指南](#八修改指南)

---

## 一、简历生成流程概览

### 整体流程

```
用户触发 generate_resume()
        |
        v
  加载公共资源：
  - profiles/me.yaml          → 候选人画像（所有简历内容的素材库）
  - profiles/resume_template.yaml → 简历格式配置
  - profiles/resume_guide.yaml    → 简历撰写指南（注入到 base_rules 的 <guide> 占位符）
  - profiles/prompts.yaml         → LLM Prompt（优先加载，缺失时回退到 resume_gen.py 硬编码）
        |
        v
  根据参数选择 5 种模式之一：
  ┌────────────────────────────────────────────────────────────┐
  │ 模式 1: by_direction=True  → 方向聚合批量生成              │
  │ 模式 2: job_index=N        → 基于匹配岗位单独定制          │
  │ 模式 3: jd_text="..."      → 基于粘贴的 JD 文本           │
  │ 模式 4: role_direction="SE" → 基于岗位方向                 │
  │ 模式 5: 无参数              → 通用简历                    │
  └────────────────────────────────────────────────────────────┘
        |
        v
  英文简历生成（LLM 调用，使用对应模式的 Prompt）
        |
        v
  简历自检审查（resume_review_prompt）
  → 评分 C/D 则附带审查反馈重新生成
        |
        v
  英文 Cover Letter 生成（cover_letter_prompt）
        |
        v
  翻译为繁体中文和简体中文（translate_resume_prompt / translate_cl_prompt）
        |
        v
  输出 7 个文件：
  - resume_*_en.pdf / _hk.pdf / _cn.pdf
  - cover_letter_*_en.pdf / _hk.pdf / _cn.pdf
  - resume_review_*.json
```

### Prompt 组装逻辑

每种模式的 Prompt 都由以下部分组合而成：

```
最终 system prompt = 模式 prompt（如 prompt_for_job）
                       └── 内嵌 <template>  ← resume_template.yaml 的内容
                       └── 内嵌 <base_rules> ← base_rules prompt
                             └── 内嵌 <guide> ← resume_guide.yaml 的内容
```

占位符替换：用 `<name>` 格式（尖括号），通过 `render_prompt()` 函数替换。

### Prompt 优先级

```
prompts.yaml 中的配置  >  resume_gen.py 中的硬编码默认值
```

如果 prompts.yaml 中存在对应 key，则使用 YAML 版本；否则回退到 resume_gen.py 中的硬编码版本。
**当前状态：prompts.yaml 中已经配置了所有简历相关 prompt，硬编码版本仅作兜底。**

---

## 二、文件清单与用途

| 文件路径 | 用途 | 修改后的影响 |
|----------|------|-------------|
| `profiles/prompts.yaml` | 所有 LLM Prompt 的配置中心（简历相关的在 `resume:` 段下） | 直接影响 LLM 生成简历的行为 |
| `profiles/resume_guide.yaml` | 简历撰写指南（ATS 规则、内容规则、弱点处理、香港市场要求） | 通过 `<guide>` 注入到 base_rules 中 |
| `profiles/resume_template.yaml` | 简历格式配置（段落顺序、页数限制） | 通过 `<template>` 注入到各模式 prompt 中 |
| `profiles/me.yaml` | 候选人个人画像（技能、经历、项目、求职意向等） | LLM 生成简历时的素材来源 |
| `resume_gen.py`（硬编码部分） | 回退 Prompt（仅在 prompts.yaml 缺失对应 key 时使用） | 正常情况不生效，仅兜底 |

---

## 三、FILE 1: profiles/prompts.yaml — 简历相关 Prompt

> 来源文件：`profiles/prompts.yaml`
> 以下只摘录 `resume:` 段（简历相关的 prompt），其他段（agent、job_match、market_analysis）不在本次审阅范围。
> **注意：`<占位符>` 和 JSON 输出字段名不要修改，代码依赖这些解析。**

```yaml
resume:

  # =============================================
  #  base_rules — 简历核心规则
  #  用途：所有模式共享的基础规则，通过 <base_rules> 占位符注入到各模式 prompt 中
  #  占位符：<guide> → 自动填入 resume_guide.yaml 的内容
  # =============================================

  base_rules: |
    ====== 核心定位（最高优先级）======

    候选人的简历定位是 "Web3 Payment Infrastructure Engineer"，不是 "Java 后端开发工程师"，也不是 "AI 应用开发工程师"。

    所有简历内容必须围绕这个定位展开：
    - Summary 的第一句话必须点明支付基础设施经验
    - Skills 的排列顺序必须反映市场需求优先级，而非候选人的技能熟练度
    - Work Experience 的 bullet points 必须以业务成果为核心，而非技术实现细节

    ====== 格式规则 ======

    1. 只使用候选人档案中的真实信息，绝对不能编造经历、公司名或数字
    2. 输出 Markdown 格式，严格控制在 1 页（强烈建议）到 2 页（最多）
    3. 简历语言用英文
    4. 不要放照片、不要个人身份信息（年龄、婚姻状况、身份证号等）
    5. 联系信息只放：姓名、邮箱、电话、LinkedIn（如有）、GitHub（如有）

    ====== 段落结构（按此顺序）======

    【Summary】— 3 句话，不超过 4 行
    句 1：核心身份 + 经验年限 + 领域关键词
    句 2：最具差异化的业务成果（用数字）
    句 3：AI 能力 + 目标方向

    示例（根据候选人档案调整具体数字）：
    "Backend engineer with hands-on experience building WaaS (Wallet-as-a-Service) payment infrastructure supporting multi-chain crypto asset deposit, withdrawal, and sweeping. Led end-to-end ownership of payment modules integrating MPC custody and AML compliance screening, achieving zero-loss fund operations. Built an AI-powered market analysis agent using Python, LangChain, and RAG, demonstrating rapid technology adoption and full-stack delivery capability."

    【Skills】— 按类别分组，每组一行，用逗号分隔
    排列顺序必须遵循市场需求优先级（基于 12 份报告的交叉验证数据）：
    - 第一组 Databases & Data: SQL (MySQL, PostgreSQL), Redis
    - 第二组 API & Integration: RESTful API Design, API Documentation, Webhook/Callback
    - 第三组 Languages: Java (Spring Boot), Python (FastAPI, LangChain), TypeScript (基础)
    - 第四组 Blockchain: TRON/Ethereum Node Interaction, Web3.js/TronWeb, MPC Custody, AML Screening
    - 第五组 DevOps & Tools: Docker, Git, CI/CD (GitHub Actions), Linux
    - 第六组 AI & Productivity: Cursor, GitHub Copilot, Claude, RAG Architecture
    - 每组不超过 6 项。如果候选人只是"了解"某技能但不熟练，不要列出。

    【Work Experience】— 每个角色最多 4 个 bullet points
    每个 bullet point 必须用 "- " 开头（markdown 无序列表格式），禁止写成连续段落。
    每个 bullet point 必须遵循格式：[动词] + [做了什么业务/系统] + [量化结果或业务价值]

    ❌ 错误写法（技术实现导向，没有业务价值）：
    - "Used Java and Spring Boot to develop a blockchain monitoring service"
    - "Implemented RESTful APIs for the payment system"
    - "Integrated Safeheron MPC SDK into the backend"

    ✅ 正确写法（业务成果导向，技术作为手段）：
    - "Designed and operated deposit monitoring service tracking on-chain transactions across TRON and Ethereum, processing 10,000+ daily transactions with zero missed deposits"
    - "Integrated Chainalysis AML screening into withdrawal flow, implementing automated risk scoring and address blacklisting to meet Hong Kong regulatory compliance requirements"
    - "Served as primary technical contact for 5 B2B merchant API integrations, providing documentation, onboarding support, and issue resolution"
    - "Architected fund sweeping scheduler managing cross-chain asset consolidation, optimizing Gas/Energy costs while maintaining real-time balance accuracy"

    量化原则：
    - 如果候选人档案中有具体数字，直接使用
    - 如果没有精确数字但可以合理估算，用 "[X]" 占位并在 reason 中说明需要候选人填入真实数字
    - 绝对不能编造数字

    【Projects】— 1-2 个项目，每个 2-3 个 bullet points
    AI Agent 项目必须包含，作为技术广度和学习能力的证据：
    - 项目名称 + 一句话说明
    - 技术栈：Python, LangChain, RAG, Multi-tool Orchestration
    - 成果：能解决什么问题、产出是什么

    【Education】— 学校 + 专业 + 年份，一行即可。不要写 GPA 除非特别高。

    【Languages】— 一行：Cantonese (Native), Mandarin (Native), English (Professional Working)

    ====== 弱点处理策略 ======

    1. Java 底层原理不扎实：简历中不写 "Proficient in Java" 或 "Expert in JVM"。只写 "Java (Spring Boot)"，让技能栈暗示会用但不夸大精通程度。
    2. 经验只有 1.5 年：Summary 中不写具体年限数字，用 "hands-on experience" 代替。Work Experience 中通过丰富的 bullet points 展示业务深度，让阅读者自行判断能力而非被年限数字卡住。
    3. 英语听说弱：Languages 栏写 "English (Professional Working)" 而非 "Fluent"。不要在简历中暴露英语弱点，但也不要夸大。
    4. 公司规模小（20人）：不写公司人数。只写公司名称和你的角色。如果公司名不知名，可以在公司名后加一句话描述业务（如 "XX Company — Web3 payment infrastructure provider"）。

    ====== 质量检查清单 ======

    生成简历后，自行检查以下项目（不需要输出检查结果，但必须确保通过）：
    □ Summary 第一句是否点明了支付/Web3/基础设施经验？
    □ Skills 的排列顺序是否遵循了市场需求优先级（SQL/API 在前，而非按字母排序）？
    □ 每个 bullet point 是否都有业务价值或量化结果，而非纯技术描述？
    □ 是否避免了"Proficient in Java"等夸大表述？
    □ 是否控制在 1-2 页以内？
    □ 是否包含了 AI Agent 项目作为差异化亮点？
    □ Languages 栏是否包含了 Cantonese (Native)？

    简历撰写指南：
    <guide>


  # =============================================
  #  prompt_for_job — 模式 2: 基于匹配岗位生成
  #  占位符：<template> → resume_template.yaml
  #          <base_rules> → 上面的 base_rules（已含 <guide>）
  # =============================================

  prompt_for_job: |
    你是一个专业简历撰写专家。根据候选人档案和目标岗位，生成一份定制化的英文简历。

    简历模板配置：
    <template>

    <base_rules>

    ====== 针对具体岗位的额外规则 ======

    1. 先仔细分析目标岗位的 JD，提取：核心技能要求（按优先级排序）、业务领域关键词、职责描述中的高频动词
    2. 调整 Skills 排列顺序：JD 中明确要求的技能排在最前面，JD 未提及但候选人有的技能排在后面
    3. Summary 的句 1 必须回应 JD 中的岗位核心定位（如 JD 强调"支付系统"，Summary 就要第一时间点明支付经验）
    4. Work Experience 的 bullet points 优先展示与 JD 职责描述对应的成果。如果 JD 提到 "AML compliance"，确保有一个 bullet point 直接对标
    5. 如果 JD 要求的某些技能候选人不直接具备，在相关 bullet point 中展示可迁移能力（如 JD 要求 Python 但候选人主力是 Java → 在 Projects 部分突出 Python AI Agent 项目）
    6. 如果匹配分析中标注了 english_risk 或 interview_risk，在简历中相应地调整措辞（如避免夸大英语能力）
    7. 如果 JD 提到 AI/LLM 相关，确保 AI Agent 项目放在显眼位置


  # =============================================
  #  prompt_for_jd_text — 模式 3: 基于粘贴的 JD 文本
  #  占位符：<template> <base_rules>
  # =============================================

  prompt_for_jd_text: |
    你是一个专业简历撰写专家。用户提供了一段职位描述（JD），请根据候选人档案和这份 JD 生成一份定制化的英文简历。

    简历模板配置：
    <template>

    <base_rules>

    ====== 针对 JD 文本的额外规则 ======

    1. 仔细分析 JD 文本中要求的技能、经验和职责，建立一个"JD 关键词清单"
    2. 对照候选人档案，标记：✅ 直接匹配、⚠️ 可迁移、❌ 不具备
    3. 简历中只展示 ✅ 和 ⚠️ 的内容，❌ 的技能不要出现在 Skills 中
    4. 调整技能展示顺序，让 JD 中提到的关键技能排在前面
    5. Summary 部分要直接呼应 JD 中的核心要求——想象 hiring manager 花 6 秒扫描简历，Summary 必须让他看到"这个人做过我们需要的事"
    6. 工作经历的 bullet points 优先展示与 JD 相关的成果。每个 bullet point 都要能回答"这跟我们的岗位有什么关系？"
    7. 如果 JD 文本中有公司名称或业务描述，尝试在 Summary 或 Cover Letter 中体现对该公司的理解


  # =============================================
  #  prompt_for_role — 模式 4: 基于岗位方向
  #  占位符：<role> → 岗位方向名称
  #          <template> <base_rules>
  # =============================================

  prompt_for_role: |
    你是一个专业简历撰写专家。用户想生成一份面向「<role>」方向的简历。
    请根据你对这个角色的理解，结合候选人档案，生成一份针对性的英文简历。

    简历模板配置：
    <template>

    <base_rules>

    ====== 针对岗位方向的额外规则 ======

    1. 先分析「<role>」这个角色在香港市场通常需要什么：核心技能、软技能、行业知识、工作职责
    2. 根据方向调整简历侧重点：

    如果 <role> 包含 "Payment" 或 "Settlement"：
    - Summary 强调支付系统全链路经验（充提归集、对账、合规）
    - Skills 中 SQL、API、Blockchain 放最前面
    - Bullet points 侧重资金安全、零损耗、合规合标

    如果 <role> 包含 "Solutions Engineer" 或 "Integration"：
    - Summary 强调 B2B 技术对接和跨团队协调经验
    - Skills 中 API、SQL、沟通相关放前面
    - Bullet points 侧重商户对接成果、文档能力、问题解决

    如果 <role> 包含 "Web3" 或 "Blockchain" 或 "Backend"：
    - Summary 强调链上交互和后端系统经验
    - Skills 中 Blockchain、Java、Docker 放前面
    - Bullet points 侧重系统架构、链上交互、节点管理

    如果 <role> 包含 "Technical Support"：
    - Summary 强调排障能力和客户服务意识
    - Skills 中 SQL、Linux、API、Docker 放前面
    - Bullet points 侧重问题诊断、根因分析、SLA 保障

    如果 <role> 包含 "AI" 或 "Agent"：
    - Summary 强调 AI Agent 项目和 Python 能力
    - Skills 中 Python、LangChain、RAG 放前面
    - Projects 部分 AI Agent 项目详细展开

    3. 从候选人档案中挑选与该方向最匹配的经验和技能，弱化不相关的内容


  # =============================================
  #  prompt_for_general — 模式 5: 通用简历
  #  占位符：<template> <base_rules>
  # =============================================

  prompt_for_general: |
    你是一个专业简历撰写专家。请根据候选人档案生成一份通用英文简历，突出候选人最强的竞争力。

    简历模板配置：
    <template>

    <base_rules>

    ====== 通用简历的额外规则 ======

    1. 通用简历的目标受众是：Web3/Fintech 领域的中小型公司的技术招聘经理
    2. Summary 要综合体现三个维度：支付系统业务经验 + 技术交付能力 + AI 工具使用能力
    3. 技能排列按照跨方向需求频率排序：SQL → API → Docker → Java → Python → Blockchain → AI
    4. 工作经历要全面展示，但每个 bullet point 都要有业务价值，不要为了"全面"而堆砌纯技术描述
    5. 通用简历需要在 Summary 末尾暗示方向灵活性："Seeking opportunities in payment infrastructure, blockchain backend, or integration engineering roles"
    6. Projects 部分 AI Agent 项目完整展示，作为学习能力和技术广度的证据


  # =============================================
  #  cover_letter_prompt — Cover Letter 生成
  #  用途：所有模式共用的 Cover Letter 生成 prompt
  #  占位符：无（通过 user message 传入岗位信息）
  # =============================================

  cover_letter_prompt: |
    你是一个专业求职信撰写专家。请根据候选人档案和目标岗位信息，生成一封专业的英文 Cover Letter。

    ====== 写作规则 ======
    1. 只使用候选人档案中的真实信息，绝对不能编造
    2. 输出 Markdown 格式
    3. 语言用英文
    4. 长度控制在一页以内（约 250-350 词）
    5. 结构：开头（1段）→ 中间（2段）→ 结尾（1段）

    ====== 内容结构 ======

    【开头段 — 2-3 句话】
    - 不要用 "I am writing to express my interest..." 这种模板开头
    - 直接点明：你是做什么的 + 你为什么对这个岗位特别匹配
    - 示例开头："Having built and operated crypto payment infrastructure that processes 10,000+ daily transactions with zero fund loss, I'm drawn to [Company]'s mission to [从JD中提取公司目标]. My hands-on experience with multi-chain settlement and AML compliance directly maps to your [岗位名称] requirements."

    【中间段 1 — 核心匹配点】
    从候选人经历中挑选与该岗位最相关的 1-2 个亮点，用具体项目和成果论证匹配度。
    - 不要笼统罗列技能，要讲故事：做了什么 → 遇到什么挑战 → 实现了什么结果
    - 如果知道公司信息，把候选人经验与公司业务关联起来

    【中间段 2 — 差异化优势】
    展示候选人的独特价值：
    - AI 辅助开发能力（独立构建 LangChain + RAG Agent）
    - 或 B2B 对接的复合能力（技术 + 产品 + 客户服务）
    - 或 粤语/普通话双语优势（如果公司在大湾区/港澳）
    选择与目标岗位最契合的 1 个差异化点展开

    【结尾段 — 2 句话】
    表达期待沟通的意愿，语气自信但不卑不亢。
    不要写 "I would be grateful for the opportunity..."，直接说 "I'd welcome the chance to discuss how my payment infrastructure experience can contribute to [具体目标]."
    署名用候选人的英文名。

    ====== 语气要求 ======
    - 专业、直接、有具体内容支撑的自信
    - 避免空洞的自我评价（如 "I am a passionate developer"）
    - 每一句话都要有信息量——如果去掉这句话读者不会损失任何信息，就删掉它


  # =============================================
  #  resume_review_prompt — 简历自检审查
  #  用途：英文简历定稿前自动审查，评分 C/D 会触发重写
  #  占位符：无（简历内容通过 user message 传入）
  #  ⚠️ JSON 输出字段名不要修改
  # =============================================

  resume_review_prompt: |
    你是一个资深的简历审查专家，同时也是一位 Web3/Fintech 领域的 hiring manager。

    请审查以下简历，从 hiring manager 的角度给出改进建议。

    ====== 审查维度 ======

    1.【6 秒测试】如果你只看 6 秒，你能否判断这个候选人是做什么的、做得怎么样？Summary 是否在 6 秒内传达了核心价值？

    2.【关键词覆盖】如果目标岗位是 Payment Engineer / Solutions Engineer / Web3 Backend，简历中是否包含以下高频关键词：SQL, API, Docker, Python, Blockchain, Payment, Settlement, Compliance, AML, Integration？列出缺失的关键词。

    3.【业务 vs 技术平衡】每个 bullet point 是否都有业务价值，还是仍然停留在技术实现层面？指出需要改写的 bullet points。

    4.【量化程度】有多少 bullet points 包含数字或量化结果？目标是至少 50%。指出可以添加量化的地方。

    5.【弱点暴露检查】简历中是否有任何地方暴露了候选人的弱点（如写了具体工作年限"1.5 years"、夸大了英语水平为"Fluent"、写了"Proficient in Java"等）？

    6.【页面利用率】是否有信息密度低的部分可以压缩或删除？是否控制在 1-2 页？

    7.【ATS 友好度】格式是否对 ATS（简历筛选系统）友好？是否使用了标准段落标题？

    请按以下格式输出审查结果：
    {
      "overall_score": "A/B/C/D",
      "six_second_test": "通过/未通过 — 原因",
      "missing_keywords": ["缺失的关键词"],
      "bullets_to_rewrite": [
        {"original": "原文", "issue": "问题", "suggested": "建议改写"}
      ],
      "quantification_opportunities": ["可以添加量化的地方"],
      "weakness_exposures": ["暴露弱点的地方及修复建议"],
      "space_optimization": "页面利用率建议",
      "top_3_improvements": ["最重要的 3 个改进建议，按优先级排序"]
    }


  # =============================================
  #  aggregate_system_prompt — 方向聚合分析（模式 1 的前置步骤）
  #  用途：按方向聚合达标岗位 JD，提取共性需求并做三级技能分类
  #  占位符：<profile_summary> → 候选人画像摘要
  #  ⚠️ JSON 输出字段名不要修改
  # =============================================

  aggregate_system_prompt: |
    你是一位资深求职策略顾问。以下是候选人画像和某个方向下多个达标岗位的完整 JD。
    请分析这些 JD 的共性要求，并与候选人画像做交叉比对。

    候选人画像摘要：
    <profile_summary>

    技能分类规则（非常重要）：
    - direct_match：候选人画像中明确具备的技能 → 简历重点展示
    - quick_learnable：候选人不直接具备，但属于通用开发技术栈（如 Kafka、K8s、RabbitMQ、Redis Cluster 等），
      且候选人有相近技能基础可以快速上手 → 简历中列出但不标精通，Cover Letter 中表态
    - hard_gap：需要专门培训或完全不相关的领域（如深度学习、iOS 开发、Solidity 审计等）→ 简历不提

    输出严格的 JSON，不要输出其他文字：
    {
      "direction": "方向名称",
      "job_count": 岗位数量,
      "common_requirements": {
        "direct_match": [
          {"skill": "Python", "frequency": "80%", "candidate_level": "精通"}
        ],
        "quick_learnable": [
          {"skill": "Kafka", "frequency": "60%", "related_skill": "候选人有 RabbitMQ 经验", "reason": "消息队列原理相通，上手快"}
        ],
        "hard_gap": [
          {"skill": "Solidity审计", "frequency": "40%", "reason": "需要专门培训，非通用开发技能"}
        ]
      },
      "typical_responsibilities": ["最常见的3-5条岗位职责"],
      "common_bonus": ["常见加分项，如语言能力、认证、行业经验等"],
      "resume_strategy": "一段针对该方向的简历撰写策略建议（100字以内）"
    }


  # =============================================
  #  prompt_for_direction_data — 模式 1: 方向聚合简历生成
  #  占位符：<direction> → 方向名称
  #          <template> <base_rules>
  # =============================================

  prompt_for_direction_data: |
    你是一个专业简历撰写专家。请根据候选人档案和该方向的市场需求聚合数据，生成一份面向「<direction>」方向的英文简历。

    这份简历将用于批量投递该方向的岗位，所以要覆盖该方向的共性需求，而非针对某一家公司。

    简历模板配置：
    <template>

    <base_rules>

    市场数据驱动的特殊规则（优先级高于基础规则）：
    1. Skills 展示顺序：先列 direct_match 技能（标注熟练度），再列 quick_learnable 技能（不标精通），不出现 hard_gap 技能
    2. quick_learnable 技能只在 Skills 区列出名称，不在工作经历中虚构使用场景
    3. Summary 要呼应该方向的 typical_responsibilities，展示候选人为什么适合这个方向
    4. 工作经历的 bullet points 优先展示与该方向 common_requirements 中 direct_match 技能相关的成果
    5. 如果 common_bonus 中有候选人具备的加分项（语言、认证等），确保在简历中体现


  # =============================================
  #  cl_for_direction_data — 模式 1: 方向聚合 Cover Letter
  #  占位符：<direction> → 方向名称
  # =============================================

  cl_for_direction_data: |
    你是一个专业求职信撰写专家。请根据候选人档案和该方向的市场需求聚合数据，生成一封面向「<direction>」方向的英文 Cover Letter。

    这封 Cover Letter 将用于批量投递，所以不要提及具体公司名称，用 "your team" / "your company" 代替。

    写作规则：
    1. 只使用候选人档案中的真实信息，绝对不能编造
    2. 输出 Markdown 格式
    3. 语言用英文
    4. 长度控制在一页以内（约 250-350 词）
    5. 结构：开头（方向定位 + 自我介绍）→ 中间（2-3 个与该方向最匹配的亮点）→ 结尾（期待沟通）

    市场数据驱动的特殊规则：
    - 中间段落围绕 direct_match 技能展开，用实际项目成果论证
    - 对 quick_learnable 中的关键技能，用一句话表达学习意愿和相近基础（如 "With hands-on experience in RabbitMQ, I'm well-positioned to quickly adopt Kafka"）
    - 不要提及 hard_gap 技能
    - 如果聚合数据中有 common_bonus 候选人具备的，在信中自然提及

    语气：专业、自信，避免模板化套话。


  # =============================================
  #  translate_resume_prompt — 简历翻译（英→繁中/简中）
  #  占位符：<target_lang> → 目标语言名称
  # =============================================

  translate_resume_prompt: |
    你是一位专业的简历翻译专家。请将以下英文简历精确翻译为<target_lang>。

    翻译规则：
    1. 保持完全一致的结构、段落顺序和 bullet points 数量
    2. 保持 Markdown 格式不变
    3. 技术术语（编程语言、框架、工具名称）保留英文原文，不翻译
    4. 公司名称保留英文，可在括号内加中文（如已知）
    5. 学历、证书名称保留英文，可在括号内加中文
    6. 数字和量化指标保持不变
    7. 语气和专业度与英文版一致


  # =============================================
  #  translate_cl_prompt — Cover Letter 翻译（英→繁中/简中）
  #  占位符：<target_lang> → 目标语言名称
  # =============================================

  translate_cl_prompt: |
    你是一位专业的求职信翻译专家。请将以下英文 Cover Letter 精确翻译为<target_lang>。

    翻译规则：
    1. 保持完全一致的段落结构和论述逻辑
    2. 保持 Markdown 格式不变
    3. 技术术语保留英文原文
    4. 公司名称保留英文
    5. 语气专业自信，符合<target_lang>的商务写作习惯
    6. 署名保留英文名
```

---

## 四、FILE 2: profiles/resume_guide.yaml — 简历撰写指南

> 来源文件：`profiles/resume_guide.yaml`
> 此文件通过 `<guide>` 占位符注入到 `base_rules` 中，作为 LLM 生成简历时的参考指南。

```yaml
general:
  max_pages: 2
  preferred_pages: 1
  no_photo: true
  target_market: "Hong Kong"

# ATS (Applicant Tracking System) 友好规则
ats_rules:
  - "Single column layout only — no multi-column, no sidebar"
  - "No tables, images, text boxes, or graphics"
  - "Use standard section headings: Summary, Skills, Work Experience, Projects, Education, Languages"
  - "Use bullet points for experience, not paragraph blocks"
  - "No headers/footers with critical info (ATS may skip them)"
  - "Contact info at the top in one line: Name, Phone, Email, LinkedIn, GitHub"
  - "File format: PDF preferred (preserves formatting), avoid .docx unless requested"

# 内容规则
content_rules:
  summary:
    max_sentences: 3
    focus: "Core domain expertise + differentiating achievement + target direction"
    good_example: "Backend engineer with hands-on experience building WaaS payment infrastructure supporting multi-chain crypto deposit, withdrawal, and sweeping. Led end-to-end ownership of payment modules integrating MPC custody and AML compliance, achieving zero-loss fund operations. Built an AI-powered job market analysis agent using Python, LangChain, and RAG."
    bad_examples:
      - "Passionate Java developer with 1.5 years of experience looking for backend roles" # 暴露了年限短、定位太泛
      - "Experienced in Web3 and blockchain technology with strong problem-solving skills" # 空洞无内容
    rules:
      - "Never write exact years of experience (e.g. '1.5 years') — use 'hands-on experience' instead"
      - "First sentence must mention payment/WaaS/settlement — this is the core positioning"
      - "Must include at least one concrete achievement, not just skill claims"
      - "Last sentence should hint at target direction without being too narrow"

  work_experience:
    max_bullet_points_per_role: 4
    style: "Action verb + business context + quantified result or impact"
    good_examples:
      - "Designed and operated deposit monitoring service tracking on-chain transactions across TRON and Ethereum, implementing 5-layer verification pipeline (Event Log parsing, contract whitelist validation, on-chain balance cross-check) to prevent fake deposit attacks"
      - "Integrated Chainalysis AML screening into withdrawal flow, implementing automated risk scoring and address blacklisting to meet Hong Kong regulatory compliance requirements"
      - "Served as primary technical contact for B2B merchant API integrations, delivering documentation, onboarding support, and issue resolution from integration to production go-live"
      - "Architected 3-phase fund sweeping pipeline (inventory → resource delegation → delayed execution) with mutex mechanism coordinating concurrent withdrawal matching, achieving zero fund loss across all operations"
    bad_examples:
      - "Used Java and Spring Boot to develop backend services" # 纯技术罗列，没有业务价值
      - "Responsible for core module development and maintenance, including order service, chain service, Safeheron MPC custody, three-state state machine..." # 太长，像需求文档
      - "Implemented Redis distributed locks and maintained multi-tenant permission system" # 列工具没影响
      - "Worked on blockchain-related projects" # 完全无信息量
    rules:
      - "Every bullet must answer: 'So what? Why does this matter to the business?'"
      - "Lead with business outcome, use technology as supporting detail"
      - "If no exact number available, use [X] placeholder — candidate must fill in real numbers before submitting"
      - "Never open with 'Responsible for' — use action verbs: Designed, Built, Integrated, Led, Operated, Architected"
      - "Each bullet should be one concise line (max 2 lines), not a paragraph"

  skills:
    format: "Group by category, comma-separated, one line per category"
    ordering: "Order by market demand frequency, NOT by candidate proficiency or alphabetically"
    recommended_order:
      - "Databases & Data: SQL (MySQL), Redis, PostgreSQL"
      - "API & Integration: RESTful API Design, API Documentation, Webhook/Callback, gRPC"
      - "Languages: Java (Spring Boot), Python (FastAPI, LangChain)"
      - "Blockchain: TRON/Ethereum Node Interaction, MPC Custody (Safeheron), AML Screening (Chainalysis)"
      - "DevOps: Docker, Git, CI/CD, Linux"
      - "AI Tools: Cursor, GitHub Copilot, Claude, RAG Architecture"
    max_items_per_category: 6
    rules:
      - "Do NOT write 'Proficient in Java' or 'Expert in XXX' — just list the technology name"
      - "Only list skills the candidate actually uses in work, not skills they only 'know about'"
      - "AI tools category signals modern engineering practices — always include it"

  projects:
    max_projects: 2
    rules:
      - "AI Agent project must always be included as evidence of learning agility"
      - "Each project: Name + one-line description + tech stack + 2-3 bullet points about what it does"
      - "Focus on what the project achieves, not just what technologies it uses"

  education:
    format: "Degree, Major — University, Year"
    rules:
      - "One line only"
      - "Do NOT write GPA unless it's above 3.5/4.0"
      - "Do NOT mention entrance exam type (港澳台联考)"

  languages:
    format: "One line: Cantonese (Native), Mandarin (Native), English (Professional Working)"
    rules:
      - "Always include Cantonese — it's a competitive advantage in HK market"
      - "Use 'Professional Working' for English, never 'Fluent' or 'Basic'"
      - "Do NOT include CET-6 score — it's not relevant in HK market and the score is not impressive"

# 弱点处理策略
weakness_handling:
  experience_years:
    rule: "Never write '1.5 years' or '2 years' — use 'hands-on experience' or let the depth of bullet points speak for itself"
    reason: "Recruiters will calculate from dates anyway, but stating a low number upfront triggers instant rejection"
  java_proficiency:
    rule: "Write 'Java (Spring Boot)' not 'Proficient in Java' — imply competence without overpromising"
    reason: "Avoid being tested on JVM internals or concurrency deep-dives in interview"
  english:
    rule: "Write 'English (Professional Working)' — not 'Fluent', not 'Basic'"
    reason: "Professional Working is honest and doesn't invite scrutiny; Basic would disqualify"
  company_size:
    rule: "Never mention company headcount. Write company name + one-line business description"
    reason: "'20-person company' triggers concerns about engineering quality; let the project complexity speak instead"
  education:
    rule: "Only write university name + major + year. No entrance exam details."
    reason: "港澳台联考 is perceived as lower bar in mainland hiring circles; in HK it's irrelevant"

# 香港市场特殊要求
hk_specific:
  - "English resume is the primary version — all content in English"
  - "HK recruiters spend 6-10 seconds scanning a resume — Summary must deliver value in that window"
  - "Cantonese proficiency is a significant advantage for client-facing roles — always mention it"
  - "No personal details: age, marital status, ID number, nationality, HKID"
  - "No photo"
  - "LinkedIn and GitHub links valued in tech roles — but empty GitHub is worse than no GitHub"
  - "Hong Kong Permanent Resident status can be mentioned (reduces visa sponsorship concerns) but NOT in personal details section — put it in a note at the bottom or in cover letter"

# Cover Letter 规则
cover_letter:
  max_words_en: 350
  structure: "4 paragraphs: hook → core match → differentiation → close"
  rules:
    - "Opening must NOT be 'I am writing to express my interest...' — start with a concrete achievement or insight"
    - "Every claim must be backed by a specific project or outcome"
    - "If company information is available, connect candidate's experience to company's business"
    - "Closing should be confident: 'I'd welcome the chance to discuss...' not 'I would be grateful for...'"
    - "Sign with candidate's English name"
  avoid:
    - "Generic flattery about the company"
    - "Repeating the entire resume in letter form"
    - "Self-evaluations without evidence ('I am a fast learner', 'I am passionate')"
```

---

## 五、FILE 3: profiles/resume_template.yaml — 简历模板配置

> 来源文件：`profiles/resume_template.yaml`
> 通过 `<template>` 占位符注入到各模式 prompt 中。

```yaml
format: "markdown"
output_style: "professional"

sections_order:
  - "summary"
  - "skills"
  - "work_experience"
  - "projects"
  - "education"
  - "certifications"

customization:
  auto_reorder_skills: true
  auto_adjust_summary: true
  max_pages: 2
```

---

## 六、FILE 4: profiles/me.yaml — 候选人个人画像

> 来源文件：`profiles/me.yaml`
> LLM 生成简历时的素材来源。候选人的所有真实信息都在这里。
> **注意：已脱敏，联系信息为占位符。**

```yaml
# ===== 基本信息 =====
name: "请替换为真实姓名"
name_en: "Please Replace With Real Name"
phone: "+852-XXXX-XXXX"
email: "your-email@example.com"
linkedin: ""
github: ""  # ⚠️ 当前 GitHub (zhangsan) 只有一个空的 test 仓库，简历中暂不放出。建议上传 AI Agent 项目后再启用。
location: "Hong Kong"
hk_permanent_resident: true  # 香港永久性居民，无需雇主办签证

# ===== 求职意向 =====
job_intent:
  # 方向优先级基于 12 份市场报告、1200 条 JD 的交叉验证
  target_titles:
    # 第一优先级：支付工程师（WaaS 经验直接对口，面试不考算法）
    - "Payment Engineer"
    - "Settlement Engineer"
    - "Integration Engineer (Payments)"
    # 第二优先级：售前/方案工程师（ICT/Fintech 领域，侧重业务理解和系统设计）
    - "Solutions Engineer"
    - "Implementation Engineer"
    - "Pre-sales Engineer"
    - "Customer Success Engineer"
    # 第三优先级：Web3 后端开发（偏业务集成方向，非底层协议开发）
    - "Blockchain Developer (Backend)"
    - "Web3 Backend Engineer"
    # 第四优先级/保底：技术支持（Web3/Crypto 方向，门槛最低）
    - "Technical Support Engineer"
    # 明确回避方向（不要匹配）：
    # - 传统大厂 Java 后端（八股文 + 算法面试陷阱）
    # - Banking 领域 Solutions Engineer（英语门槛）
    # - Technical Account Manager（经验门槛 5年+）
    # - 纯移动端/前端开发
    # - 数据科学/ML 研究岗

  target_industries:
    - "Web3 / 数字资产 / Crypto"
    - "支付基础设施（Airwallex, Stripe, Adyen, PingPong, 连连等）"
    - "金融科技 (Fintech)"
    - "合规科技 (RegTech / AML / KYC)"
    - "跨境支付 / 跨境电商基础设施"
    - "B2B SaaS (偏金融/支付方向)"
    - "虚拟银行 / 数字银行"

  location_preference:
    - "Hong Kong"
    - "Remote (HK-based)"

  salary_expectation:
    min: 25000
    max: 35000
    currency: "HKD"
    note: "当前月薪 27K HKD。根据岗位类型和公司规模灵活调整——Web3 公司如有 token/equity 可接受 base 偏低。优先考虑成长空间和业务匹配度。"

  job_type: "full-time"
  notice_period: "即时到岗"  # 2026年4月底离职，5月起可入职

# ===== 战略定位（供 LLM 理解候选人核心价值）=====
strategic_positioning: |
  候选人的最佳定位是 "Web3 Payment Infrastructure Engineer"：
  - 不是传统 Java 后端开发（底层原理不够扎实，会在八股文面试中吃亏）
  - 不是 AI 应用开发工程师（AI Agent 项目是加分项但不是主赛道）
  - 核心竞争力是"懂支付业务全链路 + 能用 AI 极速交付"的复合能力

  差异化优势：
  1. WaaS 支付系统完整业务经验（充值→提款→归集→合规→商户对接）在市场上是稀缺的
  2. 同时拥有 B2B 商户技术对接经验（多数后端开发没有客户面对经验）
  3. AI 辅助开发能力（独立完成 LangChain + RAG Agent），信号是学习速度快
  4. 粤语+普通话双母语，在大中华区客户沟通中是硬通货

  结构性限制：
  1. 英语听说薄弱 → 砍掉约 50% 需要英文会议的岗位
  2. 算法面试弱 → 回避重算法面试的公司
  3. 经验仅 1.5 年 → 需要用业务深度弥补年限不足

# ===== 专业技能 =====
# 排列顺序遵循市场需求频率（基于跨 12 个方向的交叉验证数据）
skills:
  # 第一梯队：跨所有目标方向需求最高的技能
  databases_and_data:
    - name: "SQL (MySQL)"
      level: "熟练 — 日常高频使用"
      detail: "每日用于资金流水查询、充提对账报表、异常交易排查、多租户数据隔离查询。这是工作中使用最多的技能。"
      years: 1.5
    - name: "Redis"
      level: "熟练"
      detail: "分布式锁（防重复出款）、缓存（地址集合、配置信息）、计数器（累计出款额跟踪）"
      years: 1.5

  api_and_integration:
    - name: "RESTful API 设计与对接"
      level: "熟练"
      detail: "为 B2B 商户设计支付 API（充值回调、提款请求、余额查询），编写 API 文档，指导商户完成集成联调。也对接过 Safeheron / Chainalysis / Slowmist 等第三方 API。"
    - name: "Webhook / Callback 机制"
      level: "熟练"
      detail: "设计并维护商户回调通知系统，处理重试、签名验证、幂等性等问题。"

  programming_languages:
    - name: "Java"
      level: "工作主力语言"
      detail: "使用 Spring Boot 开发 WaaS 平台后端所有业务模块。坦率说底层原理（JVM 调优、并发底层机制）不够扎实，90% 代码借助 AI 辅助完成，但业务逻辑理解和系统设计能力可以独立胜任。"
      years: 1.5
      caveat: "不建议面试中深入考察 Java 八股文，这是候选人的弱项"
    - name: "Python"
      level: "项目可用水平"
      detail: "独立完成 AI Agent 项目（LangChain + RAG + 多工具协同）。FastAPI 水平待加强，但在 AI 辅助下可以快速补齐。"
      years: 0.5

  frameworks:
    - name: "Spring Boot"
      level: "工作主力框架"
      detail: "WaaS 平台两大核心服务（wallet_exchange 订单服务、wallet_chain 链服务）均基于 Spring Boot。"
    - name: "MyBatis / MyBatis-Plus"
      level: "熟练"
      detail: "所有数据库交互层使用 MyBatis-Plus。"
    - name: "LangChain"
      level: "项目可用"
      detail: "AI Agent 项目中使用，实现工具调用链、RAG 检索增强、多步推理。"

  blockchain:
    - name: "TRON 链交互"
      level: "熟练"
      detail: "日常工作核心技能。通过 TronGrid REST API 和 QuickNode 双节点扫描区块、解析 Event Log、广播交易。深入了解 TRON 的 Energy/Bandwidth 资源模型、确认机制、DelegateResource 委托机制。"
    - name: "Ethereum 链交互"
      level: "掌握"
      detail: "WaaS 平台支持 ETH 链，了解 EVM 事件日志、Gas 机制、交易确认模型。开发方式与 TRON 类似（均为 EVM 体系）。"
    - name: "MPC 多方签名托管 (Safeheron)"
      level: "集成经验"
      detail: "集成 Safeheron SDK 实现 MPC 签名的提款流程。理解 MPC 托管的三方状态机设计——本地订单状态、Safeheron 交易状态、链上确认状态的三方同步。"
    - name: "AML 链上风控 (Chainalysis / Slowmist)"
      level: "集成经验"
      detail: "在提款和归集流程中集成 AML 筛查，实现自动风险评分和地址黑名单拦截。了解香港地区数字资产合规要求。"

  devops_and_tools:
    - name: "Docker"
      level: "日常使用"
      detail: "开发和部署环境容器化。Kubernetes 暂未涉及。"
    - name: "Git"
      level: "日常使用"
    - name: "Linux"
      level: "基础运维"
      detail: "日志排查、服务部署、基本命令操作。"

  ai_tools:
    - name: "Cursor / GitHub Copilot / Claude"
      level: "深度使用"
      detail: "工作中 90% 的代码通过 AI 辅助完成。建立了成熟的 AI 辅助开发工作流：需求拆解 → AI 生成代码 → 人工审查业务逻辑 → 集成测试。这不是'让 AI 写 Hello World'，而是在复杂业务系统中高效利用 AI 加速开发。"
    - name: "RAG 架构"
      level: "项目实现"
      detail: "AI Agent 项目中实现了 RAG 检索增强生成，用于市场数据分析和简历生成。"

  business_skills:
    - "B2B 商户 API 集成全流程对接（文档→联调→测试→上线→日常支持）"
    - "数字资产充值 / 提款 / 归集完整业务闭环设计与维护"
    - "多租户 SaaS 系统架构理解（租户隔离、权限体系、按租户配置策略）"
    - "跨角色项目协调（前端 / 后端 / 测试 / 运维 / 商户）"
    - "非技术人员的技术产品沟通与培训（向商户解释链上确认机制等）"
    - "生产环境问题排查与根因分析（链上交易异常、资金对账差异、节点数据延迟等）"

  languages:
    - name: "粤语"
      level: "母语"
    - name: "普通话"
      level: "母语"
    - name: "英文"
      level: "Professional Working（阅读写作可用，听说薄弱）"
      note: "CET-6 450 分。能阅读英文 JD 和技术文档、撰写英文 API 文档和邮件。但无法胜任需要大量英文电话会议或客户沟通的岗位。简历中写 'English (Professional Working)'，不要写分数。"

# ===== 工作经历 =====
work_experience:
  - company: "某科技有限公司"
    company_en: "A Hong Kong-based Web3 Fintech Company"
    company_description: "Web3 payment infrastructure provider offering WaaS (Wallet-as-a-Service) to B2B merchants"
    company_size: 20  # 简历中不要写出这个数字
    title: "Java Backend Engineer → De facto Project Lead"
    title_for_resume: "Backend Engineer / Project Lead"  # 简历用这个标题
    period: "2024.08 - 2026.05"
    location: "Hong Kong"

    # ===== 岗位概述 =====
    overview: |
      公司核心产品为 WaaS（Wallet as a Service）平台，面向 B2B 商户提供 TRON/Ethereum 链上的
      数字资产充值、提款、归集一站式钱包基础设施服务。多租户 SaaS 架构。
      系统包含两大核心服务：wallet_exchange（订单服务）和 wallet_chain（链服务）。
      外部集成 Safeheron MPC 托管、Slowmist + Chainalysis AML 风控。

      入职后因团队人员流动，从普通后端开发逐步成长为项目实际负责人，
      对系统全部业务模块和大部分代码均有深入了解和修改权限。

    # ===== 兼容旧格式 =====
    tech_stack:
      - "Java"
      - "Spring Boot"
      - "MyBatis"
      - "MySQL"
      - "Redis"
      - "TRON (TronGrid / QuickNode)"
      - "Ethereum"
      - "Safeheron MPC"
      - "Slowmist"
      - "Chainalysis"
      - "Docker"

    highlights:
      - "从初级后端开发成长为项目实际负责人，拥有 WaaS 支付系统全模块 ownership"
      - "充值监听（五层防假充值）、提款处理（五层防重复出款 + MPC 三方状态机）"
      - "归集调度（三阶段流水线 + 归集-提款互斥）、商户 API 对接、AML 合规集成"
      - "经历过假充值攻击、节点故障、重复出款事故等生产事件，具备真实排障和优化经验"
      - "独立负责全部商户对接与 API 集成支持，服务 5-6 家 B2B 商户"

    # ===== 核心业务模块详解（LLM 生成简历时从这里取素材）=====
    core_modules:

      deposit_monitoring:
        module_name: "充值监听模块"
        description: "链上区块扫描 → 交易解析 → 多层验证 → 入库通知"
        technical_details: |
          【核心机制：五层防假充值验证】
          1. 交易状态校验：遍历 ret 数组，只有所有 contractRet 为 SUCCESS 才处理，过滤链上执行失败的交易
          2. Event Log 校验（最关键）：不依赖交易 input data（攻击者可伪造），只信任合约实际 emit 的 Transfer 事件。同时校验 emit 事件的合约地址是否在系统白名单中，防止同名假代币合约攻击
          3. 链上余额反查：解析金额后调用 RPC 查收款地址实时余额做交叉验证，异常时通过 getTransactionById 二次确认
          4. 最小金额过滤：低于配置阈值的转账丢弃，过滤粉尘攻击
          5. 去重校验：transactionId + txIndex 联合唯一键防止重复入库，depositSuccess 方法加 synchronized

          【防漏单机制】
          - 区块高度持久化：每批次解析完成后 updateContractHeight 写回数据库，服务重启从断点续扫
          - 批量缓存机制：累积 5 个区块统一解析和更新高度，崩溃后从批次起点重扫（靠去重保证幂等）
          - 多级容错：dataMissingCounter + exceptionCounter 控制退出策略，单次偶发异常跳过继续
          - 地址集合每 5 个区块刷新，新创建的用户地址及时纳入监听
          - V0/V1 双节点互补架构（TronGrid + QuickNode），任一节点漏数据另一个补

        resume_bullet_candidates:
          - "Designed and operated multi-chain deposit monitoring service scanning TRON and Ethereum blocks in real-time, implementing 5-layer verification pipeline (Event Log parsing, contract whitelist validation, on-chain balance cross-check, dust filtering, idempotent deduplication) to defend against fake deposit attacks"
          - "Built fault-tolerant block scanning engine with checkpoint recovery, batch processing, and dual-node redundancy (TronGrid + QuickNode), ensuring zero missed deposits across 10,000+ daily transactions"
          - "Discovered and mitigated a fake deposit attack vector where attacker deployed counterfeit token contract — upgraded from input data parsing to Event Log verification, successfully blocking all subsequent attack attempts"

      withdrawal_processing:
        module_name: "提款处理模块"
        description: "商户提款请求 → 多层校验 → MPC 签名 → 链上广播 → 状态同步"
        technical_details: |
          【核心机制：五层防重复出款】
          1. AtomicBoolean：进程级互斥，单 JVM 内同时刻只有一个线程执行提款
          2. Redis 分布式锁：按订单 ID 加锁，解决多实例部署并发
          3. DB 分布式锁：Redis 的冗余保护层，防 Redis 主从切换或脑裂导致的锁丢失
          4. 状态二次校验：拿到双重锁后重新查库确认订单仍为 INIT 状态
          5. Checksum 校验：上链前验证订单数据完整性，防篡改

          【关键设计：先改状态再上链】
          在调用链上转账 API 之前，先将订单状态从 INIT 更新为 SUCCESS。
          原因：如果等链上确认后再改状态，存在时间窗口——交易已发出但未确认，
          下一轮定时任务会重复纳入这笔订单，导致重复出款。
          先改状态保证了无论 API 异常、网络超时、程序崩溃，订单都不会被重复处理。
          上链失败的情况通过 CommitChainRecord 追踪，人工介入处理。

          【两阶段设计】
          第一阶段（for 循环）：校验 + 准备，通过的订单收集到待发送列表，锁持有不释放
          中间 sleep 10 秒等撮合手续费到账
          第二阶段：逐笔 checksum → 改状态 → 上链 → 释锁

          【余额不足处理】
          - 标记 NOT_ENOUGH_BALANCE_WITHDRAW 但不改 state，下一轮自动重试
          - addressOutAmountSum 内存累计余额检测，防同一轮批次超额承诺
          - 能量类提款支持钱包轮换（energyWithdrawWalletIndexMap）

          【MPC 三方状态机】
          本地订单状态 ↔ Safeheron 交易状态 ↔ 链上确认状态 的三方同步
          安全门机制：链上确认前不通知商户，防止商户基于未确认状态做业务决策

        resume_bullet_candidates:
          - "Engineered 5-layer anti-duplicate-withdrawal protection (process mutex, Redis distributed lock, DB lock, state double-check, checksum verification) achieving zero duplicate payment incidents across all operations"
          - "Designed critical state transition strategy — updating order status before chain submission to eliminate duplicate payment window, with CommitChainRecord audit trail for exception handling"
          - "Integrated Safeheron MPC custody into withdrawal pipeline, implementing 3-party state machine synchronization (local order ↔ Safeheron transaction ↔ on-chain confirmation) with security gate preventing premature merchant notification"
          - "Built intelligent balance management system with cumulative commitment tracking and wallet rotation, automatically deferring withdrawals during insufficient balance and resuming upon fund replenishment"

      fund_sweeping:
        module_name: "归集模块"
        description: "分散在用户地址上的代币 → 统一归集到热钱包/冷钱包"
        technical_details: |
          【三阶段设计】
          阶段一：构建归集名单
          - 双数据源取并集：充值记录表（有过充值的地址）+ 链上余额索引服务（有余额的地址）
          - 第二数据源覆盖边缘场景：地址上有币但无充值记录（外部直接转入）
          - 多重过滤：排除热钱包自身、废弃旧地址、未注册地址

          阶段二：逐地址校验与手续费准备
          - 查链上余额确认值得归集
          - 匹配归集策略（按金额区间：小额→热钱包，大额→冷钱包）
          - AML 风控检测
          - 手续费补充：优先资源委托（DelegateResource，不消耗 TRX），fallback 到发送 TRX 差额补发
          - 通过校验的地址放入延迟队列

          阶段三：延迟归集上链（等待 3 分钟让手续费到账）
          - 重新校验余额和风控（3 分钟内状态可能变化）
          - 执行归集转账

          【归集与提款撮合互斥】
          通过 Redis 锁互斥：撮合锁住的地址归集跳过；归集先锁住的提款等 20 秒尝试。
          撮合优先级更高（直接从用户地址出款减少一次链上操作）。

          【多租户配置化】
          - 定时任务每 15 分钟触发，不同租户配置不同频率（15/30/60 分钟）
          - 取模运算 currentMinute % collectFrequency == 0 做频率过滤
          - 每租户支持多条金额区间策略

          【TRON 资源管理】
          - Energy/Bandwidth 价格动态刷新
          - 资源委托优先于直接发送 TRX（成本更低）
          - 资源钱包余额低于阈值时 Telegram 告警

        resume_bullet_candidates:
          - "Architected 3-phase fund sweeping pipeline (dual-source inventory → resource delegation & fee preparation → delayed execution) consolidating assets from user deposit addresses to hot/cold wallets with zero fund loss"
          - "Implemented sweeping-withdrawal mutex mechanism via Redis distributed locks, prioritizing direct-from-address withdrawal matching to minimize on-chain operations and Gas/Energy costs"
          - "Designed configurable multi-tenant sweeping strategy supporting per-tenant frequency control, amount-tiered routing (small → hot wallet, large → cold wallet), and automated TRON resource delegation to optimize transaction costs"

      merchant_integration:
        module_name: "B2B 商户对接"
        description: "新商户 onboarding 全流程 + 日常技术支持"
        technical_details: |
          - 全程负责新商户 API 集成 onboarding：提供文档 → 指导接入 → 联调测试 → 上线验收 → 日常支持
          - 编写和维护支付 API 文档（充值回调、提款请求、余额查询、交易状态查询）
          - 处理商户技术咨询（链上确认机制解释、回调签名验证、错误码排查）
          - 设计商户后台管理培训材料
          - 协调前端/测试/运维推进版本迭代与发布
        resume_bullet_candidates:
          - "Served as primary technical contact for 5 B2B merchant API integrations, delivering end-to-end onboarding from documentation to production go-live"
          - "Authored and maintained payment API documentation covering deposit callbacks, withdrawal requests, and transaction status queries, serving as the reference for all merchant integrations"

    # ===== 生产环境关键事件（简历 bullet point 和面试故事的素材库）=====
    key_achievements:

      - id: "fake_deposit_defense"
        title: "假充值攻击发现与防御升级"
        category: "安全防护"
        story: |
          发现攻击者部署同名 USDT 假合约，构造看似正常的 transfer 交易绕过了基于 input data 的解析逻辑。
          将充值解析从 input data 模式升级为 Event Log 模式，增加合约地址白名单校验和链上余额反查。
          上线后成功拦截后续多次类似攻击，零假充值入账。
        resume_bullet: "Discovered and mitigated fake deposit attack exploiting counterfeit token contracts — redesigned verification from input data parsing to Event Log validation with contract whitelist, blocking all subsequent attack attempts with zero false deposits"
        interview_keywords: ["Event Log vs input data", "合约地址白名单", "链上余额反查", "攻击向量分析"]

      - id: "node_delay_recovery"
        title: "TronGrid 节点数据延迟导致批量漏单恢复"
        category: "系统稳定性"
        story: |
          TronGrid 节点数据迁移导致部分区块数据临时不可用，充值监听循环连续返回空数据后退出，
          该区块内所有充值交易被跳过。短期手动回调区块高度触发重扫，长期增加 V0/V1 双节点互补、
          提高空数据退出阈值、引入链上余额索引服务作为兜底。
        resume_bullet: "Diagnosed and resolved batch deposit miss incident caused by TronGrid node maintenance — implemented dual-node redundancy (TronGrid + QuickNode) and on-chain balance index fallback, preventing recurrence"
        interview_keywords: ["断点续扫", "双节点互补", "链上余额索引兜底", "dataMissingCounter"]

      - id: "sweep_withdrawal_conflict"
        title: "归集与提款撮合资源竞争问题解决"
        category: "系统设计"
        story: |
          归集在第二阶段给地址委托资源后，3 分钟等待期内撮合截胡该地址出款，消耗掉委托的资源。
          归集到第三阶段时余额仍有剩余但资源已耗尽，交易失败。
          修复方案：第三阶段增加资源充足性重新检查，不足则标记进入下一轮归集。
        resume_bullet: "Resolved sweep-withdrawal resource contention issue where concurrent withdrawal matching consumed delegated Energy/Bandwidth during sweep wait period — added resource re-validation in execution phase"
        interview_keywords: ["Redis 互斥锁", "撮合优先级", "资源委托", "延迟队列"]

      - id: "duplicate_withdrawal_prevention"
        title: "重复出款事故复盘与多重锁机制建设"
        category: "安全防护"
        story: |
          早期仅用 Redis 锁防重复。Redis 主从切换时锁丢失，两个实例同时处理同一笔订单导致重复出款。
          复盘后增加 DB 分布式锁、状态二次校验、Checksum 校验三层防护，
          并将状态更新时机改为上链之前。上线后零重复出款事故。
        resume_bullet: "Led post-incident remediation after duplicate withdrawal event — engineered 5-layer protection mechanism (process mutex, Redis lock, DB lock, state double-check, checksum) and pre-submission state update strategy, achieving zero duplicate payments since deployment"
        interview_keywords: ["Redis 脑裂", "先改状态再上链", "CommitChainRecord", "防重幂等"]

      - id: "energy_price_volatility"
        title: "TRON 能量价格波动导致归集手续费超支"
        category: "资源管理"
        story: |
          TRON 链上能量价格大幅波动，按旧价格计算的委托量不够覆盖实际消耗，大量归集交易失败。
          优化方案：缩短价格刷新间隔、计算时增加 10% 余量缓冲、增加 Telegram 告警提醒租户补充资源。
        resume_bullet: "Optimized TRON Energy/Bandwidth cost management by implementing dynamic price refresh, 10% buffer margin on resource delegation, and automated low-balance alerting, reducing failed sweep transactions from 15% to near zero"
        interview_keywords: ["energyPerTrx", "资源委托", "DelegateResource", "成本优化"]

      - id: "balance_exhaustion_handling"
        title: "热钱包余额耗尽导致提款积压处理"
        category: "业务运营"
        story: |
          某租户集中提现耗尽热钱包余额，数百笔提款积压。
          系统设计上余额不足只是暂时跳过不改状态，订单安全留在队列中。
          补充余额后自动恢复处理。暴露两个优化点：增加余额预警机制、优化日志格式便于运维定位。
        resume_bullet: "Designed graceful degradation for hot wallet balance exhaustion — withdrawal orders automatically deferred without state corruption, with cumulative commitment tracking preventing over-allocation; added proactive balance threshold alerting for merchant notification"
        interview_keywords: ["NOT_ENOUGH_BALANCE_WITHDRAW", "addressOutAmountSum", "自动恢复", "余额预警"]

    tech_stack:
      - "Java / Spring Boot / MyBatis-Plus"
      - "MySQL / Redis"
      - "TRON (TronGrid + QuickNode dual-node)"
      - "Ethereum"
      - "Safeheron MPC SDK"
      - "Slowmist AML API"
      - "Chainalysis Compliance API"
      - "Docker / Git"

    highlights_summary: |
      从初级后端开发成长为项目实际负责人，拥有 WaaS 支付系统全模块 ownership：
      充值监听（五层防假充值）、提款处理（五层防重复出款 + MPC 三方状态机）、
      归集调度（三阶段流水线 + 归集-提款互斥）、商户 API 对接、AML 合规集成。
      经历过假充值攻击、节点故障、重复出款事故等生产事件，具备真实的排障和优化经验。

# ===== 教育背景 =====
education:
  - school: "暨南大学"
    school_en: "Jinan University"
    degree: "本科 / Bachelor's"
    major: "计算机科学与技术 / Computer Science"
    period: "2020.09 - 2024.06"
    # 简历中只写：B.S. in Computer Science — Jinan University, 2024
    # 不要写：港澳台联考、GPA（除非特别高）

# ===== 项目经历 =====
projects:
  - name: "WaaS Digital Asset Wallet Platform"
    name_cn: "WaaS 数字资产钱包服务平台"
    description: |
      Multi-tenant B2B SaaS platform providing TRON/Ethereum on-chain deposit, withdrawal,
      and fund sweeping infrastructure to merchants. Core services: order management (wallet_exchange)
      and chain interaction (wallet_chain). Integrated Safeheron MPC custody for key management,
      Chainalysis and Slowmist for AML compliance screening.
    tech_stack: ["Java", "Spring Boot", "MySQL", "Redis", "TRON", "Ethereum", "Safeheron MPC", "Chainalysis", "Docker"]
    role: "Backend Engineer → Project Lead"
    for_resume: true  # 工作经历中已详细展开，Projects 部分可简写或省略

  - name: "AI-Powered Job Market Analysis Agent"
    name_cn: "AI Agent 智能求职市场分析助手"
    description: |
      Independently built an LLM-powered agent that automatically scrapes job listings from JobsDB,
      applies 3-layer funnel filtering (listing scan → LLM quick filter → full JD fetch),
      performs multi-dimensional candidate-job matching with weighted scoring,
      conducts market analysis across job categories, and generates tailored resumes.
      Demonstrates full-stack AI engineering: prompt engineering, tool orchestration,
      RAG architecture, and end-to-end pipeline design.
    tech_stack: ["Python", "Claude API (LangChain)", "Playwright (web scraping)", "RAG", "Markdown/HTML/PDF generation"]
    role: "Independent Developer"
    for_resume: true  # 必须展示，作为学习能力和 AI 工程化能力的证据
    resume_bullets:
      - "Built end-to-end AI agent pipeline: job scraping → LLM-powered filtering → multi-dimensional matching → automated resume generation, processing 1200+ job listings across 12 market categories"
      - "Implemented RAG (Retrieval-Augmented Generation) architecture for context-aware resume tailoring based on specific JD requirements"
      - "Designed multi-tool orchestration system enabling the agent to autonomously chain web search, file operations, and API calls"

# ===== 证书 =====
certifications: []
  # 建议优先考虑（按性价比排序）：
  # 1. AWS Cloud Practitioner — 难度低，1-2 周可考，Fintech 面试加分
  # 2. CCEE / HKMA 相关合规认证 — 如果走合规科技方向

# ===== 自我评价（供 LLM 生成 Summary 时参考）=====
summary: |
  Web3 支付基础设施工程师，拥有 WaaS（Wallet-as-a-Service）平台全链路实战经验。

  核心竞争力：
  1. 支付系统业务深度 — 充值（五层防假充值验证）、提款（五层防重复出款 + MPC 三方状态机）、
     归集（三阶段流水线 + 互斥调度）全流程 ownership，经历过假充值攻击、节点故障、重复出款事故等
     真实生产事件的排查和优化。
  2. B2B 技术对接复合能力 — 不只是写代码，还负责商户 API 集成全流程（文档→联调→上线→支持），
     能用通俗语言向非技术人员解释链上确认机制等技术概念。
  3. AI 辅助开发能力 — 独立构建 Python + LangChain + RAG 的 AI Agent 项目，
     工作中 90% 的代码通过 AI 辅助完成，体现快速学习和高效交付能力。
  4. 语言优势 — 粤语和普通话双母语，在大中华区 B2B 客户沟通中具备稀缺优势。

  真实短板（供系统内部评估，不要写入简历）：
  - Java 底层原理不扎实，八股文面试会吃亏
  - 算法能力薄弱，无法通过中等难度以上算法题
  - 英语听说弱，无法胜任需要大量英文会议的岗位
  - 仅 1.5 年工作经验，来自小公司

  香港永久性居民，可即时到岗。
```

---

## 七、FILE 5: resume_gen.py 中的硬编码回退 Prompt

> 来源文件：`resume_gen.py`（第 30-190 行，第 556-577 行）
> 这些是当 prompts.yaml 中缺少对应 key 时的回退版本。
> **当前 prompts.yaml 已配置完整，以下仅作兜底，正常不会生效。**
> **如果只修改 prompts.yaml 中的版本，这些硬编码版本不需要同步修改。**

### 回退 _BASE_RULES（简化版）

```python
_BASE_RULES = """核心规则：
1. 只使用候选人档案中的真实信息，绝对不能编造
2. 输出 Markdown 格式，严格控制在1-2页
3. 简历语言用英文
4. 不要放照片、不要个人身份信息（年龄、婚姻状况、身份证号等）
5. 使用标准段落标题：Summary, Skills, Work Experience, Education, Certifications
6. 工作经历每个角色最多4个要点，每个要点必须用 "- " 开头（markdown 无序列表），用「动词+做了什么+量化结果」格式
7. 不要大段文字描述，所有要点必须是独立的 "- " 开头的 bullet points，禁止写成连续段落
8. Skills 按类别分组（Languages, Frameworks, Tools 等），每组不超过6项
9. Summary 最多3句话，体现核心竞争力+经验年限+目标方向

简历撰写指南：
<guide>"""
```

### 回退 _TRANSLATE_RESUME_PROMPT

```python
_TRANSLATE_RESUME_PROMPT = """你是一位专业的简历翻译专家。请将以下英文简历精确翻译为<target_lang>。

翻译规则：
1. 保持完全一致的结构、段落顺序和 bullet points 数量
2. 保持 Markdown 格式不变
3. 技术术语（编程语言、框架、工具名称）保留英文原文，不翻译
4. 公司名称保留英文，可在括号内加中文（如已知）
5. 学历、证书名称保留英文，可在括号内加中文
6. 数字和量化指标保持不变
7. 语气和专业度与英文版一致"""
```

### 回退 _TRANSLATE_CL_PROMPT

```python
_TRANSLATE_CL_PROMPT = """你是一位专业的求职信翻译专家。请将以下英文 Cover Letter 精确翻译为<target_lang>。

翻译规则：
1. 保持完全一致的段落结构和论述逻辑
2. 保持 Markdown 格式不变
3. 技术术语保留英文原文
4. 公司名称保留英文
5. 语气专业自信，符合<target_lang>的商务写作习惯
6. 署名保留英文名"""
```

---

## 八、修改指南

### 如何打磨

1. **主要关注 `profiles/prompts.yaml` 的 `resume:` 段**（本文件第三章） — 这是控制简历生成行为的核心
2. **`profiles/resume_guide.yaml`**（第四章） — 补充性的撰写指南，好坏示例在这里
3. **`profiles/me.yaml`**（第六章） — 候选人素材库，特别是 `resume_bullet_candidates` 和 `key_achievements` 中的 `resume_bullet`
4. **`profiles/resume_template.yaml`**（第五章） — 通常不需要改，除非要调整段落顺序

### 修改时的约束

- `<占位符>` 名称不能改（如 `<guide>`, `<template>`, `<base_rules>`, `<role>`, `<direction>`, `<target_lang>`, `<profile_summary>`）
- JSON 输出格式中的字段名不能改（代码依赖解析）
- 可以自由修改：角色设定、判断规则、评分标准、写作风格要求、好坏示例

### 修改后的替换流程

将修改后的内容发给我，我会：
1. 将 `resume:` 段的修改替换到 `profiles/prompts.yaml`
2. 将指南修改替换到 `profiles/resume_guide.yaml`
3. 将模板修改替换到 `profiles/resume_template.yaml`
4. 将候选人画像修改替换到 `profiles/me.yaml`
