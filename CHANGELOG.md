# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- 项目初始化：README、架构设计文档（`docs/architecture.md`）、`.gitignore`（#1）
- 产品愿景与需求文档 `docs/vision.md`
- MIT 开源许可证
- 开发流程约定（分支 / 提交信息 / PR 规范）
- 产品设计定稿：课程档位制（S/A/B/C）复习策略、界面方案、流程时间轴（#3）
- 数据库设计文档 `docs/database.md`（11 表结构 + DDL + 设计决策，#5）
- Phase 1 后端核心（#7）：
  - SQLAlchemy 数据模型（11 张表，对齐 `docs/database.md` DDL，含 CHECK/UNIQUE 约束与外键级联）
  - FastAPI 应用骨架：pydantic-settings 配置管理、CORS、健康检查 `GET /health`
  - 基础 CRUD API：课程（含 tier 档位）/ 课程时间块 / 知识点 / 复习计划 / 任务 / 杂事项 / 数据源
  - `backend/scheduler/` 模块占位与接口签名（遗忘曲线调度 / 时间表规划 / 习惯校准，算法待实现）
  - SQLite 初始化脚本 `scripts/init_db.py`（幂等建表 + 默认设置）
  - pytest 测试 63 例全部通过（模型约束与级联 + CRUD 接口）
- 算法模块（#9）：
  - 遗忘曲线调度器 `backend/scheduler/review.py`：S/A/B/C 档位复习序列、难度微调（≥4 首次提前至课后 2 小时 / ≤2 跳过当晚 / S 档难度≥4 额外一次）、每日复习上限顺延次日、跳过/逾期状态流转
  - 时间表规划器 `backend/scheduler/planner.py`：确定性贪心约束求解，B/C 档释放时段（`release_slot`）可安排其他任务、学习时段偏好、保证 `UNIQUE(date, start_time)`、放不下的项目进入 dropped 报告
  - 自适应校准模块 `backend/scheduler/calibration.py`：按 课程 × 时段 × 难度 分桶统计「预估 vs 实际」，输出修正系数 factor；snapshot/load 可对接 `calibration_stats` 表
  - 调度器接口契约扩展（`ReviewDraft.ref_id` / `PlanItemDraft.release_slot`，向后兼容）
  - pytest 单元测试 60 例全部通过（全量 123 例，无回归）
- MCP 数据接入层（#11）：
  - `backend/mcp_client/` 包：JSON-RPC 2.0 传输层（stdio 子进程 / streamable HTTP + session 管理）、OAuth 2.0 授权码 + PKCE 客户端（端点/凭据全部可配置，测试全 mock）
  - iCal adapter：解析教务系统导出 .ics（TZID=Asia/Shanghai、RRULE WEEKLY、同课程多 VEVENT 去重合并、DESCRIPTION 教室/教师兜底）→ `courses` + `course_sessions`；同步默认 merge 不覆盖手改字段，overwrite 模式全量覆盖，删除仍走手动 CRUD（手动维护兜底）
  - Notion adapter：对接官方远程 MCP Server（mcp.notion.com/mcp），OAuth 起点/回调端点 + token 自动刷新；`query_database` → `tasks`（source='notion'，按 source_ref 幂等 upsert，属性名可配置，状态归一化）
  - Obsidian adapter：obsidian-mcp-server（stdio）读 vault + 全文搜索；`vault_path` 直读兜底（不依赖 MCP 服务器）；只做查询接口，不落库
  - data_sources API 增强：`POST /{id}/sync`（同步 + 更新 last_sync_at）、`POST /{id}/enable|disable`、`POST /notion/oauth/start|callback`
  - 使用说明 `docs/mcp-client.md`；pytest 测试 50 例全部通过（全量 173 例，无回归）

[#1]: https://github.com/Leo-iaa/jren-campus-assistant/issues/1
[#7]: https://github.com/Leo-iaa/jren-campus-assistant/issues/7
[#9]: https://github.com/Leo-iaa/jren-campus-assistant/issues/9
[#11]: https://github.com/Leo-iaa/jren-campus-assistant/issues/11
