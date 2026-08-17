# 数据库设计：Jren Campus Assistant

> 单用户起步，SQLite；多用户时平滑迁移 PostgreSQL（表结构基本兼容）。
> 本设计对应 `docs/architecture.md` 后端各模块（MCP 接入 / 提取 / 调度 / 规划 / 校准）。

## 1. 设计原则

- **单用户**：不建 users 表，全局配置用 `settings` 键值表
- **多态引用**：日程计划项 `plan_items` 通过 `item_type + ref_id` 引用课程块 / 任务 / 复习 / 杂项，冗余 `title` 便于展示查询
- **冲突兜底**：`UNIQUE(date, start_time)` 让数据库本身拒绝时间冲突，作为时间表规划器的最后防线
- **校准分桶**：`calibration_stats` 只存聚合统计（样本数 + 修正系数），不存明细，保持简单
- **外键级联**：删除课程 → 级联删除时间块 / 知识点 / 复习计划；删除知识点 → 级联删除复习计划

## 2. ER 关系总览

```text
settings ──────────── 全局键值配置（复习上限、学习时段、LLM 等）

courses 1───N course_sessions      课程 + 每周时间块（含 B/C 档释放标记）
courses 1───N knowledge_points     知识点（难度 1-5，关联笔记来源）
knowledge_points 1───N review_schedules  复习计划（第 N 次复习、到期日、状态）
courses 1───N tasks                作业任务（Notion 导入 / 手动创建）

course_sessions ─┐
tasks            ├── 被 plan_items 多态引用（item_type + ref_id）
review_schedules ┘
misc_items ───────── 杂事项（独立表，也被 plan_items 引用）

data_sources ────── 数据源绑定（Notion OAuth / Obsidian vault / iCal）
calibration_stats ─ 课程 × 时段 × 难度 分桶校准统计
plan_versions ───── 每日计划确认快照（版本化）
```

## 3. 表结构（DDL）

### 3.1 `settings` —— 全局配置（单用户）

```sql
CREATE TABLE settings (
  id    INTEGER PRIMARY KEY,
  key   TEXT UNIQUE NOT NULL,   -- 如 review_daily_cap / study_hours / llm_provider
  value TEXT NOT NULL
);
```

### 3.2 `courses` —— 课程

```sql
CREATE TABLE courses (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,                     -- 课程名（如：高数）
  code       TEXT,                              -- 课程代码（可选）
  tier       TEXT NOT NULL DEFAULT 'A'
             CHECK (tier IN ('S','A','B','C')), -- 课程档位（产品决策）
  color      TEXT,                              -- 界面显示颜色
  teacher    TEXT,
  notes      TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 3.3 `course_sessions` —— 课程时间块（每周重复）

```sql
CREATE TABLE course_sessions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id     INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  day_of_week   INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6), -- 0=周一
  start_time    TEXT NOT NULL,                -- '08:00'
  end_time      TEXT NOT NULL,
  location      TEXT,
  release_slot  INTEGER NOT NULL DEFAULT 0,   -- B/C 档：该时段是否释放给其他任务
  UNIQUE (course_id, day_of_week, start_time)
);
```

### 3.4 `knowledge_points` —— 知识点（从笔记提取）

```sql
CREATE TABLE knowledge_points (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id       INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  title           TEXT NOT NULL,              -- 知识点名称
  content_snapshot TEXT,                      -- 原始笔记片段
  difficulty      INTEGER NOT NULL DEFAULT 3
                  CHECK (difficulty BETWEEN 1 AND 5),
  source_path     TEXT,                       -- Obsidian 笔记路径
  status          TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','archived')),
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 3.5 `review_schedules` —— 复习计划（每知识点多条）

```sql
CREATE TABLE review_schedules (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  knowledge_point_id INTEGER NOT NULL
                     REFERENCES knowledge_points(id) ON DELETE CASCADE,
  seq                INTEGER NOT NULL,        -- 第几次复习（1,2,3...）
  due_date           TEXT NOT NULL,           -- 计划复习日期
  status             TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','done','skipped','overdue')),
  completed_at       TEXT,
  UNIQUE (knowledge_point_id, seq)
);
```

### 3.6 `tasks` —— 作业任务（Notion 导入 / 手动）

```sql
CREATE TABLE tasks (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id         INTEGER REFERENCES courses(id) ON DELETE SET NULL,
  title             TEXT NOT NULL,
  description       TEXT,
  deadline          TEXT,                     -- 截止时间
  estimated_minutes INTEGER,                  -- 预估耗时（供规划器使用）
  source            TEXT NOT NULL DEFAULT 'manual'
                    CHECK (source IN ('notion','manual')),
  source_ref        TEXT,                     -- Notion 页面 ID 等
  status            TEXT NOT NULL DEFAULT 'todo'
                    CHECK (status IN ('todo','doing','done','cancelled')),
  created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 3.7 `plan_items` —— 日程计划项（核心表）

```sql
CREATE TABLE plan_items (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  date       TEXT NOT NULL,                   -- 哪一天（YYYY-MM-DD）
  start_time TEXT NOT NULL,
  end_time   TEXT NOT NULL,
  item_type  TEXT NOT NULL
             CHECK (item_type IN ('course','task','review','misc')),
  ref_id     INTEGER,                         -- 对应各来源表的 id（多态引用）
  title      TEXT NOT NULL,                   -- 冗余标题，便于展示
  status     TEXT NOT NULL DEFAULT 'draft'
             CHECK (status IN ('draft','confirmed','done','skipped','adjusted')),
  UNIQUE (date, start_time)                   -- 时间冲突兜底
);
```

### 3.8 `misc_items` —— 杂事项

```sql
CREATE TABLE misc_items (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  title            TEXT NOT NULL,
  duration_minutes INTEGER,                   -- 预计耗时
  preferred_time   TEXT,                      -- 偏好时段（可选）
  deadline         TEXT,
  status           TEXT NOT NULL DEFAULT 'todo'
                   CHECK (status IN ('todo','done','cancelled')),
  created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 3.9 `data_sources` —— 数据源绑定

```sql
CREATE TABLE data_sources (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  source_type TEXT NOT NULL
              CHECK (source_type IN ('notion','obsidian','ical','caldav')),
  name        TEXT,
  config      TEXT,                           -- JSON：OAuth token / vault 路径 / URL
  enabled     INTEGER NOT NULL DEFAULT 1,
  last_sync_at TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 3.10 `calibration_stats` —— 自适应校准分桶

```sql
CREATE TABLE calibration_stats (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id    INTEGER REFERENCES courses(id),
  time_bucket  TEXT,                          -- 'morning' | 'afternoon' | 'evening'
  difficulty   INTEGER,                       -- 1-5 或 NULL（任务类）
  item_type    TEXT NOT NULL,                 -- 'task' | 'review'
  sample_count INTEGER NOT NULL DEFAULT 0,
  ratio_sum    REAL NOT NULL DEFAULT 0,       -- 实际/预估 比值累计
  factor       REAL NOT NULL DEFAULT 1.0,     -- 修正系数 = ratio_sum / sample_count
  UNIQUE (course_id, time_bucket, difficulty, item_type)
);
```

### 3.11 `plan_versions` —— 每日计划确认快照（可选增强）

```sql
CREATE TABLE plan_versions (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  date         TEXT NOT NULL,
  version      INTEGER NOT NULL DEFAULT 1,
  payload      TEXT NOT NULL,                 -- 计划 JSON 快照
  confirmed_at TEXT,
  UNIQUE (date, version)
);
```

## 4. 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 用户模型 | 无 users 表，`settings` 键值 | 单用户起步，多用户时再引入 |
| 计划项多态 | `item_type + ref_id` + 冗余 `title` | 展示查询一条 SQL 完成；SQLite 单用户下可接受 |
| 时间冲突 | `UNIQUE(date, start_time)` | 数据库层兜底，约束求解器出错也不产生重叠 |
| 课程时间块 | 独立表而非 JSON 字段 | 可查询、可释放（`release_slot`）、未来支持调课 |
| 校准统计 | 分桶聚合而非明细 | 表小、查询快；明细可后续补日志表 |
| 复习计划 | 每知识点一行一个 seq | 状态独立（跳过/逾期），支持拖后重排 |
| 外键策略 | 课程删除级联，任务置 NULL | 课程没了知识点复习全清；任务保留兜底 |
| 时间格式 | TEXT（ISO-8601 局部） | SQLite 无原生时间类型，文本可排序可比较 |

## 5. 后续演进

- **多用户**：加 `users` 表，所有业务表加 `user_id` 外键 + 复合索引
- **PostgreSQL**：TEXT 日期可直接迁移为 `DATE` / `TIMESTAMP`；`CHECK` 约束兼容
- **明细审计**：需要时新增 `execution_logs` 明细表，`calibration_stats` 作为物化聚合
