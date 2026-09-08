# Jren Campus Assistant · J人校园助手

> 基于大模型的智能校园日程规划助手 —— 计划型（J人）学生的「第二大脑」。

![Status](https://img.shields.io/badge/status-开发中-blue)
![载体](https://img.shields.io/badge/载体-Notion%20Calendar%20%2B%20WorkBuddy-blue)
![Backend](https://img.shields.io/badge/backend-FastAPI-green)

## 项目定位

自动读取你的**课表、Notion 作业**，结合**艾宾浩斯遗忘曲线**和你的学习习惯，生成一张合理可执行的时间表——自动确认写入 Notion Calendar，按时间轴推送微信。

**一天的闭环：**

1. 🌙 **21:00** — WorkBuddy 定时任务调后端生成次日计划，自动写入 Notion Calendar
2. ☀️ **早晨** — 微信收到今日计划推送（一整天时间轴，课程与作息混排）
3. 💬 **随时** — 微信一句话：「把高数作业挪到晚上」「有新任务 XXX，ddl 明天」→ 自动调整并同步日历
4. ✅ **用得越久越准** — 记录「预估 vs 实际」耗时 + 从调整/完成行为中学习你的作息偏好

## 核心功能

- **课程档位制**：S/A/B 三档。S 档课后自动排 1 小时复习；B 档照常占日程但标注「可写 XX 作业」——水课时间不浪费
- **遗忘曲线复习**：按档位 + 知识点难度生成复习序列，每日上限顺延
- **约束规划**：固定课程 + 任务 + 复习 + 杂项，贪心求解不冲突时间表，尊重用户画像（作息屏障、脑力截止、偏好时段）
- **用户画像**：手动设置作息/固定安排，自动从「连续 3 次把高数挪到晚上」这类行为中学出偏好，可对话查看与修改
- **微信操控**：加任务、改日程、查计划，改动实时同步 Notion

## 架构

```text
WorkBuddy（调度+推送，腾讯 CodeBuddy）
├─ 定时任务 21:00 → 生成次日计划 → 推微信
├─ 定时任务 08:20 → 推今日计划
└─ 微信对话 → 调后端 MCP 工具
        │ MCP (http://127.0.0.1:28070/mcp)
        ▼
后端 FastAPI（纯 API + 12 个 MCP 工具，无定时任务）
├─ plan_generator / plan_lifecycle / plan_preview / task_intake / queries
├─ scheduler/（遗忘曲线 + 约束规划 + 画像学习，纯算法）
├─ Notion Calendar / 任务库写入（幂等同步）
└─ SQLite（全本地，13 张表）
```

**职责划分**：后端只做被动的 API + MCP 工具；所有定时触发、微信推送由 WorkBuddy 承担。

## 快速开始

```bash
git clone https://github.com/Leo-iaa/jren-campus-assistant.git
cd jren-campus-assistant/backend
pip install -r requirements.txt
cd ..
python -m backend.scripts.init_db
uvicorn backend.main:app --host 0.0.0.0 --port 28070
```

健康检查：`http://127.0.0.1:28070/health`

**WorkBuddy 接入**：MCP 连接器加 `http://127.0.0.1:28070/mcp`；微信推送装 `wechat-clawbot-push` 桥（PyPI）；再建两个定时任务（21:00 生成+推送 / 早晨推送）。详见 [docs/mcp-server.md](docs/mcp-server.md)。

## 开发约定

`main` 稳定主干，工作走 `feat/` `fix/` 分支 → PR（关联 Issue）→ rebase 合并；Conventional Commits + 语义化版本。**禁止直接推 main。**

测试：`cd backend && pytest`（292 例）。

## 文档

- [用户手册](docs/USER_GUIDE.md) · [架构设计](docs/architecture.md) · [产品愿景](docs/vision.md) · [数据库设计](docs/database.md) · [MCP 接入](docs/mcp-client.md) · [MCP Server / WorkBuddy](docs/mcp-server.md)

## 隐私

所有数据存本机 SQLite，不上传不采集；密钥自配在本地，仓库无硬编码凭据。单用户设计。
