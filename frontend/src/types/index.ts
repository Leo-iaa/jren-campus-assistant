/**
 * API 类型定义 —— 对齐后端 backend/schemas/*.py 的 Pydantic 契约。
 * 后端字段变化时，优先同步此文件。
 */

/** 课程档位：S 核心 / A 标准 / B 轻量 / C 划水 */
export type Tier = 'S' | 'A' | 'B' | 'C'

export const TIERS: Tier[] = ['S', 'A', 'B', 'C']

export const TIER_LABELS: Record<Tier, string> = {
  S: '核心课程',
  A: '标准课程',
  B: '轻量课程',
  C: '划水课程',
}

export const TIER_REVIEW_SEQ: Record<Tier, number[]> = {
  S: [1, 2, 4, 7, 15],
  A: [1, 2, 4, 7, 15],
  B: [1, 7],
  C: [],
}

// ---------- 课程 ----------

export interface Course {
  id: number
  name: string
  code: string | null
  tier: Tier
  color: string | null
  teacher: string | null
  notes: string | null
  created_at: string
}

export interface CourseSession {
  id: number
  course_id: number
  day_of_week: number // 0=周一 ... 6=周日
  start_time: string // 'HH:MM'
  end_time: string // 'HH:MM'
  location: string | null
  release_slot: number // 0/1：B/C 档该时段是否释放
}

// ---------- 知识点 / 复习计划 ----------

export type ReviewStatus = 'pending' | 'done' | 'skipped' | 'overdue'
export type KnowledgeStatus = 'active' | 'archived'

export interface KnowledgePoint {
  id: number
  course_id: number
  title: string
  content_snapshot: string | null
  difficulty: number // 1-5
  source_path: string | null
  status: KnowledgeStatus
  created_at: string
}

export interface ReviewSchedule {
  id: number
  knowledge_point_id: number
  seq: number // 第几次复习（1,2,3...）
  due_date: string // 'YYYY-MM-DD'
  status: ReviewStatus
  completed_at: string | null
}

// ---------- 作业任务 / 杂事项 ----------

export type TaskStatus = 'todo' | 'doing' | 'done' | 'cancelled'
export type MiscStatus = 'todo' | 'done' | 'cancelled'

export interface Task {
  id: number
  course_id: number | null
  title: string
  description: string | null
  deadline: string | null
  estimated_minutes: number | null
  source: 'notion' | 'manual'
  source_ref: string | null
  status: TaskStatus
  created_at: string
}

export interface MiscItem {
  id: number
  title: string
  duration_minutes: number | null
  preferred_time: string | null
  deadline: string | null
  status: MiscStatus
  created_at: string
}

// ---------- 数据源 ----------

export type DataSourceType = 'notion' | 'obsidian' | 'ical' | 'caldav'

export const DATA_SOURCE_LABELS: Record<DataSourceType, string> = {
  notion: 'Notion',
  obsidian: 'Obsidian',
  ical: 'iCal 课表',
  caldav: 'CalDAV 日历',
}

export interface DataSource {
  id: number
  source_type: DataSourceType
  name: string | null
  config: string | null // JSON 字符串
  enabled: boolean
  last_sync_at: string | null
  created_at: string
}

export interface SyncResult {
  source_id: number
  source_type: string
  synced_at: string
  fetched: number
  created: number
  updated: number
  skipped: number
  warnings: string[]
}

export interface OAuthStartResult {
  source_id: number
  authorization_url: string
}

// ---------- 今日计划（前端聚合） ----------

export type PlanItemType = 'course' | 'task' | 'review' | 'misc' | 'free'

export interface PlanTimelineItem {
  key: string // 稳定唯一 key（用于拖拽排序）
  type: PlanItemType
  start_time: string
  end_time: string
  title: string
  subtitle?: string | null
  /** 复习专用：第几次复习 */
  review_seq?: number
  /** 复习专用：知识点难度 */
  difficulty?: number
  /** 课程专用：档位 */
  tier?: Tier
  /** 课程专用：地点 */
  location?: string | null
  /** 原始引用（course session / task / review / misc 的 id） */
  ref_id?: number | null
  status?: string
}

/** 计划确认/调整状态（暂存 localStorage，后端 plan API 就绪后切换） */
export interface PlanLocalState {
  /** 已确认的日期 'YYYY-MM-DD' */
  confirmedDate: string | null
  /** 用户拖拽调整后的条目 key 顺序 */
  order: string[]
  /** 最后调整时间 */
  adjustedAt: string | null
}

// ---------- 偏好设置 / LLM 配置（暂存 localStorage） ----------

export interface Preferences {
  /** 每日复习上限（默认 8） */
  reviewDailyCap: number
  /** 学习时段 [起, 止]，'HH:MM' */
  studyStart: string
  studyEnd: string
}

export interface LlmConfig {
  provider: 'doubao' | 'deepseek'
  apiKey: string
  endpoint: string
  model: string
}
