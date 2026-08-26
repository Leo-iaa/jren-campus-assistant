# MCP Server 暴露层使用说明（WorkBuddy 接入）

> 对应 Issue #20（暴露层）与 #55（add_task / Notion 任务库），实现于 `backend/mcp_server/`。
> 本文档面向实际部署与联调，
> 协议细节可参考 [docs/architecture.md](architecture.md) 2.1 载体层与
> [docs/vision.md](vision.md)「提醒链路（方案 A）」。

## 1. 这是什么

后端把业务能力包装为 **MCP Server**（Streamable HTTP 传输，挂载在 `/mcp` 路径），
让 WorkBuddy（AI 载体）通过标准 MCP 协议调用：生成 / 预览 / 确认 / 调整每日计划、
**一句话添加任务**、查询课程 / 任务 / 复习、标记完成并校准耗时预估。

与 `backend/mcp_client/`（数据**接入**层：读 Notion / Obsidian / iCal）相对，
本层是数据**暴露**层：WorkBuddy → `/mcp` → 编排服务 → 数据库 + 调度算法。

```
WorkBuddy（MCP 客户端，微信远程）
   │  Streamable HTTP：http://127.0.0.1:8000/mcp（方案 A 同机）
   ▼
backend/mcp_server/server.py    ← 9 个 MCP 工具（薄封装）
   ▼
backend/mcp_server/service.py   ← 计划编排（生成/预览/确认/调整/完成/查询/添加任务）
   ├── backend/scheduler/       ← 遗忘曲线 + 时间表规划器 + 校准（纯算法）
   ├── backend/mcp_server/notion_calendar.py  ← Notion 日历写入（幂等，时段块事件）
   ├── backend/mcp_server/notion_task.py      ← Notion 任务库写入（属性探测降级）
   └── backend/mcp_server/scheduler_jobs.py   ← APScheduler 21:00 兜底
```

## 2. 快速启动

```bash
# 仓库根目录
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0`：**必须**，否则 WorkBuddy（手机 / 其他设备）连不上
- 启动日志会出现：`MCP 定时任务已启动：每天 21:00 生成次日计划`（APScheduler 兜底）
- 验证：
  - `curl http://127.0.0.1:8000/health` → `{"status":"ok","database":"connected"}`
  - 浏览器打开 `http://127.0.0.1:8000/docs` 可看 REST API

> ⚠️ 首次使用前记得 `python -m backend.scripts.init_db` 初始化数据库（幂等）。

### 2.1 开机自启（Windows，方案 A 部署）

后端与 WorkBuddy 同机部署时，让服务在**开机登录后自动后台启动**，无需手动操作：

1. 两个脚本（已入库 `backend/scripts/`）：
   - `start_backend.bat`：启动逻辑——定位仓库根、启动 uvicorn、日志落盘 `backend/data/server.log`；
     自带**端口占用检测**（8000 已被监听则跳过，防重复启动）
   - `start_backend_hidden.vbs`：隐藏窗口启动器（WSH `Run` 窗口参数 0，桌面不弹黑窗口）
2. 配置自启：把 `start_backend_hidden.vbs` **复制**到系统启动文件夹：
   `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`
   （资源管理器地址栏粘贴该路径回车即可）
3. 原理：登录时 Windows 自动运行启动文件夹里的 vbs → 隐藏启动 bat → uvicorn 后台运行

> 💡 为什么不用「任务计划程序」：非管理员终端下 `schtasks /create` 注册会被拒（拒绝访问）；
> 单用户登录场景下启动文件夹等效且零权限依赖，对新手更直观。

> ⚠️ 两个脚本必须保持 **ASCII 纯英文注释**：cmd.exe 与 WSH 按 ANSI 代码页解析脚本文件，
> UTF-8 中文注释会被拆成乱码命令导致启动失败（实测踩坑）。

**自查服务是否在跑（大白话）**：浏览器打开 `http://127.0.0.1:8000/health`，
看到 `{"status":"ok",...}` 就是正常；打不开则双击 `start_backend.bat` 手动启动，
或重启电脑让自启重新生效。

> 注意：vbs 引用的是仓库的**绝对路径**；若仓库被移动，需同步更新 vbs 中的路径。

## 3. 工具清单（9 个）

| 工具 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `generate_tomorrow_plan` | `date?`（YYYY-MM-DD，默认明日）、`auto_confirm?`（默认 false） | JSON：placed / dropped / skipped / preview / confirm? | 生成计划草案（draft）。`auto_confirm=true` 时生成后立即确认并写 Notion 日历（免睡前确认） |
| `get_today_plan_preview` | `date?`（默认今日） | 纯文本 | 微信友好预览：时间轴 + 确认状态，适合 08:00 推送 |
| `confirm_plan` | `date`（必填） | JSON：confirmed_count / version / notion_sync | 确认计划 → 版本快照 → 写 Notion 日历（时段块事件） |
| `adjust_plan_item` | `item_id`、`start_time`、`end_time`、`title?` | JSON：更新后的计划项 + notion_sync + message | 调整单项时间/标题；冲突会报错。**该日计划已确认时自动同步更新 Notion 日历**（Issue #58） |
| `add_task` | `title`（必填）、`due_date?`、`task_type?`、`course_id?`、`estimated_minutes?` | JSON：task / plan_action / plan_message / notion_sync | **一句话添加任务**：写本地 + Notion 任务库，并联动今日计划（详见下） |
| `mark_done` | `item_id`、`actual_minutes?` | JSON：计划项 + 校准记录 | 标记完成；task/review 记录「预估 vs 实际」校准 |
| `get_courses` | 无 | JSON 数组 | 课程列表（含 S/A/B/C 档位） |
| `get_tasks` | `status?`（todo/doing/done/cancelled） | JSON 数组 | 作业任务列表（含类型 task_type） |
| `get_reviews` | `due_date?`（YYYY-MM-DD） | JSON 数组 | 复习计划列表（含知识点与难度） |

调用约定：
- 工具出错返回 `{"error": "中文原因"}`；缺少必填参数由 MCP 协议层直接拒绝
- 日期一律 `YYYY-MM-DD`、时间一律 `HH:MM`，时区为 **Asia/Shanghai**
- 预览为纯文本（可直接推微信），其余工具返回 JSON 文本

### 生成语义（重要）

- 每晚 21:00 生成的是 **草案（draft）**，需要用户确认后才生效、才写日历
- **已确认的计划不会自动重排**：再次调用 `generate_tomorrow_plan` 会提示
  「该日计划已确认」，改动请用 `adjust_plan_item` 逐项调整
- 放不下的项目进 `dropped`，缺时长的杂项 / 与已完成项冲突的草案进 `skipped`

### add_task 语义（一句话添加任务，Issue #55）

微信工作流：用户说「有新任务：XXX，ddl 是 YYY，类型是 ZZZ」→ WorkBuddy 调
`add_task` → 后端写本地 `tasks` 表 + Notion 任务库 → 联动今日计划 → 返回
`plan_message`（WorkBuddy 直接转述给用户）。

参数说明：
- `title`：任务名（必填）
- `due_date`：截止日期（YYYY-MM-DD，可选）
- `task_type`：任务类型，枚举 **作业 / 实验 / 考试 / 其他**（可选）
- `course_id`：关联课程 id（可选，用 `get_courses` 查）
- `estimated_minutes`：预估耗时（分钟，可选，供规划器排时长）

**计划联动设计理由**：是否立即重排今日，取决于「任务紧迫度」与「今日计划是否已确认」——

| 场景 | 行为 | 理由 |
|------|------|------|
| ddl ≤ 明天 且 今日计划未确认 | 立即重排今日（复用 `generate_plan`，幂等），返回「已安排到今天 HH:MM-HH:MM」 | 紧迫任务尽早落位，避免拖到截止才想起 |
| 今日计划已确认 | 不重排，提示下次生成时纳入 | 尊重已确认安排（与 `generate_tomorrow_plan` 同一保护语义） |
| ddl 更远 / 无 ddl / 已过期 | 不挤占今天，下次 21:00 生成时自然纳入 | 远期任务不抢占今天时间片；过期任务不自动排（提示手动处理） |

Notion 任务库写入为**尽力而为**：未配置任务库 / 写入失败不阻断添加，
结果进 `notion_sync` 字段（WorkBuddy 可转述「任务库写入失败：原因」）。

## 4. WorkBuddy 连接步骤

> 方案 A 部署：WorkBuddy 与后端**装在同一台 Windows 电脑**，直接连本机地址，无需查局域网 IP。

1. **确认后端已启动**（见第 2 节）
2. **打开 WorkBuddy → 设置 → MCP 服务**（或「MCP 管理」），添加服务器：
   - 名称随意（如 `jren-campus-assistant`）
   - 类型：**http**（Streamable HTTP）
   - 地址：`http://127.0.0.1:8000/mcp`
3. 若 WorkBuddy 支持直接编辑配置文件，等价配置（mcp.json）：

   ```json
   {
     "mcpServers": {
       "jren-campus-assistant": {
         "type": "http",
         "url": "http://127.0.0.1:8000/mcp"
       }
     }
   }
   ```

4. **验证**：连接成功后让 WorkBuddy 列出工具，应能看到上表 9 个工具；
   试着问「查询课程列表」或「今天的计划是什么」

> 💡 以后若把 WorkBuddy 装到**另一台设备**（如手机或宿舍电脑），才需要改用局域网地址
> `http://<电脑IP>:8000/mcp` 并确保防火墙放行 8000 端口、两端同一网络。

## 5. WorkBuddy 定时任务配置（主通道，已实测）

用 WorkBuddy 的**「自动化」功能**创建两个定时任务（支持每日 / CRON 触发，可调用已连接的 MCP 工具）：

| 定时任务 | 触发时间 | 调用工具 | 用途 |
|----------|----------|----------|------|
| 生成明日计划 | 每天 21:00 | `generate_tomorrow_plan`（`auto_confirm=true`） | 生成次日计划 → 自动确认 → 写 Notion 日历 → 推微信 |
| 推送今日计划 | 每天 08:20 | `get_today_plan_preview` | 把今日计划文本直推微信（方案 A 主提醒） |

建议的自动化指令文本（已实测跑通，可直接使用）：

```
每天 21:00：调用 jren-campus-assistant 的 generate_tomorrow_plan 工具（auto_confirm 设为 true）
生成并自动确认次日计划，任务完成后把返回结果里 preview 字段的完整文本作为消息，
调用 wechat-clawbot-push 的 push_wechat_message 工具推送到我的微信；
如果 preview 为空，就把 message 字段的内容推送给我。
```

```
每天 08:20：调用 jren-campus-assistant 的 get_today_plan_preview 工具获取今日计划文本，
把返回的文本作为消息，调用 wechat-clawbot-push 的 push_wechat_message 工具推送到我的微信。
```

### 5.1 微信直推（wechat-clawbot-push，实测方案）

自动化结果直推**个人微信 ClawBot 聊天框**的实现（2026-08-25 实测通过）：

1. **安装桥**：`wechat-clawbot-push` 是 PyPI 上的 stdio MCP 服务（v2.x），暴露
   `push_wechat_message` 工具，专为 WorkBuddy 个人微信 ClawBot 定时主动推送设计。
   在 WorkBuddy 中按其文档安装到隔离 venv，并注册进 `mcp.json`（stdio）
2. **授权 token**：首次调用 `acquire_token` 是长轮询——按提示**立即用手机微信给
   ClawBot 发任意一条文字消息**（约 35 秒窗口），token 会绑定到 `C:\Users\<user>\.workbuddy\wechat-clawbot-push\push_cache.json`
3. **验证**：`bridge_status` 自检 token 有效，`--test` 或直接调 `push_wechat_message` 发一条测试消息；
   多个自动化任务**复用同一个已缓存 token**，无需重复授权
4. **推送**：自动化任务里把结果作为消息参数调 `push_wechat_message`，返回 HTTP 200 即成功

> 与「推送到小程序」的区别：小程序是 WorkBuddy 自带开关（结果发到小程序）；ClawBot 推送达
> 到**微信聊天窗口**本身。本项目实测方案走 ClawBot 直推。

## 6. 后端 21:00 兜底（APScheduler）

即使 WorkBuddy 未触发 / 未配置，只要后端进程在运行，每天 21:00 也会自动生成次日计划：

- 实现：`backend/mcp_server/scheduler_jobs.py`（BackgroundScheduler + CronTrigger）
- 时区：Asia/Shanghai；错过触发点（如电脑休眠）1 小时内补跑
- 开关与环境变量见第 8 节表格；启动日志会打印任务状态

> 注意：兜底生成的是**草案**（不自动确认、不写日历）——自动确认由 WorkBuddy 定时任务
> 的 `auto_confirm=true` 承担（避免未配置 Notion 时兜底静默写库）。

## 7. Notion Calendar 写入

确认计划时（`confirm_plan`）自动把当日 plan_items **幂等**写入 Notion 日程数据库，
事件含**起止时间**（日历显示为时段块）。

> ⚠️ **关于 08:00 提醒**：Notion API 限制 `reminder` 只能用于**不含时间**的 date 属性，
> 带起止时间（datetime）的事件不允许带提醒。因此写入**不带 reminder**，
> 08:00 提醒由 **WorkBuddy 微信推送**承担（方案 A 主通道，见 [docs/vision.md](vision.md) 提醒链路）。

### 7.1 前置条件

1. 已绑定 Notion 数据源并配置**集成令牌**（`config.tokens.access_token`，见 [docs/mcp-client.md](mcp-client.md) 3.1；REST 直连，无需 OAuth）
2. 在 Notion 建一个**日程数据库**（Calendar database，模板选「日程」），
   记下数据库 ID（URL 中 `.../<32位ID>?v=...` 的那段）
3. 数据库需包含以下属性（默认名，可在 config.props 覆盖）：
   - **名称**（title，必选）；**日期**（Date 类型，**需包含时间**）；**类型**（Select 类型）
   - 模板缺属性时在数据库「属性」里手动添加
4. 告诉后端日历数据库 ID（二选一）：
   - 环境变量：`JREN_NOTION_CALENDAR_DB=<数据库ID>`
   - 或写进数据源 config：`PATCH /api/data-sources/{id}`，config JSON 加
     `"calendar_database_id": "<数据库ID>"`

### 7.2 属性映射（可配置）

| 属性（默认名） | 用途 | 说明 |
|----------------|------|------|
| 名称（title） | 事件标题 | 即 plan_item.title |
| 日期（date） | 起止时间 | `YYYY-MM-DDTHH:MM:00+08:00`，带时区偏移避免显示偏差 |
| 类型（select） | 事件分类 | course / task / review / misc |

数据库属性名不同时，在数据源 config 加：

```json
{"props": {"title": "Event", "date": "Date", "type": "Category"}}
```

### 7.3 幂等与更新

- 按「当日日期 + 标题」匹配已有事件：不存在 → 新建；时间/类型变了 → 更新；
  完全一致 → 跳过
- 同一天重复确认不会产生重复事件
- 确认结果里 `notion_sync` 字段报告 `created / updated / unchanged`；
  Notion 未授权或未配置时该字段为错误信息或 null（**不阻断确认**）

### 7.4 Notion 任务库写入（add_task 用，Issue #55）

微信添加任务时把任务写入**第二个 Notion 库**（任务库，与日程库并列）：

1. **找到任务库**：在 Notion 建「任务列表」模板数据库（属性：任务名称 / 截止日期 /
   当前状态 / 优先级 / 备注），记下数据库 ID——直接粘贴**页面链接**也行，
   `config_notion.bat` 会自动解析页面内嵌数据库并让你选择
2. **配置任务库 ID**（二选一，与日程库配置并列，可共用同一个集成令牌）：
   - 环境变量：`JREN_NOTION_TASK_DB=<数据库ID>`
   - 或数据源 config：`"task_database_id": "<数据库ID>"`
   - 推荐：重跑 `config_notion.bat`，脚本会引导输入/沿用三个配置（令牌 / 日程库 / 任务库）

属性映射（默认名，可在 `config.task_props` 覆盖，**独立于日历库的 props**）：

| 属性（默认名） | 用途 | 说明 |
|----------------|------|------|
| 任务名称（title） | 任务名 | 必填 |
| 截止日期（date） | ddl | 只写日期 `YYYY-MM-DD`（date-only） |
| 当前状态（status） | 初始状态 | 自动取库内「To-do 组」首选项名（如中文模板的「未开始」），选项名以库为准 |
| 类型（select） | 任务类型 | 库中**没有该属性则跳过并提示**（补上后自动生效，零代码改动） |
| 优先级 / 备注 | 暂未写入 | 预留，属性名可配置 |

写入前用 `GET /v1/databases/{id}` 探测属性，**只写入库中真实存在的属性**——
用户任务库没建「类型」属性时任务照常入库，`notion_sync.missing_props` 会报告缺失项。

## 8. 环境变量一览

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `JREN_MCP_SCHEDULER_ENABLED` | `true` | 是否启用 21:00 兜底定时任务（测试/开发可关） |
| `JREN_MCP_PLAN_GENERATE_TIME` | `21:00` | 兜底任务触发时间（HH:MM，Asia/Shanghai） |
| `JREN_MCP_NOTION_CALENDAR_DB` | 无 | Notion 日程数据库 ID（或写入数据源 config） |
| `JREN_MCP_NOTION_TASK_DB` | 无 | Notion 任务数据库 ID（add_task 写入用，或写入数据源 config） |

## 9. 微信通道实测记录

> 表格用于记录真实联调结果（单向 = WorkBuddy→微信推送；双向 = 微信回复→WorkBuddy 调工具）。

| 日期 | 场景 | 通道 | 结果 | 备注 |
|------|------|------|------|------|
| 2026-08-25 | 08:20 今日计划推送 | 单向（wechat-clawbot-push 直推 ClawBot） | ✅ 成功（HTTP 200） | 手动模拟触发验证；token 已缓存复用 |
| 2026-08-25 | 21:00 生成明日计划推送 | 单向（wechat-clawbot-push 直推 ClawBot） | ✅ 成功（HTTP 200） | 手动模拟触发验证，preview 完整文本已送到微信 |
| 待实测 | 微信回复「确认今天的计划」 | 双向 |  | 微信助理对话通道 |
| 待实测 | 微信回复「把高数作业挪到晚上」 | 双向 |  | 调整后自动同步 Notion 日历 |
| 待实测 | 微信回复「添加任务：XXX」 | 双向 |  | add_task 工具已就绪 |
| 待实测 | 微信回复「标记高数作业完成」 | 双向 |  |  |

## 10. 常见问题（FAQ）

**Q：WorkBuddy 提示连不上 / 超时？**
A：① 后端是否在跑（浏览器开 `http://127.0.0.1:8000/health` 应返回 ok）；② MCP 地址是否
`http://127.0.0.1:8000/mcp`；③ 类型是否选 **http**（Streamable HTTP）；④ 若 WorkBuddy 装在其他设备，
改用 `http://<电脑IP>:8000/mcp` 并确认防火墙放行 8000、两端同一网络。

**Q：WorkBuddy 装到别的设备时局域网 IP 变化了怎么办？**
A：家用路由器一般 DHCP 分配，重启可能变。建议在路由器里给电脑绑定静态 IP，
或每次重启后重新确认 IP（WorkBuddy 里改地址）。同机部署（127.0.0.1）无此问题。

**Q：`/mcp` 为什么不需要鉴权？**
A：单用户家庭局域网使用，未加认证；请勿把 8000 端口暴露到公网。

**Q：生成计划时说「该日计划已确认，未重新生成」？**
A：这是保护行为——已确认的计划不会被自动覆盖。新增/改动请用
`adjust_plan_item` 逐项调整，或先在计划项层面处理。

**Q：Notion 日历没写入？**
A：确认 `confirm_plan` 返回的 `notion_sync` 字段：null = 未绑定 Notion 数据源；
`{"error": ...}` = 按错误信息排查（未授权 / 缺数据库 ID / 属性名不匹配）。

**Q：事件显示时间不对？**
A：写入值带 `+08:00` 偏移，Notion 应按数据库所在时区正确显示；若仍不对，
检查 Notion 工作区时区设置。

## 11. 相关文档

- [docs/architecture.md](architecture.md) 2.1 载体层（Notion Calendar + WorkBuddy）
- [docs/vision.md](vision.md) 提醒链路（方案 A）与产品决策
- [docs/mcp-client.md](mcp-client.md) MCP 数据接入层（Notion OAuth 等）
- [docs/database.md](database.md) 表结构（plan_items / plan_versions / calibration_stats）
