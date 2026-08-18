# 📘 Jren Campus Assistant 用户使用手册

> 面向非技术用户：**从零开始，跟着做就能跑通**。
> 本手册所有步骤已在全新克隆环境实测验证。完整技术细节见 [docs/mcp-server.md](mcp-server.md) 与 [docs/mcp-client.md](mcp-client.md)。

---

## 1. 这是什么

一个会自动帮你排日程的校园助手：

- 🌙 **每晚 21:00** 自动读取你的课表 / Notion 作业 / Obsidian 笔记，结合遗忘曲线生成**明日计划草案**
- 📱 **早上 08:00** 微信收到今日计划预览
- 💬 在 WorkBuddy（或微信远程）里说一句话就能**确认 / 调整**计划
- 🗓️ 确认后计划自动写入 **Notion Calendar**（手机 / 电脑 / 平板都能看）

---

## 2. 你需要准备什么

| 项目 | 说明 |
|------|------|
| Windows 电脑 | 后端与 WorkBuddy 装同一台电脑（方案 A） |
| Python 3.11+ | 官网 python.org 下载，安装时**勾选 Add to PATH** |
| WorkBuddy | 腾讯 CodeBuddy PC 客户端（官网下载，免费额度） |
| Notion 账号 | 可选但推荐（计划写日历用） |
| git | 可选（不会用 git 可以直接在 GitHub 页面下载 ZIP） |

---

## 3. 快速上手（三步）

```text
第一步：克隆 + 安装 + 初始化数据库     （约 5 分钟）
第二步：启动后端 + 开机自启            （约 2 分钟）
第三步：WorkBuddy 连接 + 配定时任务    （约 5 分钟）
```

---

## 4. 详细步骤

> 💻 **先分清你的终端**：窗口标题写着 **Windows PowerShell** 就用 PowerShell 命令；写着 **命令提示符（CMD）** 就用 CMD 命令。本手册两者都给。

### 4.1 获取代码

**方式 A（推荐，用 git）：**

```bash
git clone https://github.com/Leo-iaa/jren-campus-assistant.git
cd jren-campus-assistant
```

**方式 B（不会 git）：** GitHub 仓库页面 → 绿色 `Code` 按钮 → `Download ZIP` → 解压，进入解压出的文件夹。

> 💡 以下命令都在**仓库根目录**（含 `backend/`、`README.md` 的那个文件夹）的终端里执行。

### 4.2 安装后端依赖

```bash
cd backend
python -m venv .venv
```

**激活虚拟环境**（激活成功后命令行最前面会出现 `(.venv)`）：

**PowerShell**（推荐）：

```powershell
.\.venv\Scripts\Activate.ps1
```

> 若提示「无法加载文件…禁止运行脚本」：先执行 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`，输入 `Y` 确认，再重新激活。

**CMD（命令提示符）**：

```cmd
.venv\Scripts\activate
```

> macOS / Linux 用 `source .venv/bin/activate`。
> 不想激活的话，把后面所有 `python` 换成 `.\.venv\Scripts\python.exe`（PowerShell）或 `.venv\Scripts\python.exe`（CMD）即可，效果一样。

```bash
pip install -r requirements.txt
```

### 4.3 初始化数据库

```bash
# 回到仓库根目录
cd ..
python -m backend.scripts.init_db
```

看到"初始化完成"即成功。此命令**可以重复执行**（幂等，不会破坏数据）。

### 4.4 验证安装（可选）

```bash
cd backend
python -m pytest
```

应看到 `215 passed`。

### 4.5 启动后端

```bash
cd ..   # 回到仓库根目录
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

验证是否成功（另开一个终端或浏览器）：

```
浏览器打开 http://127.0.0.1:8000/health
看到 {"status":"ok","database":"connected"} 即正常
```

接口文档（Swagger UI）：`http://127.0.0.1:8000/docs`

> ⚠️ 窗口别关，关了服务就停了。想省事请看下一节的开机自启。

### 4.6 开机自启（强烈推荐）

1. 按 `Win + R`，输入下面路径后回车，打开启动文件夹：
   ```
   %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
   ```
2. 把仓库里的 `backend/scripts/start_backend_hidden.vbs` **复制**进去
3. 以后每次开机登录，后端自动在后台启动（不弹黑窗口）

**怎么知道后端在不在跑？** 浏览器打开 `http://127.0.0.1:8000/health`，能看到 ok 就是在跑；打不开就双击 `start_backend.bat` 手动启动。

### 4.7 配置 Notion（可选，但推荐）

计划确认后写入 Notion Calendar，需要三步：

**① 创建集成并拿令牌**
- 打开 https://www.notion.so/my-integrations → `New integration` → 填名称 → 创建
- 复制令牌（`ntn_` 开头的一长串）

**② 建日程数据库**
- Notion 里新建页面 → 模板选**「日程」**（Calendar）
- 确认数据库包含三个属性：**名称**（标题）、**日期**（含时间）、**类型**（选择）
- 记下数据库 ID：打开该数据库，URL 里 `.../数据库ID?v=...` 那段 32 位字符串

**③ 把集成连到数据库**
- 打开数据库页面 → 右上角 `⋯` → `Connections` → 添加你的集成

**④ 绑定到后端**（后端运行中，两种方式任选）：

- **方式一（推荐，图形界面，不用敲命令）**：浏览器打开 `http://127.0.0.1:8000/docs` → 找到 `POST /api/data-sources` → 点 **Try it out** → 请求体填：

```json
{
  "source_type": "notion",
  "name": "Notion",
  "config": "{\"tokens\":{\"access_token\":\"ntn_你的令牌\"}}"
}
```

→ 点 **Execute**，返回 `200` 即绑定成功。

- **方式二（命令行）**：⚠️ PowerShell 必须写 `curl.exe`（`curl` 是别名，语法不兼容）：

```bash
curl.exe -X POST http://127.0.0.1:8000/api/data-sources -H "Content-Type: application/json" -d "{\"source_type\":\"notion\",\"name\":\"Notion\",\"config\":\"{\\\"tokens\\\":{\\\"access_token\\\":\\\"ntn_你的令牌\\\"}}\"}"
```

**⑤ 告诉后端日历数据库 ID**：设置环境变量 `JREN_NOTION_CALENDAR_DB=你的数据库ID`，然后重启后端。

### 4.8 WorkBuddy 连接 MCP

1. 打开 WorkBuddy → **设置 → MCP 服务**（或「MCP 管理」）→ 添加服务器
2. 填写：
   - 名称：随意（如 `jren-campus-assistant`）
   - 类型：**http**（Streamable HTTP）
   - 地址：`http://127.0.0.1:8000/mcp`
3. 连接成功后，问 WorkBuddy：**「查询课程列表」**——能返回结果就说明联调成功 ✅

### 4.9 WorkBuddy 定时任务（核心自动化）

用 WorkBuddy 的**「自动化」**功能创建两个定时任务：

| 任务 | 触发时间 | 调用工具 | 效果 |
|------|---------|---------|------|
| 生成次日计划 | 每天 21:00 | `generate_tomorrow_plan` | 微信收到「明日计划已生成，记得睡前确认」 |
| 推送今日计划 | 每天 08:00 | `get_today_plan_preview` | 微信收到今日完整时间表 |

建议的自动化指令文本（创建任务时填写）：

```
每天 21:00：调用 jren-campus-assistant 的 generate_tomorrow_plan 工具生成次日计划，
把返回的 JSON 总结成一句话发给用户（如「明天的计划已生成，共 6 项，睡前记得确认」）。
```

```
每天 08:00：调用 get_today_plan_preview 工具，把返回的文本原样推送给我。
```

> 💡 微信推送前，先在 WorkBuddy 里完成 IM 接入（微信 / 企业微信等）。

---

## 5. 日常使用（大白话）

```
🌙 21:00  微信收到「明日计划已生成」
          · 想调整：跟 WorkBuddy 说「把高数作业挪到晚上」
          · 确认：说「确认明天的计划」→ 自动写入 Notion 日历
☀️ 08:00  微信收到今日计划预览
📱 白天   打开 Notion Calendar 看时间表；完成一项就跟 WorkBuddy 说「标记 XX 完成」
🔄 长期   系统记录你的「预估 vs 实际」耗时，越用越准
```

**8 个 MCP 工具一览**（WorkBuddy 里可直接调用）：

| 工具 | 作用 |
|------|------|
| `generate_tomorrow_plan` | 生成次日计划草案 |
| `get_today_plan_preview` | 今日计划文本（微信友好） |
| `confirm_plan` | 确认计划 → 写入 Notion 日历 |
| `adjust_plan_item` | 调整单项时间 / 标题 |
| `mark_done` | 标记完成（触发耗时校准） |
| `get_courses` / `get_tasks` / `get_reviews` | 查询课程 / 作业 / 复习 |

---

## 6. 常见问题（FAQ）

**Q：`http://127.0.0.1:8000/health` 打不开？**
A：后端没在运行。双击 `backend/scripts/start_backend.bat` 手动启动，或重启电脑让自启生效。

**Q：WorkBuddy 提示连不上 MCP？**
A：① 先确认 `/health` 能打开；② MCP 地址是否为 `http://127.0.0.1:8000/mcp`；③ 类型是否选了 **http**。WorkBuddy 装在其他设备时改用 `http://<电脑IP>:8000/mcp`，并确认防火墙放行 8000 端口。

**Q：确认计划后 Notion 日历没写入？**
A：看 `confirm_plan` 返回的 `notion_sync` 字段：`null` = 没绑定 Notion 数据源；报错 = 按提示排查（令牌无效 / 缺数据库 ID / 属性名不匹配）。

**Q：数据库初始化会不会清掉我的数据？**
A：不会。`init_db` 是幂等的：已存在的表不会重建，只补建缺失的表。

**Q：电脑关机了定时任务还跑吗？**
A：不跑。21:00 的生成由电脑上的后端兜底任务负责（APScheduler），开机后 1 小时内会补跑；08:00 微信推送由 WorkBuddy 定时任务负责，同样需要电脑开机。这是「方案 A 本地部署」的固有约束。

**Q：更多问题？**
A：完整版见 [docs/mcp-server.md](mcp-server.md) 第 10 节（含局域网 IP 变化、鉴权说明、时间显示等）。

---

## 7. 想深入了解？

| 文档 | 内容 |
|------|------|
| [docs/mcp-server.md](mcp-server.md) | MCP 工具清单、WorkBuddy 配置、Notion 日历写入细节 |
| [docs/mcp-client.md](mcp-client.md) | 数据源绑定（课表 iCal / Obsidian / Notion） |
| [docs/architecture.md](architecture.md) | 整体架构 |
| [docs/vision.md](vision.md) | 产品设计与决策（课程档位制等） |
| [docs/database.md](database.md) | 数据库设计 |

---

*遇到任何问题，欢迎在仓库 Issues 里提问。*
