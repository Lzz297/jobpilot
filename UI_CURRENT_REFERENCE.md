# UI 当前实现参考

> 本文档记录 Web UI 的当前实现细节（布局、样式、交互）。
> 仅供后续对照改代码使用，**不作为产品规格**。
> 产品功能规格见 `PROJECT_INTRO.md`。

---

## 一、当前布局

```
┌──────────────┬─────────────────────────────────────────┐
│  侧边栏      │           主内容区                        │
│  (280px)     │  ┌─────────────────────────────────┐    │
│              │  │  对话区                          │    │
│  Workflow    │  │  用户消息（蓝底气泡）              │    │
│  [找工作]    │  │  Agent 回复（白底气泡 + Markdown） │    │
│  [排序切换]  │  └─────────────────────────────────┘    │
│              │  ┌─────────────────────────────────┐    │
│  Current Run │  │  进度面板（终端风格，深色底）      │    │
│  [隐藏面板]  │  │  [日志输出...]                    │    │
│              │  └─────────────────────────────────┘    │
│  Actions     │  ┌─────────────────────────────────┐    │
│  [市场分析]  │  │  输入栏                          │    │
│  [简历生成▼] │  │  [输入框] [Send]                 │    │
│  · From JD   │  └─────────────────────────────────┘    │
│  · By Role   │                                         │
│  · General   │                                         │
│              │                                         │
│  Model       │                                         │
│  [下拉框]    │                                         │
│              │                                         │
│  History     │                                         │
│  [run 列表]  │                                         │
│              │                                         │
│  Files       │                                         │
│  [文件列表]  │                                         │
│              │                                         │
│  Reports     │                                         │
│  [报告列表]  │                                         │
└──────────────┴─────────────────────────────────────────┘
```

## 二、设计系统变量（CSS Custom Properties）

| 变量 | 当前值 | 用途 |
|------|--------|------|
| `--sidebar-bg` | `#0f172a` | 侧边栏背景 |
| `--sidebar-text` | `#94a3b8` | 侧边栏文字 |
| `--sidebar-heading` | `#e2e8f0` | 侧边栏标题 |
| `--sidebar-hover` | `rgba(255,255,255,0.06)` | 侧边栏悬停 |
| `--sidebar-active` | `#3b82f6` | 侧边栏激活态 |
| `--main-bg` | `#f8fafc` | 主内容区背景 |
| `--chat-bg` | `#ffffff` | 对话区背景 |
| `--user-bubble` | `#3b82f6` | 用户气泡 |
| `--user-text` | `#ffffff` | 用户气泡文字 |
| `--agent-bubble` | `#ffffff` | Agent 气泡 |
| `--agent-text` | `#0f172a` | Agent 气泡文字 |
| `--progress-bg` | `#0f172a` | 进度面板背景 |
| `--progress-text` | `#94a3b8` | 进度面板文字 |
| `--border-subtle` | `rgba(226,232,240,0.6)` | 微边框 |
| `--border` | `#e2e8f0` | 标准边框 |
| `--accent` | `#3b82f6` | 主色调 |
| `--accent-hover` | `#2563eb` | 主色调悬停 |
| `--success` | `#22c55e` | 成功色 |
| `--warning` | `#f59e0b` | 警告色 |
| `--error` | `#ef4444` | 错误色 |
| `--ring` | `rgba(59,130,246,0.2)` | 焦点环 |

## 三、当前交互组件

### 3.1 侧边栏区域

| 区域 | 当前实现 |
|------|----------|
| **Header** | "JobsDB Agent" 标题 + 状态指示点 + Model 下拉框 |
| **Workflow** | "Find & Match Jobs" 按钮（触发 `/api/pipeline` search_match）+ 排序切换（radio：按日期 / 按相关度） |
| **Current Run** | 隐藏面板（初始 `hidden`），显示当前活跃 run 的时间和岗位统计 |
| **Actions** | "Market Analysis..." 按钮 → 弹出 modal 输入参数；可折叠的 "Generate Resume" 分组（展开 3 个子按钮） |
| **History** | `/api/runs` 获取历史 run 列表，当前 run 高亮，点击查看文件 |
| **Files** | 浏览 `/api/files` 文件列表，点击下载 |
| **Reports** | 浏览 `/api/market/files` 报告列表，点击下载 |

### 3.2 Modal 弹窗

- **Market Analysis** modal：输入 job_category / location / classification / include_gap_analysis 等参数
- **JD Modal**：粘贴 JD 文本 → 生成简历
- **Role Modal**：输入岗位方向 → 生成简历

### 3.3 进度面板

- 终端风格（黑底绿字），显示 `emit()` 所有输出
- SSE 实时流，自动滚动到底部

### 3.4 对话区

- 用户气泡：蓝底白字，右对齐
- Agent 气泡：白底深字，左对齐，带边框
- Agent 回复中的 Markdown 做格式化渲染

### 3.5 文件下载

- `/download/<path>` 端点，路径相对于 `output/` 目录

## 四、SSE 事件格式

当前后端产生的 SSE 事件类型：

| type | 当前 payload |
|------|-------------|
| `progress` | `{"type": "progress", "text": "..."}` |
| `status` | `{"type": "status", "text": "..."}` |
| `tool_call` | `{"type": "tool_call", "tool": "...", "args": "..."}` |
| `done` | `{"type": "done", "reply": "...", "files": [["path", "desc"], ...]}` |
| `error` | `{"type": "error", "text": "..."}` |
| `ping` | `{"type": "ping"}` — 30 秒心跳 |

## 五、PDF 样式（简历 & 报告）

### 简历 CSS (RESUME_CSS)

- 字体：Arial → Calibri → Microsoft JhengHei → PingFang HK → PingFang SC → SimHei → sans-serif
- 字号：正文 10.5pt，h1 22pt，h2 12pt
- h2：全大写 + `letter-spacing: 0.5px` + `border-bottom: 1.5px solid #333`
- @page margin: 2cm；实际渲染 margin: top 1.5cm / right 2cm / bottom 1.5cm / left 2cm

### 报告 CSS (REPORT_CSS)

- h1/h2 颜色：`#1a5276`
- 表格：`tr:nth-child(even) { background: #fafbfc }` + 边框 `#ddd`
- @page margin: 2cm；实际渲染 margin: 2cm 四边统一

## 六、当前 API 端点（Server 侧）

| 路由 | 方法 | 当前实现 |
|------|------|----------|
| `/` | GET | `send_from_directory("static", "index.html")` |
| `/api/session` | POST | 创建 sid（8 位 UUID），session 含 messages / queue / busy |
| `/api/chat` | POST | body: `{sid, message}` → 后台线程执行 `_run_agent_turn()` |
| `/api/pipeline` | POST | body: `{sid, action, sort_by?}` → 后台线程执行 `_run_pipeline()` |
| `/stream/<sid>` | GET | SSE 事件流，30 秒 ping 心跳 |
| `/api/runs` | GET | 返回 run 列表（id, path, time, stage, job_count, match_count, is_current） |
| `/api/runs/<id>/files` | GET | 递归遍历 run 目录，返回文件列表 |
| `/api/files` | GET | 递归遍历 output/ 目录，返回所有文件 |
| `/api/market/files` | GET | 列出 output/market/ 下文件（不递归） |
| `/api/config/model` | GET | 返回 `{current_provider, current_model, presets}` |
| `/api/config/model` | POST | body: `{provider, model?}` → 立即生效 + 回写 YAML |
| `/download/<path>` | GET | `send_from_directory("output", path)` |
