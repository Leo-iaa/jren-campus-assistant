# 📘 Jren Campus Assistant 用户使用手册

> 面向非技术用户：**全程只需要双击和点击，不需要敲任何命令**。
> 遇到任何看不懂的报错，截图发给维护者即可。

---

## 1. 这是什么

一个会自动帮你排日程的校园助手：

- 🌙 **每晚 21:00** 自动读取你的课表 / Notion 作业 / Obsidian 笔记，结合遗忘曲线生成**明日计划草案**
- 📱 **早上 08:00** 微信收到今日计划预览
- 📥 **微信说一句话就能添加任务**（如「有新任务：高数作业，ddl 是明天」）→ 自动写进任务库 + 排进日程
- 💬 在 WorkBuddy（或微信远程）里说一句话就能**确认 / 调整**计划
- 🗓️ 确认后计划自动写入 **Notion Calendar**（手机 / 电脑 / 平板都能看）

---

## 2. 你需要准备什么

| 项目 | 说明 |
|------|------|
| Windows 电脑 | 后端与 WorkBuddy 装在同一台电脑 |
| WorkBuddy | 腾讯 CodeBuddy PC 客户端（官网下载，免费额度） |
| Notion 账号 | 可选但推荐（计划写日历用） |

> 环境配置（Python、依赖、数据库）全部由一键脚本自动完成，**不需要你手动安装任何开发环境**。

---

## 3. 快速上手（三步）

```text
第一步：双击 setup.bat          一键安装（自动完成所有环境配置，几分钟）
第二步：双击 start_backend.bat  启动服务
第三步：导入课表 + 配置 Notion（双击两个脚本，各粘贴一串码）
第四步：WorkBuddy 连接 + 配定时任务
```

---

## 4. 详细步骤

### 4.1 获取代码

**方式一（最简单）：下载 ZIP**
- GitHub 仓库页面 → 绿色 **Code** 按钮 → **Download ZIP** → 解压到任意位置（比如桌面）

**方式二：git 克隆**（熟悉 git 的人可选）

```bash
git clone https://github.com/Leo-iaa/jren-campus-assistant.git
```

### 4.2 一键安装

1. 进入仓库文件夹（解压出的文件夹）
2. **双击 `setup.bat`**
3. 耐心等待（约 3-5 分钟），窗口显示 `Setup complete!` 即安装完成

> 安装过程全自动：检查环境 → 配置依赖 → 初始化数据库。任何一步失败窗口里都会显示中文提示。

### 4.3 启动服务

1. **双击 `backend\scripts\start_backend.bat`**
2. 验证是否成功：浏览器打开 `http://127.0.0.1:8000/health`
3. 看到 `{"status":"ok",...}` 就是成功了 ✅

> 接口页面（可看可点）：浏览器打开 `http://127.0.0.1:8000/docs`

### 4.4 开机自启（强烈推荐）

1. 按 `Win + R`，输入下面路径，回车打开启动文件夹：
   ```
   %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
   ```
2. 把仓库里的 `backend\scripts\start_backend_hidden.vbs` **复制**进去
3. 以后每次开机登录，服务自动在后台启动，不用手动双击

**服务在不在跑？** 浏览器打开 `http://127.0.0.1:8000/health`，能看到 ok 就是在跑。

### 4.5 导入课表（必须做）

1. 从教务系统导出课表（`.ics` 文件，如「2026春夏.ics」）
2. **双击 `backend\scripts\config_ical.bat`**
3. 把 `.ics` 文件**拖进窗口**（或粘贴完整路径）后回车
4. 看到「同步完成」即导入成功 ✅（课程和上课时间自动写入系统）

> 导入后每门课默认为 **A 档**；课程档位（S/A/B/C）的设置脚本即将提供。

### 4.6 配置 Notion（可选，但推荐）

计划确认后写入 Notion Calendar、微信添加任务写入任务库，需要四步（全在网页/记事本里操作）：

**① 创建集成拿令牌**
- 打开 https://www.notion.so/my-integrations → `New integration` → 创建 → 复制令牌（`ntn_` 开头）

**② 建两个数据库**
- **日程数据库**：Notion 里新建页面 → 模板选**「日程」**（Calendar）
  - 确认包含三个属性：**名称**（标题）、**日期**（含时间）、**类型**（选择）
- **任务数据库**：再新建页面 → 模板选**「任务列表」**（Tasks）
  - 确认包含属性：**任务名称**（标题）、**截止日期**、**当前状态**
  - （可选）加一个「类型」选择属性（作业/实验/考试/其他），不加也行——系统会跳过它
- 打开数据库，从网址里记下 32 位**数据库 ID**（也可以不记——第④步直接粘贴整条链接，脚本会自动提取；粘贴**页面链接**也能自动找到里面的数据库）

**③ 把集成连到数据库**
- 每个数据库页面 → 右上角 `⋯` → `Connections` → 添加你的集成

**④ 一键绑定（只需要几串码）**
- 双击 `backend\scripts\config_notion.bat`
- 按提示粘贴：① 集成令牌（`ntn_` 开头）② 日程数据库 ID/链接 ③ 任务数据库 ID/链接（可跳过）
- 已有配置可以**直接回车沿用**（令牌 / 库 ID 不用重新输入）
- 看到「绑定成功」即完成 ✅
- 脚本自动完成：检查服务 → 绑定数据源（已有则自动更新）→ 写入两个库 ID，不用再手动操作接口

### 4.7 WorkBuddy 连接 MCP

1. 打开 WorkBuddy → **设置 → MCP 服务** → 添加服务器
2. 填写：
   - 名称：随意（如 `jren-campus-assistant`）
   - 类型：**http**（Streamable HTTP）
   - 地址：`http://127.0.0.1:8000/mcp`
3. 连接成功后，问 WorkBuddy：**「查询课程列表」**——能返回结果就说明联调成功 ✅

### 4.8 WorkBuddy 定时任务（核心自动化）

> ✅ **微信推送已实测跑通**（2026-08-25）：安装 `wechat-clawbot-push` 桥后，自动化结果会**直接发到微信聊天窗口**（ClawBot），不用再走企业微信/小程序。

**第一步：接通微信推送**（只需一次）
1. 在 WorkBuddy 里安装 `wechat-clawbot-push`（PyPI 上的微信推送桥，stdio MCP，暴露 `push_wechat_message` 工具），并按它的说明注册到 MCP 配置
2. 首次授权：让 WorkBuddy 调用 `acquire_token` 获取 token——**提示出现后立刻用手机微信给 ClawBot 发任意一条消息**（约 35 秒内），token 就绑定成功了
3. 验证：让它发一条测试消息，微信收到即通 ✅（多个定时任务共用同一个 token）

**第二步：创建两个定时任务**

| 任务 | 触发时间 | 调用工具 | 效果 |
|------|---------|---------|------|
| 生成明日计划 | 每天 21:00 | `generate_tomorrow_plan`（auto_confirm=true） | **自动排好明天** + 写入 Notion 日历 + 微信收到完整时间表 |
| 推送今日计划 | 每天 08:20 | `get_today_plan_preview` | 微信收到今日完整时间表 |

建议的自动化指令文本（创建任务时填写，**已实测可用**）：

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

> 21:00 任务里 `auto_confirm=true` 是**免确认**开关：生成后直接确认并写入 Notion 日历，
> 不需要睡前手动确认了（Issue #58）。

---

## 5. 日常使用

```
🌙 21:00  微信自动收到「明日计划」（已自动确认并写入 Notion 日历）
          · 临时有事：跟 WorkBuddy 说「把高数作业挪到晚上」→ 调整同步到日历
          · 新任务：说「有新任务：XXX，ddl 是明天」→ 自动入库并排日程
☀️ 08:20  微信收到今日计划预览
📱 白天   打开 Notion Calendar 看时间表；完成一项就跟 WorkBuddy 说「标记 XX 完成」
🔄 长期   系统记录你的「预估 vs 实际」耗时，越用越准
```

**9 个 MCP 工具一览**（WorkBuddy 里可直接调用）：

| 工具 | 作用 |
|------|------|
| `generate_tomorrow_plan` | 生成次日计划（`auto_confirm=true` 时自动确认并写日历，免睡前确认） |
| `get_today_plan_preview` | 今日计划文本（微信友好） |
| `confirm_plan` | 确认计划 → 写入 Notion 日历 |
| `adjust_plan_item` | 调整单项时间 / 标题（已确认的日程会自动同步 Notion 日历） |
| `add_task` | **一句话添加任务**（写本地 + Notion 任务库，自动排日程） |
| `mark_done` | 标记完成（触发耗时校准） |
| `get_courses` / `get_tasks` / `get_reviews` | 查询课程 / 作业 / 复习 |

**微信一句话加任务**（需要先配置任务库，见 4.6 节）：

```
给 WorkBuddy 发：有新任务：高数作业，ddl 是明天，类型是作业
WorkBuddy 回复：已添加任务「高数作业」；已安排到今天 20:00-21:00
```

---

## 6. 常见问题（FAQ）

**Q：`http://127.0.0.1:8000/health` 打不开？**
A：服务没在运行。双击 `backend\scripts\start_backend.bat` 手动启动；如果还不行，重启电脑让开机自启生效。

**Q：WorkBuddy 提示连不上 MCP？**
A：① 先确认 `http://127.0.0.1:8000/health` 能打开（服务在跑）；② 检查 MCP 地址是否 `http://127.0.0.1:8000/mcp`、类型是否 **http**；③ WorkBuddy 装在其他设备时改用 `http://<电脑IP>:8000/mcp` 并确认防火墙放行。

**Q：确认计划后 Notion 日历没写入？**
A：看 `confirm_plan` 返回的 `notion_sync` 字段：`null` = 没绑定 Notion 数据源；报错 = 按提示排查（令牌无效 / 缺数据库 ID / 属性名不匹配）。

**Q：电脑关机了定时任务还跑吗？**
A：不跑。21:00 生成由电脑上的服务负责，08:00 推送由 WorkBuddy 定时任务负责——都需要电脑开机。这是「本地部署」方案的固有约束。

**Q：setup.bat 或启动时报错了？**
A：直接截图发给维护者，把报错窗口完整截图即可。

**Q：更多技术细节？**
A：见 [docs/mcp-server.md](mcp-server.md)（工具清单 / Notion 日历 / 排查）。

---

## 7. 想深入了解？

| 文档 | 内容 |
|------|------|
| [docs/mcp-server.md](mcp-server.md) | MCP 工具、WorkBuddy 配置、Notion 日历写入细节 |
| [docs/mcp-client.md](mcp-client.md) | 数据源绑定（课表 iCal / Obsidian / Notion） |
| [docs/architecture.md](architecture.md) | 整体架构 |
| [docs/vision.md](vision.md) | 产品设计与决策（课程档位制等） |
| [docs/database.md](database.md) | 数据库设计 |

---

*遇到任何问题，欢迎在仓库 Issues 里提问。*
