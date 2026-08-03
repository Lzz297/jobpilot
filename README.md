# JobPilot

面向香港 JobsDB 市场的 AI 求职助手。从搜索岗位到生成定制简历一条龙，接入多个 LLM Provider，在终端和浏览器里都能用。

![Python](https://img.shields.io/badge/python-3.13-blue)
![Flask](https://img.shields.io/badge/flask-3.x-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

## 核心功能

整条求职流程拆成四个环节：**搜 → 评 → 写 → 查**，外加一个独立的**市场调研模块**。

**搜** — 基于 Playwright 无头浏览器抓取 JobsDB 岗位信息，经过规则过滤和全量 JD 抓取，保留完整职位描述上下文。同时集成 Tesseract OCR，支持从截图或 PDF 中提取 JD 文本，扩大了信息来源范围。

**评** — 拿到 JD 后由 LLM 做岗位方向分类，再从技能匹配度、经验匹配度、职级匹配度、行业匹配度和加分项五个维度打分。评分过程会根据方向自动选权重方案，边缘分数的岗位会触发第二轮复评，取两轮平均并标注置信度。

**写** — 支持三种简历生成模式：按方向聚合（批量投递）、指定匹配岗位、直接粘贴 JD。用户可以在 Web UI 里选择需要输出的语言（英文 / 繁中 / 简中），按需组合，比如只出英文版，或者英文 + 繁中两份。每份简历生成后会先做质量审查，不达标的自动修正后再定稿。

**查** — 简历定稿后逐条 bullet 做事实核查，检查数字矛盾、强度升级、空来源引用、占位符残留等 7 类问题。查到问题可以在界面上逐条确认或定点修正，修正结果会重新过一遍检查。

**市场调研** — 跟找工作的主流程独立。输入一个岗位类别（比如 "Java Developer"、"Web3"），系统会主动搜索 JobsDB 并从技能需求、薪资分布、经验要求、行业分布、语言门槛、面试线索等 11 个维度出一份分析报告，附带跟个人画像的差距分析和可执行的学习路径。

## 技术栈

| 层 | 用了什么 |
|---|---------|
| 语言 | Python 3.13 |
| 前端 | 原生 HTML/CSS/JS 单页应用，Tailwind CSS（CDN） |
| 后端 | Flask + SSE 实时推送 |
| LLM | DeepSeek / Qwen / GLM 可切换，OpenAI SDK 兼容接口 |
| 结构化输出 | Instructor + Pydantic（8 个主路径） |
| 网页抓取 | Playwright 无头浏览器，4 层解析回退 |
| OCR | Tesseract，支持截图和 PDF 导入 JD |
| PDF 渲染 | Playwright Chromium，Markdown → HTML → A4 PDF |
| 存储 | SQLite（画像、Campaign、策略、系统配置） |
| 可观测 | LangSmith 追踪全部 LLM 调用 |

## 架构

```
入口层:   agent.py (终端 CLI)   /   web_app.py (Flask Web + SSE)

         ┌──────────────────────────────────────┐
         │            llm_call()                │
         │  24 处 LLM 调用点收敛到一个入口       │
         │  内建指数退避重试/错误分类/Provider 切换│
         └──────────────────────────────────────┘
                          │
         ┌────────────────┼────────────────┐
    scraper.py       job_match.py     resume_gen.py
    (采集+清洗)       (五维评分)        (三语简历)
                          │
                    market_analysis.py
                    (独立市场调研)
```

## 快速开始

```bash
# 1. 安装依赖
pip install -e .                    # 根据 pyproject.toml 装全部依赖
playwright install chromium

# 2. 初始化数据库（建表 + 默认 admin 用户）
python data/migrate.py

# 3. 配置 API Key — 在 .env 里填入你要用的 Provider
echo "DEEPSEEK_API_KEY=sk-xxx" > .env

# 4. 启动 Web UI
python web_app.py
# 浏览器打开 http://127.0.0.1:5000
# 首次登录：用户名 admin，密码 admin123

# 5. 或者走终端模式（先在 Web UI 里创建 Campaign）
python agent.py --campaign web3_hunt
```

详细的配置说明见 [CONFIG_GUIDE.md](CONFIG_GUIDE.md)。

## 项目结构

```
├── agent.py              # 终端 CLI 入口
├── web_app.py            # Flask Web UI — 50+ 个 API 端点
├── config.py             # llm_call() 统一入口 + 并发编排 + Token 追踪
├── scraper.py            # JobsDB 爬虫 — 列表页 4 层解析 + 详情页 3 层解析
├── job_search.py         # 三层漏斗搜索
├── job_match.py          # 五维匹配评分 + 方向分类 + 及格线复评
├── resume_gen.py         # 3 种模式 × 三语 × 质量自检
├── checker.py            # 简历 bullet 逐条事实核查
├── ocr_utils.py          # Tesseract OCR + 图片预处理管道
├── pdf_renderer.py       # Markdown → HTML → PDF
├── market_analysis.py    # 四阶段市场调研 + 差距分析
├── tools_defs.py         # 14 个工具的 JSON Schema 注册 + 分发
├── engine/contracts/     # Pydantic 数据模型（11 个）
├── evaluation/           # 评估系统 — 方向准确率 + 混淆矩阵 + 回归对比
├── static/index.html     # Web UI 前端
├── profiles/             # YAML 模板（简历模板 + 简历撰写指南）
├── prompts/examples/     # Few-shot 示例（方向分类）
└── data/                 # SQLite 数据库 + Tesseract 语言包
```

## 持续调优

RAG 增强匹配的管线已经跑通——历史 JD 入库时走 LLM 结构化提取，按技能、业务领域、经验级别拆分写入向量库；新 JD 进来后多路检索、RRF 融合、Reranker 重排，把相似记录用作方向判断和评分的动态 few-shot。

现在主要精力放在持续收集更多 JD 数据上。因为向量库的质量直接取决于样本量，数据越丰富检索结果越稳定。目前持续跑评估跟踪效果，目标是方向识别准确率稳定在 90% 以上。这部分会随着数据积累逐步更新。

## 许可证

MIT
