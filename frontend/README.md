# J人校园助手 · 前端（frontend/）

React + Vite + TypeScript + PWA 三页面前端，对接后端 FastAPI（`/api/*`）。

## 功能页面

| 页面 | 路由 | 说明 |
|------|------|------|
| 今日计划 | `/`（首页） | AI 计划确认横幅（✅ 确认 / ✏️ 拖拽调整）+ 时间轴（课程 / 作业 / 复习 / 自由时间），复习点标注 🔁 与第几次 |
| 周视图 | `/#/week` | 7 天网格：课程 + 任务 + 复习点，今天高亮 |
| 设置 | `/#/settings` | 数据源绑定（Notion OAuth / Obsidian / iCal）、课程档位管理（S/A/B/C）、偏好设置（每日复习上限、学习时段）、LLM 配置（豆包 / DeepSeek） |

> 说明：应用使用 HashRouter（`#/`），PWA 静态托管无需服务端 rewrite。

## 启动方式

### 0. 环境要求

- Node.js 18+（开发验证使用 v24）
- 后端服务已启动（仓库根目录）：

```bash
cd jren-campus-assistant
python -m backend.scripts.init_db   # 首次需初始化数据库
uvicorn backend.main:app            # 默认 127.0.0.1:8000
```

### 1. 安装依赖

```bash
cd frontend
npm install
```

### 2. 开发模式

```bash
npm run dev
# 打开 http://localhost:5173
```

后端地址默认 `http://127.0.0.1:8000`，如需修改，创建 `frontend/.env.local`：

```bash
VITE_API_BASE=http://127.0.0.1:8000
```

### 3. 生产构建 / 预览

```bash
npm run build      # 类型检查 + 打包（含 PWA service worker）
npm run preview    # 本地预览构建产物
```

构建产物在 `frontend/dist/`，为 PWA（可安装到安卓主屏幕：浏览器菜单 →「添加到主屏幕」）。

### 4. 测试

```bash
npm run test       # Vitest + Testing Library（组件与纯函数测试）
```

### 5. 造演示数据（可选）

```bash
# 需要后端运行中；通过 API 造课程/时间块/知识点/复习/任务/杂项示例
python scripts/seed_demo.py
```

## 与后端的对接约定

- API 客户端集中在 `src/api/client.ts`，类型对齐后端 `backend/schemas/*.py`（`src/types/index.ts`）。
- **已真实对接**：课程 / 课程时间块 / 知识点 / 复习计划 / 任务 / 杂项 / 数据源（含同步、启停、Notion OAuth）。
- **本地状态先行**：后端暂无 plan / settings API（models 已有 `plan_items` / `plan_versions` / `settings` 表但未暴露路由），因此：
  - 今日计划时间轴 = 前端聚合（`src/lib/plan.ts` 简易确定性规划，启发式填空：固定课程 → 空闲块 → 任务/复习/杂项，任务优先于复习，自由时间 ≥30 分钟展示）
  - 计划确认 / 拖拽调整顺序、偏好设置、LLM 配置存 localStorage（`src/lib/storage.ts`）
  - 后端补 plan/settings 路由后，只需替换 `src/hooks/usePlan.ts` 的数据来源与 `src/lib/storage.ts` 的读写，UI 无需改动

## 目录结构

```text
frontend/
├── src/
│   ├── api/           # API 客户端（fetch 封装，统一错误处理）
│   ├── components/    # 卡片 / 时间轴 / 确认横幅 / 周网格 / 设置面板等
│   ├── hooks/         # useApi / useTodayPlan / useWeekPlan
│   ├── lib/           # 纯函数：日期工具 / 计划聚合 / 本地存储
│   ├── pages/         # 今日计划 / 周视图 / 设置 / Notion OAuth 回调
│   ├── styles/        # 全局样式（卡片风，移动优先）
│   ├── test/          # 测试 setup 与数据工厂
│   └── types/         # 后端契约类型
├── scripts/           # gen_icons.py（PWA 图标）、seed_demo.py（演示数据）
├── icons/             # PWA 图标（192/512 PNG + SVG）
└── vite.config.ts     # Vite + PWA 插件 + Vitest 配置
```
