# Jren Campus Assistant · J人校园助手

> 基于大模型的智能校园日程规划与复习安排助手 —— 计划型（J人）学生的「第二大脑」。

![Status](https://img.shields.io/badge/status-设计阶段-yellow)
![Platform](https://img.shields.io/badge/platform-Web%20%2F%20PWA-blue)
![Backend](https://img.shields.io/badge/backend-FastAPI-green)
![AI](https://img.shields.io/badge/AI-LLM%20%2B%20MCP-orange)

## 📌 项目定位

每天自动读取你的**课表、Notion 作业、Obsidian 笔记**，结合**艾宾浩斯遗忘曲线**和你自己的学习习惯，自动生成一张**合理且可执行**的时间表 —— 先给你过目确认，再写进日历。

### 一个典型的早晨

1. 🌅 早上打开网页，助手已自动读取今日课表：5 节课（3 节水课 + 2 节专业课）
2. 📚 课后，你在 Notion 提交了今天的作业，在 Obsidian 写完了课堂笔记
3. 🤖 助手自动融合新任务与笔记，结合前几天的上课记录和你的杂项安排
4. 🧠 基于艾宾浩斯遗忘曲线，评估「掌握知识 + 完成作业」所需的时间
5. 🗓️ 生成一份今日建议时间表，并询问你：「这样安排可以吗？」
6. ✅ 你确认或拖拽调整 → 写入日历 → 次日提醒执行
7. 🔄 记录实际完成情况，持续校准时间预估 —— **越用越懂你**

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 📥 多源数据自动采集 | 通过 MCP 统一读取课表（iCal）、Notion（作业/任务）、Obsidian（课堂笔记） |
| 🧠 知识点智能提取 | LLM 自动把当天笔记切分为「知识点记忆单元」并评估难度 |
| 📈 遗忘曲线复习调度 | 按课程档位（S/A/B/C，用户自设）与知识点难度自动安排复习，结合作业 deadline 反推优先级 |
| 🗓️ 时间表约束规划 | 固定课程 + 可变任务 + 可用时间片，生成不冲突的日程草案 |
| ✅ 用户确认机制 | 草案先呈现给你，批准/调整后才写入日历 |
| 🔄 习惯自适应 | 持续记录「预估 vs 实际」耗时，按课程 × 时段 × 难度自动校准后续规划 |
| 💡 主动建议 | 遗忘窗口提醒、任务过载建议拆分/延后、每日计划晨推 |

## 🧱 技术架构

```text
┌─────────────────────────────────────────────┐
│  前端：React + PWA（安卓 + 电脑双端通用）     │
├─────────────────────────────────────────────┤
│  后端：Python FastAPI                        │
│   ├─ MCP 客户端层（Notion/Obsidian/日历）    │
│   ├─ 知识提取层（LLM 抽取知识点与难度）       │
│   ├─ 遗忘曲线调度器（复习间隔算法）           │
│   ├─ 时间表规划器（约束求解 + LLM 编排）      │
│   ├─ 自适应校准模块（耗时学习与修正）         │
│   └─ 数据库：SQLite（单用户起步）            │
├─────────────────────────────────────────────┤
│  数据源：课表(iCal) | Notion(官方MCP)         │
│          | Obsidian(MCP) | 日历(CalDAV)      │
└─────────────────────────────────────────────┘
```

## 🛠️ 技术栈

| 层 | 选型 |
|----|------|
| 前端 | React + Vite + PWA |
| 后端 | Python FastAPI |
| MCP | Notion 官方 MCP Server / obsidian-mcp-server |
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

| 阶段 | 内容 | 周期 |
|------|------|------|
| **Phase 0 · 设计（当前）** | 需求梳理、架构设计、仓库初始化 | 进行中 |
| **Phase 1 · MVP** | 课表 + Notion + Obsidian 全链路：采集 → 提取 → 遗忘曲线规划 → 时间表 → 用户确认 → 写日历 | 2-4 周 |
| **Phase 2 · V2** | 习惯自适应校准、PWA 移动端优化、主动提醒 | 4-6 周 |
| **Phase 3 · V3** | 更多数据源、多用户云端部署、手机推送 | 待定 |

## 📁 目录结构

```text
jren-campus-assistant/
├── frontend/          # React + PWA 前端
├── backend/           # FastAPI 后端
│   ├── mcp_client/    # MCP 数据接入层
│   ├── extractor/     # 知识点提取
│   ├── scheduler/     # 遗忘曲线 + 时间表规划
│   ├── calibrator/    # 习惯自适应
│   └── models/        # 数据模型
├── docs/              # 设计文档
├── IDEA.md            # 想法与需求来源
└── README.md
```

## 🚀 快速开始

> ⚠️ 当前处于**设计阶段**，代码尚未开始编写，仓库已初始化完毕。

```bash
git clone https://github.com/Leo-iaa/jren-campus-assistant.git
cd jren-campus-assistant
# 安装与运行步骤将在 MVP 阶段补充
```

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
