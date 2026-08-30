# Jren Campus Assistant · J人校园助手

> 基于大模型的智能校园日程规划与复习安排助手 —— 计划型（J人）学生的「第二大脑」。

![Status](https://img.shields.io/badge/status-开发中-blue)
![载体](https://img.shields.io/badge/载体-Notion%20Calendar%20%2B%20WorkBuddy-blue)
![Backend](https://img.shields.io/badge/backend-FastAPI-green)
![AI](https://img.shields.io/badge/AI-LLM%20%2B%20MCP-orange)

> 📘 **新手从这里开始**：请先阅读[用户使用手册（docs/USER_GUIDE.md）](docs/USER_GUIDE.md) —— 从克隆到 WorkBuddy 联调的全流程操作指南。

## 📌 项目定位

每天自动读取你的**课表、Notion 作业、Obsidian 笔记**，结合**艾宾浩斯遗忘曲线**和你自己的学习习惯，自动生成一张**合理且可执行**的时间表 —— 自动确认，直接写进日历，微信推送给你。

### 一天的典型闭环

1. 🌙 **前一晚 21:00**：WorkBuddy 定时任务触发后端，自动读取当日数据（课表 / 新作业 / 新笔记），生成「明日计划」并**自动确认写入 Notion Calendar**
2. 🗓️ **计划已写入 Notion Calendar**（原生日历，手机 / 电脑 / 平板三端同步）
3. ☀️ **08:00**：微信收到「今日计划」推送（WorkBuddy 定时任务 + wechat-clawbot-push 直推微信），含完整时间轴
4. 💬 **临时改动 / 加任务？** 直接在微信里说：「把高数作业挪到晚上」「有新任务：XXX，ddl 是明天」→ 自动调整/添加，改动同步回 Notion 日历
5. ✅ 完成情况自动记录 → 持续校准时间预估 —— **越用越懂你**

> 想回到「先确认再写入」模式？给 `generate_tomorrow_plan` 传 `auto_confirm=false` 即可（默认行为）。

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 📥 多源数据自动采集 | 通过 MCP 统一读取课表（iCal）、Notion（作业/任务）、Obsidian（课堂笔记）、COROS（跑步数据） |
| 💬 微信一句话加任务 | 对 WorkBuddy 说「有新任务：XXX，ddl 是 YYY，类型是 ZZZ」→ 自动写本地 + Notion 任务库并排进日程（`add_task` 工具，Issue #55） |
| 🧠 知识点智能提取 | LLM 自动把当天笔记切分为「知识点记忆单元」并评估难度 |
| 📈 遗忘曲线复习调度 | 按课程档位（S/A/B/C，用户自设）与知识点难度自动安排复习，结合作业 deadline 反推优先级 |
| 🗓️ 时间表约束规划 | 固定课程 + 可变任务 + 可用时间片，生成不冲突的日程草案 |
| ✅ 计划自动确认 | 21:00 自动生成次日计划并确认写入 Notion Calendar（`auto_confirm`，Issue #58）；也可改回手动确认模式 |
| 🔄 习惯自适应 | 持续记录「预估 vs 实际」耗时，按课程 × 时段 × 难度自动校准后续规划 |
| 🧑 用户画像 | 记录作息 / 效率偏好 / 生活规律；从调整、完成、新增任务的行为中自动学习（如「连续 3 次把高数挪到晚上 → 高数优先排晚上」），规划时按画像智能安排，可对话查看/修改（Issue #63） |
| 🏃 跑步训练计划 | 接入高驰 COROS 官方 MCP，读真实跑步数据（跑量 / 配速 / 恢复 / 负荷），按周生成可执行的训练计划（轻松跑 / 间歇 / 长距离），尊重恢复信号、跑量增幅 ≤10%，训练块自动排进日程不与课程冲突（Issue #65） |
| 💡 主动建议 | 遗忘窗口提醒、任务过载建议拆分/延后、每日计划晨推 |

## 🧱 技术架构

```text
┌─────────────────────────────────────────────────┐
│  载体层（替代自建前端，双载体）                    │
│  ├─ 日程展示：Notion Calendar（原生 App，三端同步）│
│  └─ AI 交互：WorkBuddy + 微信（对话确认/调整/查询）    │
├─────────────────────────────────────────────────┤
│  后端：Python FastAPI                            │
│  ├─ MCP Server 暴露层（对接 WorkBuddy，13 个工具）     │
│  ├─ MCP 客户端层（Notion/Obsidian/iCal/COROS）         │
│  ├─ 知识提取层（LLM 抽取知识点与难度）            │
│  ├─ 遗忘曲线调度器（复习间隔算法）                │
│  ├─ 时间表规划器（约束求解 + LLM 编排）           │
│  ├─ 自适应校准模块（耗时学习与修正）              │
│  ├─ 用户画像模块（习惯记录 + 行为自动学习）       │
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
| AI 载体 | WorkBuddy（腾讯 CodeBuddy：MCP + 定时任务 + 微信/企微/QQ/飞书/钉钉远程；免费额度以官方为准） |
| 后端 | Python FastAPI |
| MCP | 客户端：Notion 官方 MCP Server / obsidian-mcp-server；服务端：MCP 暴露层（对接 WorkBuddy） |
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
| **Phase 1 · 核心** | 后端 13 表模型 / CRUD API / 调度算法 / MCP 接入 / 290 例测试 | ✅ 已完成 |
| **Phase 1.5 · 载体集成** | MCP Server 暴露层 / WorkBuddy 对接 / Notion Calendar 写入 / 21:00 定时任务 | ✅ 已完成 |
| **Phase 2 · 自适应** | 校准数据回流、提醒完善、云端部署准备 | ⏳ 待启动 |
| **Phase 3 · 扩展** | 多用户、手机推送、更多数据源 | ⏳ 待定 |

## 📁 目录结构

```text
jren-campus-assistant/
├── backend/           # FastAPI 后端
│   ├── api/           # 路由层：健康检查 + 基础 CRUD + 数据源同步/OAuth
│   ├── models/        # SQLAlchemy 数据模型（13 张表）
│   ├── schemas/       # Pydantic 请求/响应模型（校验与枚举）
│   ├── scheduler/     # 遗忘曲线 + 时间表规划 + 习惯校准 + 用户画像学习（已实现）
│   ├── mcp_client/    # MCP 数据接入层（Notion / Obsidian / iCal / COROS adapter）
│   ├── mcp_server/    # MCP Server 暴露层（WorkBuddy 接入：13 工具 + 定时任务 + Notion 日历/任务库写入 + 用户画像）
│   ├── scripts/       # 工具脚本（init_db.py 数据库初始化）
│   ├── tests/         # pytest 测试（321 例）
│   └── data/          # SQLite 数据库文件（运行时生成，不入库）
├── docs/              # 设计文档
└── README.md
```

## 🔒 隐私与数据

- **数据全本地**：所有数据（课表、计划、复习记录、习惯校准、用户画像）存放在你自己机器上的 SQLite 文件（`backend/data/`），不入库、不上传、不采集
- **密钥自配**：Notion 集成令牌等凭据通过本地脚本（`backend/scripts/config_notion.bat`）配置，只保存在你本机，代码仓库中不含任何硬编码密钥
- **部署者须知**：请勿将 `.env`、数据库文件、日志提交到任何仓库；公开仓库中的令牌/密钥一经发布即视为泄露
- 项目为**单用户设计**，数据互不可见；多用户支持见 [开发路线](#-开发路线) Phase 3

## 🚀 快速开始

### 后端

> 环境要求：Python 3.11+。

```bash
git clone https://github.com/Leo-iaa/jren-campus-assistant.git
cd jren-campus-assistant/backend

# 1. 创建虚拟环境并安装依赖
python -m venv .venv
# 激活：PowerShell → .\.venv\Scripts\Activate.ps1（若被拦截先执行 Set-ExecutionPolicy -Scope CurrentUser RemoteSigned）
#      CMD → .venv\Scripts\activate    macOS/Linux → source .venv/bin/activate
pip install -r requirements.txt

# 2. 初始化数据库（生成 backend/data/jren.db，幂等可重复执行）
# 回到仓库根目录执行：
cd ..
python -m backend.scripts.init_db

# 3. 启动后端服务
uvicorn backend.main:app --reload
# 打开 http://127.0.0.1:8001/docs 查看接口文档（Swagger UI）

# 4. 运行测试
cd backend
python -m pytest
```

健康检查：`curl http://127.0.0.1:8001/health` → `{"status":"ok","database":"connected"}`

**Windows 开机自启**（可选）：复制 `backend/scripts/start_backend_hidden.vbs` 到系统启动文件夹
（`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`），登录后服务自动后台启动；
自查：浏览器开 `http://127.0.0.1:8001/health`。详见 [docs/mcp-server.md](docs/mcp-server.md) 2.1 节。

### WorkBuddy 集成

> ✅ 后端 MCP Server 暴露层已实现（`backend/mcp_server/`，11 个工具，含 add_task / auto_confirm / get_user_profile），
> 完整配置见 [docs/mcp-server.md](docs/mcp-server.md)。

1. 启动后端：`uvicorn backend.main:app --host 0.0.0.0 --port 8001`
2. WorkBuddy（设置 → MCP 服务）添加 MCP Server：类型 **http**，地址 `http://127.0.0.1:8001/mcp`（同机部署）
3. **微信推送（实测方案）**：安装 `wechat-clawbot-push` 桥（PyPI，stdio MCP，暴露 `push_wechat_message`），
   授权 token 后即可把自动化任务结果直推微信 ClawBot 聊天框（详见 [docs/mcp-server.md](docs/mcp-server.md) 5.1 节）
4. WorkBuddy 配置两个「自动化」定时任务（均已实测跑通）：
   - 每天 **21:00** → `generate_tomorrow_plan`（`auto_confirm=true` 自动确认写日历）→ `push_wechat_message` 推完整预览
   - 每天 **08:00** → `get_today_plan_preview` → `push_wechat_message` 推今日时间轴
5. 后端 APScheduler 21:00 自动生成次日计划兜底（WorkBuddy 未触发也能跑；兜底为草案，不自动确认）
6. 手机微信远程操控：一句话加任务 / 改日程（`add_task` / `adjust_plan_item`，改动自动同步 Notion 日历）

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
- [MCP Server 暴露层使用说明（WorkBuddy 接入）](docs/mcp-server.md)
