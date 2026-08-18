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
- 载体方案切换：Notion Calendar（日程）+ QClaw（AI 交互），README / vision / architecture 同步更新（#16）
- 提醒通道定稿（方案 A）：QClaw 微信推送为主 + Notion Calendar 提醒双保险（#18）
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
- 前端三页面（#13）：
  - React + Vite + TypeScript + PWA（vite-plugin-pwa，可添加到安卓主屏幕；中文界面、简洁卡片风、移动优先）
  - 今日计划页：AI 计划确认横幅（✅ 确认 / 撤销）+ 时间轴（课程 / 作业 / 复习 / 自由时间，复习点标注 🔁 与第几次，HTML5 拖拽调整），计划 = 前端聚合（简易确定性规划：固定课程 → 空闲块填空 → 任务优先于复习）
  - 周视图：7 天网格（课程 + 任务 + 复习点），今天高亮；窄屏自动降级为列表
  - 设置页：数据源绑定（Notion OAuth 回调 / Obsidian / iCal，含同步/启停/解绑）、课程档位管理（S/A/B/C + 复习序列展示）、偏好设置（每日复习上限、学习时段）、LLM 配置（豆包 / DeepSeek）
  - 对接说明：课程/时间块/知识点/复习计划/任务/杂项/数据源真实对接 `/api/*`；后端暂无 plan/settings 路由，计划确认/调整与偏好配置先落 localStorage（`src/lib/storage.ts`），API 层预留切换点
  - Vitest 组件与纯函数测试 34 例全部通过（时间轴聚合 / 拖拽顺序 / 本地状态 / 日期工具 / 三组件）；`npm run build` 通过；与后端本地联调跑通（Edge headless 截图验证三页面）
  - `frontend/README.md` 启动说明 + `scripts/seed_demo.py` 演示数据脚本
- 后端 MCP Server 暴露层（#20）：
  - `backend/mcp_server/` 包：用官方 MCP SDK（mcp>=2.0.0）把后端包装为 Streamable HTTP MCP Server，挂载 `/mcp` 路径（QClaw 连接地址 `http://<局域网IP>:8000/mcp`，无 307 重定向，局域网 Host 直连）
  - 8 个工具：generate_tomorrow_plan / get_today_plan_preview / confirm_plan / adjust_plan_item / get_courses / get_tasks / get_reviews / mark_done，复用 `backend/scheduler/` 规划器与校准算法；工具出错返回中文 `{"error": ...}`
  - 计划编排服务：生成（草案，已确认的计划不自动重排、done 项防冲突）、预览（微信友好文本）、确认（版本快照 plan_versions）、调整（时间冲突校验）、完成（联动 review_schedules + calibration_stats 分桶校准）
  - APScheduler 每天 21:00 自动生成次日计划（后端兜底，QClaw 未触发也能跑；misfire 1 小时补跑；`JREN_MCP_SCHEDULER_ENABLED` / `JREN_MCP_PLAN_GENERATE_TIME` 可配置）
  - Notion Calendar 写入 service：confirm 时把 plan_items 幂等写入 Notion 日程数据库（按「日期+标题」匹配新建/更新/跳过），事件带 08:00 提醒（方案 A 双保险），属性名可配置，token 过期自动刷新
  - 使用说明 `docs/mcp-server.md`（QClaw 连接步骤 + 定时任务配置 + 微信通道实测记录表）；pytest 测试 39 例全部通过（全量 212 例，无回归）
- 方案 A 本地部署（#22）：开机自启脚本 `backend/scripts/start_backend.bat`（端口占用检测防重复启动、日志落盘 `backend/data/server.log`、预留 `JREN_NOTION_CALENDAR_DB` 环境变量位）+ `start_backend_hidden.vbs`（隐藏窗口启动器，复制到系统「启动」文件夹即登录自启，替代需管理员的 schtasks）；`docs/mcp-server.md` 2.1 开机自启章节（含大白话自查方法）+ README 同步；脚本保持 ASCII 编码（cmd/WSH 按 ANSI 代码页解析）

[#1]: https://github.com/Leo-iaa/jren-campus-assistant/issues/1
[#7]: https://github.com/Leo-iaa/jren-campus-assistant/issues/7
[#9]: https://github.com/Leo-iaa/jren-campus-assistant/issues/9
[#11]: https://github.com/Leo-iaa/jren-campus-assistant/issues/11
[#13]: https://github.com/Leo-iaa/jren-campus-assistant/issues/13
[#20]: https://github.com/Leo-iaa/jren-campus-assistant/issues/20
[#22]: https://github.com/Leo-iaa/jren-campus-assistant/issues/22
