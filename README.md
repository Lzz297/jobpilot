# JobsDB Agent

面向香港 JobsDB 市场的 AI 求职助手。从搜索岗位到生成定制简历一条龙，接入多个 LLM Provider，在终端和浏览器里都能用。

![Python](https://img.shields.io/badge/python-3.13-blue)
![Flask](https://img.shields.io/badge/flask-3.x-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

## 做什么

自动完成求职流程里的四个环节：**搜 → 评 → 写 → 查**

- **搜** — Playwright 无头浏览器爬 JobsDB，三层漏斗过滤，全量抓取 JD 原文
- **评** — LLM 从技能、经验、职级、行业、加分项五个维度评分，结合动态权重和及格线复评
- **写** — 英文简历先行，审查不过自动重写，再翻译为繁中/简中，一次出 7 个文件（简历 + Cover Letter × 三语 + 审查报告）
- **查** — 对生成的每一条 bullet 做事实核查，检测数字矛盾、强度升级、空来源等 7 类问题，支持定点修正

另外还有一个独立的**市场调研模块**，指定岗位类别（如 "Java Developer"、"Web3"）就能出一份 11 维度的市场分析报告，含技能排名、薪资分布、个人差距分析和可执行的学习路径。

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
pip install -r requirements.txt  # 或根据 pyproject.toml
playwright install chromium

# 2. 配置 API Key — 在 .env 里填入你要用的 Provider
echo "DEEPSEEK_API_KEY=sk-xxx" > .env

# 3. 启动 Web UI
python web_app.py
# 浏览器打开 http://127.0.0.1:5000

# 4. 或者走终端模式（需要先创建 Campaign）
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

## 开发中

**RAG 增强匹配** — 给方向分类和匹配评分加上向量检索。思路是把历史 JD 先走一遍 LLM 结构化提取，按技能、业务领域、经验级别拆开写入向量库；对新 JD 做多路检索，用 RRF 融合再用 Reranker 精排，把相似历史记录作为动态 few-shot 喂给评分链路。

目前向量库和检索管线还在打磨，效果稳定到 90% 以上后会放出来。

## 许可证

MIT
