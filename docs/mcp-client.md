# MCP 数据接入层（backend/mcp_client）

> 对应 [架构设计 2.2「MCP 客户端层」](architecture.md#22-mcp-客户端层数据接入)：
> 统一通过 MCP 协议接入外部数据，未来加数据源 = 加 adapter，不改核心逻辑。
> 实现于 Issue [#11](https://github.com/Leo-iaa/jren-campus-assistant/issues/11)。

## 1. 模块结构

```text
backend/mcp_client/
├── models.py      # 纯数据结构（TaskItem / NoteItem / CourseSessionItem / SyncResult）
├── transport.py   # MCP 传输层：JSON-RPC 2.0（stdio 子进程 / streamable HTTP）+ McpClient
├── oauth.py       # OAuth 2.0 授权码 + PKCE（S256）客户端
├── ical.py        # iCal adapter：教务 .ics 课表 → 课程时间块
├── notion.py      # Notion adapter：官方远程 MCP（mcp.notion.com/mcp）→ 作业任务
├── obsidian.py    # Obsidian adapter：obsidian-mcp-server / vault 直读 → 笔记查询
└── service.py     # 同步服务：adapter 结果落库 + last_sync_at 管理
```

约定：adapter 产出纯数据结构（不依赖 ORM），落库全部在 `service.py`；
传输层可注入替换（测试用 fake），真实账号接入时无需改动 adapter。

## 2. 课表（iCal）—— 最常用

教务系统导出 `.ics` 后，两种方式同步：

### 2.1 方式一：配置 ics_path（推荐，支持重复同步）

```bash
# 1. 绑定数据源（config 里写 .ics 文件路径）
curl -X POST http://127.0.0.1:8000/api/data-sources \
  -H 'Content-Type: application/json' \
  -d '{"source_type": "ical", "name": "2026春夏课表",
       "config": "{\"ics_path\": \"C:/Users/LEO/Downloads/2026春夏.ics\"}"}'

# 2. 触发同步（创建/更新 courses + course_sessions，并记录 last_sync_at）
curl -X POST http://127.0.0.1:8000/api/data-sources/<id>/sync
```

### 2.2 方式二：请求体直接提交 .ics 文本

```bash
curl -X POST http://127.0.0.1:8000/api/data-sources/<id>/sync \
  -H 'Content-Type: application/json' \
  -d '{"ics_content": "BEGIN:VCALENDAR\n..."}'
```

### 2.3 解析规则（以教务导出为基准）

| 特性 | 处理 |
|------|------|
| `DTSTART/DTEND` 带 `TZID=Asia/Shanghai` | 按 +08:00 归一化，取本地星期与时段 |
| `RRULE:FREQ=WEEKLY;UNTIL=...` | 展开为每周模板 → `course_sessions` |
| 同一课程拆多个 VEVENT（教师/教室中途更换） | 按 `(课程, 星期, 开始时间)` 合并，保留信息最新的一份 |
| `LOCATION: 教室 教师`（如 `实验大楼B209-1 陈建全`） | 含字母/数字的 token → 教室；纯中文 token → 教师 |
| 无 `LOCATION` | 从 `DESCRIPTION` 第 2/3 行兜底取 教室/教师 |
| 非每周（DAILY 等）/ 无 RRULE 单次事件 | 跳过并返回 warnings（单次调课不构成每周模板） |

同步结果示例（真实导出 44 个 VEVENT → 13 门课程 / 20 个时间块，幂等）：

```json
{"source_id": 1, "source_type": "ical", "synced_at": "2026-08-17T22:55:00+08:00",
 "fetched": 20, "created": 33, "updated": 0, "skipped": 0, "warnings": []}
```

### 2.4 手动维护兜底

- 课程 / 时间块的既有 CRUD API 全部保留（`POST /api/courses`、`POST /api/courses/{id}/sessions` 等）。
- 同步默认 **merge 模式**：只创建缺失行、补齐空缺字段，**不覆盖**手改的教室/时间（如调课后的手动修正）。
- 需要让 iCal 内容全量覆盖时，请求体加 `"mode": "overwrite"`（仍不删除任何行，删除始终走手动 CRUD）。

## 3. Notion（作业任务 → tasks）

> ⚠️ **接入方式（Issue #26 修正）**：Notion 官方远程 MCP（mcp.notion.com/mcp）
> 不接受自建集成令牌（一律 401），因此本层改为 **REST 直连 api.notion.com**
> （`backend/mcp_client/notion_rest.py`，Bearer 集成令牌 + `Notion-Version` 头）。
> OAuth 端点保留但已非主路径。

### 3.1 绑定（集成令牌，无需 OAuth 流程）

```bash
# 在 Notion 创建集成（https://www.notion.so/my-integrations → New integration），
# 复制令牌（ntn_ 开头），并把集成「连接」到目标数据库（数据库页 ... → Connections）
curl -X POST http://127.0.0.1:8000/api/data-sources \
  -H 'Content-Type: application/json' \
  -d '{"source_type": "notion", "name": "Notion",
       "config": "{\"tokens\": {\"access_token\": \"ntn_你的令牌\"}}"}'
```

### 3.2 同步作业任务

```bash
# config 里需要 database_id（Notion 作业数据库 ID）；也可在同步请求体传 database_id
curl -X POST http://127.0.0.1:8000/api/data-sources/<id>/sync
```

- 直接调 Notion REST `POST /v1/databases/{id}/query`。
- 按 `source_ref`（Notion 页面 ID）**幂等 upsert** 到 `tasks`（source='notion'），更新 title / deadline / status。
- 任务属性名可配置（个人化数据库）：`config.props = {"title": [...], "deadline": [...], "course": [...], "status": [...]}`；
  默认支持中文常用名（标题/截止日期/课程/状态），状态自动归一化到 `todo/doing/done/cancelled`。

## 4. Obsidian（笔记查询，不落库）

- 默认走 `npx obsidian-mcp-server`（stdio JSON-RPC）；工具名可配置（`config.tool_search` 等，默认 `search_note` / `read_note` / `list_all_notes`）。
- 配置 `config.vault_path` 后提供 **直读兜底**：MCP 服务器不可用时直接用 pathlib 在本地 vault 全文搜索 `.md`。
- 只做接入与查询接口；知识点提取算法归知识提取模块，本层不落库。

```bash
# 绑定后带关键词同步（只查询并记录同步时间，不产生业务数据）
curl -X POST http://127.0.0.1:8000/api/data-sources/<id>/sync \
  -H 'Content-Type: application/json' -d '{"query": "极限"}'
```

## 5. 数据源管理 API 速查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/data-sources` | 列表（`?source_type=ical` 过滤） |
| POST | `/api/data-sources` | 绑定数据源 |
| PATCH | `/api/data-sources/{id}` | 更新（含 enabled / config / last_sync_at） |
| POST | `/api/data-sources/{id}/enable` / `disable` | 启用 / 禁用（禁用后同步返回 409） |
| POST | `/api/data-sources/{id}/sync` | 触发同步（iCal 支持 `ics_content` / `mode`） |
| POST | `/api/data-sources/notion/oauth/start` | Notion OAuth 起点（⚠️ 保留但已非主路径，见第 3 节） |
| POST | `/api/data-sources/notion/oauth/callback` | Notion OAuth 回调（兑换 token） |
| DELETE | `/api/data-sources/{id}` | 解绑 |

## 6. 测试（全 mock，无需真实账号/密钥）

- `test_mcp_transport.py`：stdio 假子进程 + streamable HTTP（httpx.MockTransport），覆盖握手 / 工具调用 / 错误 / SSE / session id
- `test_mcp_oauth.py`：PKCE 参数、授权码兑换、refresh、过期判断（MockTransport）
- `test_mcp_ical.py`：教务导出格式合成样例（多 VEVENT 合并 / TZID / DESCRIPTION 兜底 / 跳过规则）
- `test_mcp_notion.py`：Notion 属性映射 / 状态归一化 / 文本 JSON 兜底（fake transport）
- `test_mcp_obsidian.py`：MCP 查询 + vault 直读兜底 + 目录穿越防护
- `test_mcp_sync_api.py`：同步 / 启停 / OAuth 端点（adapter mock，落库真实）

```bash
cd backend
.venv/Scripts/python.exe -m pytest   # 全量 173 例（原 123 + MCP 50）
```
