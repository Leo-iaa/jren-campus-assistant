# Jren Campus Assistant · J人校园助手

> 基于大模型的智能校园日程规划与复习安排助手 —— 计划型（J人）学生的「第二大脑」。

![Status](https://img.shields.io/badge/status-开发中-blue)
![载体](https://img.shields.io/badge/载体-Notion%20Calendar%20%2B%20QClaw-blue)
![Backend](https://img.shields.io/badge/backend-FastAPI-green)
![AI](https://img.shields.io/badge/AI-LLM%20%2B%20MCP-orange)

## 📌 项目定位

每天自动读取你的**课表、Notion 作业、Obsidian 笔记**，结合**艾宾浩斯遗忘曲线**和你自己的学习习惯，自动生成一张**合理且可执行**的时间表 —— 先给你过目确认，再写进日历。

### 一天的典型闭环

1. 🌙 **前一晚 21:00**：QClaw 定时任务触发后端，自动读取当日数据（课表 / 新作业 / 新笔记），生成「明日计划」
2. 🗓️ **计划写入 Notion Calendar**（原生日历，手机 / 电脑 / 平板三端同步）
3. ☀️ **08:00**：微信收到「今日计划」推送（QClaw 定时任务），Notion Calendar 事件提醒双保险
4. 💬 **想调整？** 直接在 QClaw / 微信里说：「把高数作业挪到晚上」「确认今天的计划」
5. ✅ 确认后计划生效 → 完成情况自动记录 → 持续校准时间预估 —— **越用越懂你**

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 📥 多源数据自动采集 | 通过 MCP 统一读取课表（iCal）、Notion（作业/任务）、Obsidian（课堂笔记） |
| 🧠 知识点智能提取 | LLM 自动把当天笔记切分为「知识点记忆单元」并评估难度 |
| 📈 遗忘曲线复习调度 | 按课程档位（S/A/B/C，用户自设）与知识点难度自动安排复习，结合作业 deadline 反推优先级 |
| 🗓️ 时间表约束规划 | 固定课程 + 可变任务 + 可用时间片，生成不冲突的日程草案 |
| ✅ 用户确认机制 | 草案先呈现给你（Notion Calendar + QClaw 对话），批准/调整后才写入日历 |
| 🔄 习惯自适应 | 持续记录「预估 vs 实际」耗时，按课程 × 时段 × 难度自动校准后续规划 |
| 💡 主动建议 | 遗忘窗口提醒、任务过载建议拆分/延后、每日计划晨推 |

## 🧱 技术架构

```text
┌─────────────────────────────────────────────────┐
│  载体层（替代自建前端，双载体）                    │
│  ├─ 日程展示：Notion Calendar（原生 App，三端同步）│
│  └─ AI 交互：QClaw + 微信（对话确认/调整/查询）    │
├─────────────────────────────────────────────────┤
│  后端：Python FastAPI                            │
│  ├─ MCP Server 暴露层（对接 QClaw，🆕 开发中）    │
│  ├─ MCP 客户端层（Notion/Obsidian/iCal）         │
│  ├─ 知识提取层（LLM 抽取知识点与难度）            │
│  ├─ 遗忘曲线调度器（复习间隔算法）                │
│  ├─ 时间表规划器（约束求解 + LLM 编排）           │
│  ├─ 自适应校准模块（耗时学习与修正）              │
│  ├─ 定时任务（21:00 生成+08:00 微信推送）        │
│  └─ 数据库：SQLite（单用户起步）                 │
├─────────────────────────────────────────────────┤
│  数据源：课表(iCal) | Notion(官方MCP)            │
│          | Obsidian(MCP) | Notion Calendar(写入) │
└─────────────────────────────────────────────────┘
```

## 🛠️ 技术栈

| 层 | 选型 |
|----|------|
| 日程载体 | Notion Calendar（原生 App：事件写入、提醒、三端同步） |
| AI 载体 | QClaw（腾讯：MCP + 定时任务 + 微信远程；免费额度约 800 积分/天） |
| 前端（可选） | React + Vite + PWA（已实现，作为备用界面保留） |
| 后端 | Python FastAPI |
| MCP | 客户端：Notion 官方 MCP Server / obsidian-mcp-server；服务端：MCP 暴露层（对接 QClaw） |
| 调度算法 | 遗忘曲线 + 约束规划（自研） |
| 数据库 | SQLite → PostgreSQL（多用户时） |
| LLM | 可配置（豆包 / DeepSeek / 扣子系等） |

## ✅ 可行性分析

这个想法**技术上完全可行**，核心依据：

- **MCP 生态已成熟**：Notion 官方 MCP Server、obsidian-mcp-server 均已可用，数据接入成本低
- **「LLM 抽取 + 约束求解」是成熟组合**：LLM 负责理解语义（切分知识点、评估难度），确定性算法保证时间表可执行
- **遗忘曲线可参数化**：初始使用标准曲线，后续用个人数据校准 —— 这正是「习惯自适应」模块的职责

主要风险与对策：

| 风险 | 对策 |
|------|------|
| 遗忘曲线对个人未必完全适用 | 自适应校准模块持续修正复习间隔 |
| 课表依赖教务系统 iCal 导出 | 提供手动维护兜底方案 |
| LLM 抽取结果不稳定 | 规则兜底（按标题/章节切分） |

> 完整的设计思路见 [docs/architecture.md](docs/architecture.md)。

## 🗺️ 开发路线

| 阶段 | 内容 | 状态 |
|------|------|------|
| **Phase 0 · 设计** | 需求、架构、数据库设计 | ✅ 已完成 |
| **Phase 1 · 核心** | 后端 11 表模型 / CRUD API / 调度算法 / MCP 接入 / 173 例测试；前端三页面（备用） | ✅ 已完成 |
| **Phase 1.5 · 载体集成（当前）** | MCP Server 暴露层 / QClaw 对接 / Notion Calendar 写入 / 定时任务 | 🔨 进行中 |
| **Phase 2 · 自适应** | 校准数据回流、提醒完善、云端部署准备 | ⏳ 待启动 |
| **Phase 3 · 扩展** | 多用户、手机推送、更多数据源 | ⏳ 待定 |

## 📁 目录结构

```text
jren-campus-assistant/
├── frontend/          # React + Vite + TS + PWA（备用界面，非主交互路径）
├── backend/           # FastAPI 后端
│   ├── api/           # 路由层：健康检查 + 基础 CRUD + 数据源同步/OAuth
│   ├── models/        # SQLAlchemy 数据模型（11 张表）
│   ├── schemas/       # Pydantic 请求/响应模型（校验与枚举）
│   ├── scheduler/     # 遗忘曲线 + 时间表规划 + 习惯校准（已实现）
│   ├── mcp_client/    # MCP 数据接入层（Notion / Obsidian / iCal adapter）
│   ├── scripts/       # 工具脚本（init_db.py 数据库初始化）
│   ├── tests/         # pytest 测试（173 例）
│   └── data/          # SQLite 数据库文件（运行时生成，不入库）
├── docs/              # 设计文档
└── README.md
```

## 🚀 快速开始

### 后端

> 环境要求：Python 3.11+。

```bash
git clone https://github.com/Leo-iaa/jren-campus-assistant.git
cd jren-campus-assistant/backend

# 1. 创建虚拟环境并安装依赖
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 2. 初始化数据库（生成 backend/data/jren.db，幂等可重复执行）
# 回到仓库根目录执行：
cd ..
python -m backend.scripts.init_db

# 3. 启动后端服务
uvicorn backend.main:app --reload
# 打开 http://127.0.0.1:8000/docs 查看接口文档（Swagger UI）

# 4. 运行测试
cd backend
python -m pytest
```

健康检查：`curl http://127.0.0.1:8000/health` → `{"status":"ok","database":"connected"}`

### QClaw 集成（规划中）

> ⚠️ 后端 MCP Server 暴露层尚未实现，以下为规划步骤，实现后补充具体配置。

1. 后端启动 MCP Server（Streamable HTTP 模式）
2. QClaw 中添加 MCP Server：地址 `http://<电脑局域网IP>:8000/mcp`
3. QClaw 配置定时任务：每天 21:00 →「生成明天的计划」；每天 08:00 →「推送今日计划预览到微信」
4. 手机微信远程操控 QClaw，对话式确认 / 调整计划（微信通道双向能力以实测为准）

### 前端（可选）

> 环境要求：Node.js 18+。当前为备用界面，主交互路径走 Notion Calendar + QClaw。

```bash
cd frontend
npm install
npm run dev        # 打开 http://localhost:5173（需后端已启动）
npm run build      # 生产构建（PWA 可安装）
npm run test       # 组件与纯函数测试
```

> 详细说明见 [frontend/README.md](frontend/README.md)。

## 🛠️ 开发流程约定

本仓库模拟真实工程协作流程，遵循以下约定：

| 环节 | 约定 |
|------|------|
| 分支模型 | `main` 为稳定主干；新工作从 `main` 切出 `feat/`、`fix/`、`docs/`、`chore/` 分支 |
| 提交信息 | [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：`<type>(<scope>): <描述>` |
| 变更合并 | 通过 Pull Request 合并，PR 描述中关联 Issue（`Closes #xx`） |
| 版本管理 | [语义化版本](https://semver.org/lang/zh-CN/) + Changelog 记录 |

> 💡 禁止直接向 `main` 推送提交 —— 即使是一个人开发，也要养成「分支 → PR → 合并」的习惯。

## 📄 文档

- [架构设计文档](docs/architecture.md)
- [产品愿景与需求](docs/vision.md)
- [数据库设计](docs/database.md)
- [MCP 数据接入层使用说明](docs/mcp-client.md)
