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
- 移除备用前端 frontend/（数据源绑定 / 档位配置改走 API 与 WorkBuddy，#30）
- 用户使用手册 `docs/USER_GUIDE.md` + README 手册入口（#32）
- 手册修正：PowerShell / CMD 激活命令区分、Notion 绑定改 Swagger UI 图形界面优先（#34）
- 手册补充：Python 自检步骤（微软商店占位符 python 会导致 venv 静默创建失败，#36）
- 新增 `setup.bat` 一键安装脚本；`requirements.txt` 去中文注释（GBK 系统 pip 编码兼容，#38）
- setup.bat 增强：自动探测 Python（商店别名抢占时回退 `py -3`），实测双路径通过（#40）
- 脚本防呆：`start_backend.bat` / `setup.bat` 支持无 venv 模式（自动回退 `py -3 --user` 安装）；用户手册全面去命令化（纯双击 + 图形界面，#42）
- 新增 `config_notion.bat` / `config_notion.py`：Notion 一键配置（只需输入令牌 + 数据库 ID 两串码，自动绑定数据源与日历库，#44）
- 新增 `config_ical.bat` / `config_ical.py`：课表一键导入（.ics 拖进窗口即可，自动绑定 + 同步；用户真实课表已导入 13 门课 / 20 时间块，#46）
- 预览回退：本地无计划时 `get_today_plan_preview` 自动读 Notion 日历当天事件（AI 回答与日历一致；+2 测试，#48）
- 修复自启脚本绝对路径：`start_backend_hidden.vbs` 更新为当前仓库位置（#50）
- `config_notion` 支持直接粘贴日程页面整条链接（自动提取 32 位数据库 ID，忽略视图 ID，#52）
- README 补充「隐私与数据」说明（数据全本地、密钥自配、公开仓库须知，#53）
- 微信一句话添加任务闭环（#55）：
  - 新增 MCP 工具 `add_task`（第 9 个）：title / due_date / task_type（作业/实验/考试/其他）/ course_id / estimated_minutes，返回微信友好 `plan_message`
  - 本地 `tasks` 表新增 `task_type` 列；`init_db` 轻量迁移自动为旧库补列（幂等）
  - 新增 `backend/mcp_server/notion_task.py`：Notion 任务库写入器，写前探测数据库属性、只写真实存在的属性（缺「类型」等属性时跳过并报告，补属性后零代码生效）；状态选项名按库内 schema 动态解析（实测中文模板为「未开始」）
  - 计划联动：ddl ≤ 明天且今日未确认 → 立即重排今日（复用 generate_plan）；已确认 / 远期 / 过期 → 下次 21:00 生成时纳入（设计理由见 docs/mcp-server.md）
  - `config_notion.bat` 扩展为三配置（令牌 / 日程库 / 任务库），支持回车沿用已有配置；粘贴**页面链接**自动解析页面内嵌数据库并让用户选择（实测任务库为页面内数据库）
  - 修复实测暴露的既有 bug：`generate_plan` 重排时删除先落地（flush），避免新草案与旧 draft 同 start_time 撞 UNIQUE(date, start_time)
  - 文档同步：mcp-server.md（9 工具 + add_task 语义 + 7.4 任务库节）/ USER_GUIDE.md / database.md / README
    - pytest 新增 22 例（任务库 writer 12 + service add_task 9 + 端点 1），全量 239 例通过；本地真实闭环实测通过（微信路径 add_task → 本地 tasks + Notion 任务库 + 今日计划）
  - 计划自动确认 + 调整同步日历 + WorkBuddy 微信推送文档（#58）：
    - `generate_tomorrow_plan` 新增 `auto_confirm` 参数：true 时生成后立即确认（draft→confirmed + 版本快照 + 写 Notion 日历），幂等；21:00 定时任务免睡前确认直达日历
    - `adjust_plan_item` 新增日历同步：该日计划已确认（已写日历）时增量幂等同步当日到 Notion 日历，返回 `notion_sync` + `message`；草案期不写、同步失败不阻断
    - WorkBuddy 微信直推链路实测并写入文档：`wechat-clawbot-push` 桥（PyPI stdio MCP，`push_wechat_message`）→ 个人微信 ClawBot 聊天框；08:20 今日计划 / 21:00 明日计划（auto_confirm）两个定时任务实测推送成功
    - docs/mcp-server.md「微信通道实测记录」更新（2026-08-25 单向推送 ✅）；README / USER_GUIDE 同步
    - pytest 新增 5 例（service 3 + 端点 2），全量 244 例通过
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
- AI 载体切换 WorkBuddy（#24）：QClaw 因体验问题弃用，载体换为 WorkBuddy（腾讯 CodeBuddy：MCP stdio/sse/http + 自动化定时任务 + 微信/企微/QQ/飞书/钉钉远程）；README / docs/{mcp-server,vision,architecture}.md 载体描述与连接/定时任务指引同步（同机部署连 `http://127.0.0.1:8000/mcp`，无需查局域网 IP）；后端代码注释同步；MCP 暴露层协议不变（标准 Streamable HTTP，后端零逻辑改动）
- Notion 接入改 REST 直连（#26）：mcp.notion.com 不接受自建集成令牌（官方确认，一律 401），NotionAdapter / NotionCalendarWriter 从 MCP 传输改为直连 api.notion.com（新增 `mcp_client/notion_rest.py`，Bearer 集成令牌 + Notion-Version）；幂等写入与属性映射逻辑不变；测试 fake 传输层改 FakeNotionRest；docs/mcp-client.md 接入方式更新（OAuth 端点保留但非主路径）
- Notion 日历写入适配（#26 补充）：Notion API 限制 reminder 只能用于不含时间的 date 属性，datetime 事件不允许带提醒——写入改为**不带 reminder**（事件保留起止时间，日历显示时段块），08:00 提醒职责由 WorkBuddy 微信推送承担；文档（README / mcp-server / vision）提醒链路描述同步更新

### Fixed

- **安全**：数据源 `config` 中的敏感字段（Notion `tokens` / `client_secret` / `client_id` / OAuth `state` / `code_verifier`）在 API 响应中打码为 `***`，不再经 `/api/data-sources` 明文泄露
- **校验**：课程时间块 `end_time <= start_time` 在创建 / 更新时返回 422（此前会被接受入库，导致规划器崩溃）
- **iCal 解析**：结束不晚于开始的事件直接跳过并告警（此前仅告警仍入库）
- **时区一致**：`created_at` 默认值由 SQLite UTC（`datetime('now')`）改为 Asia/Shanghai，与 `confirmed_at` / `completed_at` / `last_sync_at` 对齐，消除 +8 小时偏差
- **启动健壮性**：应用 lifespan 自动确保 SQLite 目录存在并建表（幂等），未先执行 `init_db` 也能正常启动
- **Notion 日历幂等**：写入键由「标题」改为「标题 + 开始时间」，同日同名但不同时段的事件不再互相覆盖 / 错位更新
- **Notion 同步**：捕获 REST 传输异常（`NotionRestError`）返回可读错误；`deadline` 统一规范为 `YYYY-MM-DD`（兼容 Notion 的 ISO 时间串）
- **计划生成**：任务 / 复习 / 杂项时长越界时 clamp 到安全上限（防止 `time()` 溢出导致 500）
- **前端 · 定时杂项被丢弃**：带 `preferred_time` 的杂项不再被静默丢弃，进入时间轴并计入空闲时段占用
- **前端 · 打包算法**：灵活项改为 first-fit 扫描全部空闲块（此前逐块跳过，小块堵塞时误入 overflow）
- **前端 · 复习上限**：每日复习上限生效，超出部分进入 overflow 并标注「顺延处理」；设置页文案与实际行为对齐
- **前端 · OAuth 回调**：修复 HashRouter 下 `redirect_uri` 不带 `#/` 导致回调路由不挂载、`code/state` 丢失的问题
- **前端 · 状态**：今日 / 周视图 `loading` 与 `error` 对齐（含知识点与时间块请求）；拖拽保存副作用移出 `setState` updater
- **测试**：修复 `WeekGrid.test.tsx` 依赖真实日期的脆弱用例（8 月 18 日必挂）；新增定时杂项 / 复习上限 / first-fit / 时间校验 / 打码 / 幂等键等用例

[#1]: https://github.com/Leo-iaa/jren-campus-assistant/issues/1
[#7]: https://github.com/Leo-iaa/jren-campus-assistant/issues/7
[#9]: https://github.com/Leo-iaa/jren-campus-assistant/issues/9
[#11]: https://github.com/Leo-iaa/jren-campus-assistant/issues/11
[#13]: https://github.com/Leo-iaa/jren-campus-assistant/issues/13
[#20]: https://github.com/Leo-iaa/jren-campus-assistant/issues/20
[#22]: https://github.com/Leo-iaa/jren-campus-assistant/issues/22
[#24]: https://github.com/Leo-iaa/jren-campus-assistant/issues/24
[#26]: https://github.com/Leo-iaa/jren-campus-assistant/issues/26
