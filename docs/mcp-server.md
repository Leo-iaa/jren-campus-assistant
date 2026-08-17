# MCP Server 暴露层使用说明（QClaw 接入）

> 对应 Issue #20，实现于 `backend/mcp_server/`。本文档面向实际部署与联调，
> 协议细节可参考 [docs/architecture.md](architecture.md) 2.1 载体层与
> [docs/vision.md](vision.md)「提醒链路（方案 A）」。

## 1. 这是什么

后端把业务能力包装为 **MCP Server**（Streamable HTTP 传输，挂载在 `/mcp` 路径），
让 QClaw（AI 载体）通过标准 MCP 协议调用：生成 / 预览 / 确认 / 调整每日计划、
查询课程 / 任务 / 复习、标记完成并校准耗时预估。

与 `backend/mcp_client/`（数据**接入**层：读 Notion / Obsidian / iCal）相对，
本层是数据**暴露**层：QClaw → `/mcp` → 编排服务 → 数据库 + 调度算法。

```
QClaw（MCP 客户端，微信远程）
   │  Streamable HTTP：http://<局域网IP>:8000/mcp
   ▼
backend/mcp_server/server.py    ← 8 个 MCP 工具（薄封装）
   ▼
backend/mcp_server/service.py   ← 计划编排（生成/预览/确认/调整/完成/查询）
   ├── backend/scheduler/       ← 遗忘曲线 + 时间表规划器 + 校准（纯算法）
   ├── backend/mcp_server/notion_calendar.py  ← Notion 日历写入（幂等 + 08:00 提醒）
   └── backend/mcp_server/scheduler_jobs.py   ← APScheduler 21:00 兜底
```

## 2. 快速启动

```bash
# 仓库根目录
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0`：**必须**，否则 QClaw（手机 / 其他设备）连不上
- 启动日志会出现：`MCP 定时任务已启动：每天 21:00 生成次日计划`（APScheduler 兜底）
- 验证：
  - `curl http://127.0.0.1:8000/health` → `{"status":"ok","database":"connected"}`
  - 浏览器打开 `http://127.0.0.1:8000/docs` 可看 REST API

> ⚠️ 首次使用前记得 `python -m backend.scripts.init_db` 初始化数据库（幂等）。

## 3. 工具清单（8 个）

| 工具 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `generate_tomorrow_plan` | `date?`（YYYY-MM-DD，默认明日） | JSON：placed / dropped / skipped | 生成计划草案（draft）。已确认的计划不自动重排 |
| `get_today_plan_preview` | `date?`（默认今日） | 纯文本 | 微信友好预览：时间轴 + 确认状态，适合 08:00 推送 |
| `confirm_plan` | `date`（必填） | JSON：confirmed_count / version / notion_sync | 确认计划 → 版本快照 → 写 Notion 日历（带 08:00 提醒） |
| `adjust_plan_item` | `item_id`、`start_time`、`end_time`、`title?` | JSON：更新后的计划项 | 调整单项时间/标题；冲突会报错 |
| `mark_done` | `item_id`、`actual_minutes?` | JSON：计划项 + 校准记录 | 标记完成；task/review 记录「预估 vs 实际」校准 |
| `get_courses` | 无 | JSON 数组 | 课程列表（含 S/A/B/C 档位） |
| `get_tasks` | `status?`（todo/doing/done/cancelled） | JSON 数组 | 作业任务列表 |
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

## 4. QClaw 连接步骤

1. **确认后端已启动**（见第 2 节），并确保运行后端的电脑与手机在同一局域网
2. **查电脑局域网 IP**：
   - Windows：`ipconfig` 找「无线局域网适配器 WLAN」的 IPv4 地址（如 `192.168.1.5`）
   - 手机与电脑连同一个 Wi-Fi 即可
3. **防火墙放行 8000 端口**（Windows）：
   - 首次启动 uvicorn 时弹窗选「允许访问」；若没弹窗：
     设置 → 防火墙和网络保护 → 允许应用通过防火墙 → 添加 uvicorn/python 或放行 TCP 8000
4. **QClaw 中添加 MCP Server**：
   - 类型：Streamable HTTP
   - 地址：`http://<局域网IP>:8000/mcp`（例如 `http://192.168.1.5:8000/mcp`）
   - 名称随意（如 `jren-campus-assistant`）
5. **验证**：连接成功后让 QClaw 列出工具，应能看到上表 8 个工具；
   试着问「查询课程列表」或「今天的计划是什么」

> 手机浏览器访问 `http://<局域网IP>:8000/health` 能返回 JSON，
> 说明网络与防火墙已通，问题只在 QClaw 配置。

## 5. QClaw 定时任务配置（主通道）

| 定时任务 | 触发时间 | 调用工具 | 用途 |
|----------|----------|----------|------|
| 生成次日计划 | 每天 21:00 | `generate_tomorrow_plan` | 预生成明日计划草案 |
| 推送计划预览 | 每天 08:00 | `get_today_plan_preview` | 把今日计划文本推到微信（方案 A 主提醒） |

建议 QClaw 的任务提示词（可按 QClaw 的模板语言调整）：

```
每天 21:00：调用 jren-campus-assistant 的 generate_tomorrow_plan 工具生成次日计划，
把返回的 JSON 总结成一句话发给用户（如「明天的计划已生成，共 6 项，睡前记得确认」）。
```

```
每天 08:00：调用 get_today_plan_preview 工具，把返回的文本原样推送给用户。
```

## 6. 后端 21:00 兜底（APScheduler）

即使 QClaw 未触发 / 未配置，只要后端进程在运行，每天 21:00 也会自动生成次日计划：

- 实现：`backend/mcp_server/scheduler_jobs.py`（BackgroundScheduler + CronTrigger）
- 时区：Asia/Shanghai；错过触发点（如电脑休眠）1 小时内补跑
- 开关与环境变量见第 8 节表格；启动日志会打印任务状态

> 注意：兜底只生成草案，**确认与日历写入仍需用户操作**（QClaw 对话确认或手动确认）。

## 7. Notion Calendar 写入（双保险）

确认计划时（`confirm_plan`）自动把当日 plan_items **幂等**写入 Notion 日程数据库，
每个事件带 **08:00 提醒**（电脑关机时由 Notion 云端兜底提醒）。

### 7.1 前置条件

1. 已绑定 Notion 数据源并完成 OAuth 授权（见 [docs/mcp-client.md](mcp-client.md)）
2. 在 Notion 建一个**日程数据库**（Calendar database，模板选「日程」），
   记下数据库 ID（URL 中 `.../<32位ID>?v=...` 的那段）
3. 告诉后端日历数据库 ID（二选一）：
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
  Notion 未授权或未配置时该字段为错误信息或 null（**不阻断确认**，双保险语义）

## 8. 环境变量一览

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `JREN_MCP_SCHEDULER_ENABLED` | `true` | 是否启用 21:00 兜底定时任务（测试/开发可关） |
| `JREN_MCP_PLAN_GENERATE_TIME` | `21:00` | 兜底任务触发时间（HH:MM，Asia/Shanghai） |
| `JREN_MCP_NOTION_CALENDAR_DB` | 无 | Notion 日程数据库 ID（或写入数据源 config） |

## 9. 微信通道实测记录

> 表格用于记录真实联调结果（单向 = QClaw→微信推送；双向 = 微信回复→QClaw 调工具）。

| 日期 | 场景 | 通道 | 结果 | 备注 |
|------|------|------|------|------|
| 待实测 | 08:00 预览推送 | 单向 |  |  |
| 待实测 | 21:00 生成提醒 | 单向 |  |  |
| 待实测 | 微信回复「确认今天的计划」 | 双向 |  |  |
| 待实测 | 微信回复「把高数作业挪到晚上」 | 双向 |  |  |
| 待实测 | 微信回复「标记高数作业完成」 | 双向 |  |  |

## 10. 常见问题（FAQ）

**Q：QClaw 提示连不上 / 超时？**
A：① 后端是否 `--host 0.0.0.0` 启动；② 手机和电脑是否同一 Wi-Fi；
③ `ipconfig` 的 IP 是否填对；④ 防火墙是否放行 8000。

**Q：局域网 IP 变化了怎么办？**
A：家用路由器一般 DHCP 分配，重启可能变。建议在路由器里给电脑绑定静态 IP，
或每次重启后重新确认 IP（QClaw 里改地址）。

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

- [docs/architecture.md](architecture.md) 2.1 载体层（Notion Calendar + QClaw）
- [docs/vision.md](vision.md) 提醒链路（方案 A）与产品决策
- [docs/mcp-client.md](mcp-client.md) MCP 数据接入层（Notion OAuth 等）
- [docs/database.md](database.md) 表结构（plan_items / plan_versions / calibration_stats）
