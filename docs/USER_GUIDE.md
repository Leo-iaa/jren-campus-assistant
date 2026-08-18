# 📘 Jren Campus Assistant 用户使用手册

> 面向非技术用户：**全程只需要双击和点击，不需要敲任何命令**。
> 遇到任何看不懂的报错，截图发给维护者即可。

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
| Windows 电脑 | 后端与 WorkBuddy 装在同一台电脑 |
| WorkBuddy | 腾讯 CodeBuddy PC 客户端（官网下载，免费额度） |
| Notion 账号 | 可选但推荐（计划写日历用） |

> 环境配置（Python、依赖、数据库）全部由一键脚本自动完成，**不需要你手动安装任何开发环境**。

---

## 3. 快速上手（三步）

```text
第一步：双击 setup.bat          一键安装（自动完成所有环境配置，几分钟）
第二步：双击 start_backend.bat  启动服务
第三步：WorkBuddy 连接 + 配定时任务
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

### 4.5 配置 Notion（可选，但推荐）

计划确认后写入 Notion Calendar，需要四步（全在网页/记事本里操作）：

**① 创建集成拿令牌**
- 打开 https://www.notion.so/my-integrations → `New integration` → 创建 → 复制令牌（`ntn_` 开头）

**② 建日程数据库**
- Notion 里新建页面 → 模板选**「日程」**（Calendar）
- 确认包含三个属性：**名称**（标题）、**日期**（含时间）、**类型**（选择）
- 打开该数据库，从网址里记下 32 位**数据库 ID**

**③ 把集成连到数据库**
- 数据库页面 → 右上角 `⋯` → `Connections` → 添加你的集成

**④ 一键绑定（只需要两串码）**
- 双击 `backend\scripts\config_notion.bat`
- 按提示粘贴两串码：① 集成令牌（`ntn_` 开头）② 日程数据库 ID
- 看到「绑定成功」即完成 ✅
- 脚本自动完成：检查服务 → 绑定数据源（已有则自动更新）→ 写入日历数据库 ID，不用再手动操作接口

### 4.6 WorkBuddy 连接 MCP

1. 打开 WorkBuddy → **设置 → MCP 服务** → 添加服务器
2. 填写：
   - 名称：随意（如 `jren-campus-assistant`）
   - 类型：**http**（Streamable HTTP）
   - 地址：`http://127.0.0.1:8000/mcp`
3. 连接成功后，问 WorkBuddy：**「查询课程列表」**——能返回结果就说明联调成功 ✅

### 4.7 WorkBuddy 定时任务（核心自动化）

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

## 5. 日常使用

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
