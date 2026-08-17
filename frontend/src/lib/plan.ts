/**
 * 今日计划聚合：把课程时间块 / 任务 / 复习 / 杂项聚合成时间轴。
 *
 * 说明：后端目前没有 plan API（计划由「规划器」生成并落库），
 * 此处为前端侧的简易确定性规划（启发式填空），逻辑与后端
 * backend/scheduler/planner.py 对齐；后端 plan API 就绪后，
 * 此模块可替换为直接读取后端计划结果，UI 无需改动。
 */
import type {
  Course,
  CourseSession,
  KnowledgePoint,
  MiscItem,
  PlanTimelineItem,
  ReviewSchedule,
  Task,
} from '../types'
import { timeToMinutes } from './date'

export interface BuildTimelineInput {
  /** 计划日期 'YYYY-MM-DD' */
  date: string
  /** 该日期的星期几 0=周一...6=周日（与后端一致） */
  dayOfWeek: number
  courses: Course[]
  sessions: CourseSession[]
  tasks: Task[]
  reviews: ReviewSchedule[]
  knowledgePoints: KnowledgePoint[]
  miscItems: MiscItem[]
  /** 学习时段起始（默认 08:00） */
  studyStart?: string
  /** 学习时段结束（默认 22:00） */
  studyEnd?: string
  /** 最短自由时间展示阈值（分钟，默认 30） */
  minFreeMinutes?: number
}

export interface BuildTimelineResult {
  timeline: PlanTimelineItem[]
  /** 已安排条目的统计 */
  stats: {
    courseCount: number
    taskCount: number
    reviewCount: number
    miscCount: number
    freeMinutes: number
  }
  /** 放不进学习时段的待办（显示在时间轴底部） */
  overflow: PlanTimelineItem[]
}

interface TimeBlock {
  start: number // 分钟
  end: number // 分钟
}

const DEFAULT_TASK_MINUTES = 60
const DEFAULT_MISC_MINUTES = 30

function toBlock(item: PlanTimelineItem): TimeBlock {
  return { start: timeToMinutes(item.start_time), end: timeToMinutes(item.end_time) }
}

/** 任务是否应出现在今日计划中（今天到期 或 进行中） */
export function taskDueToday(task: Task, date: string): boolean {
  if (task.status === 'done' || task.status === 'cancelled') return false
  if (task.deadline === date) return true
  if (task.status === 'doing') return true
  return false
}

/** 复习是否应出现在今日计划中（今天到期且未完成） */
export function reviewDueToday(review: ReviewSchedule, date: string): boolean {
  if (review.due_date !== date) return false
  return review.status === 'pending' || review.status === 'overdue'
}

/**
 * 前端简易规划器：
 * 1. 固定项：当日课程 / 当日复习 / 带时间的杂项 → 占位
 * 2. 空闲块 = 学习时段减去固定项占用
 * 3. 灵活项：到期/进行中任务、无时间杂项 → 按预估时长填入最早空闲块
 * 4. 生成自由时间条目（≥ minFreeMinutes），返回排序后的时间轴
 */
export function buildTimeline(input: BuildTimelineInput): BuildTimelineResult {
  const {
    date,
    dayOfWeek: dow,
    courses,
    sessions,
    tasks,
    reviews,
    knowledgePoints,
    miscItems,
    studyStart = '08:00',
    studyEnd = '22:00',
    minFreeMinutes = 30,
  } = input

  const courseById = new Map(courses.map((c) => [c.id, c]))
  const kpById = new Map(knowledgePoints.map((k) => [k.id, k]))

  // 1. 固定项
  const fixed: PlanTimelineItem[] = []

  for (const s of sessions) {
    if (s.day_of_week !== dow) continue
    const course = courseById.get(s.course_id)
    fixed.push({
      key: `course:${s.id}`,
      type: 'course',
      start_time: s.start_time,
      end_time: s.end_time,
      title: course?.name ?? `课程 #${s.course_id}`,
      subtitle: s.location,
      location: s.location,
      tier: course?.tier,
      ref_id: s.id,
    })
  }

  for (const r of reviews) {
    if (!reviewDueToday(r, date)) continue
    const kp = kpById.get(r.knowledge_point_id)
    fixed.push({
      key: `review:${r.id}`,
      type: 'review',
      // 复习点无固定时刻：先不占位，作为灵活项安排；这里仅用于统计
      start_time: '',
      end_time: '',
      title: kp?.title ?? `知识点 #${r.knowledge_point_id}`,
      review_seq: r.seq,
      difficulty: kp?.difficulty,
      ref_id: r.id,
      status: r.status,
    })
  }

  for (const m of miscItems) {
    if (m.status === 'done' || m.status === 'cancelled') continue
    if (!m.preferred_time) continue
    fixed.push({
      key: `misc:${m.id}`,
      type: 'misc',
      start_time: m.preferred_time,
      end_time: '',
      title: m.title,
      ref_id: m.id,
      status: m.status,
    })
  }

  // 复习与带时间杂项补全 end_time
  for (const item of fixed) {
    if (!item.end_time) {
      const dur =
        item.type === 'misc'
          ? (miscItems.find((m) => m.id === item.ref_id)?.duration_minutes ??
            DEFAULT_MISC_MINUTES)
          : 25 // 复习点默认 25 分钟
      item.end_time = formatEnd(item.start_time, dur)
    }
  }

  // 2. 空闲块
  const busy = fixed.filter((f) => f.type === 'course').map(toBlock)
  const freeBlocks = subtractBlocks(
    { start: timeToMinutes(studyStart), end: timeToMinutes(studyEnd) },
    busy,
  )

  // 3. 灵活项：到期/进行中任务（deadline 压力优先）→ 复习 → 无时间杂项
  const flexible: PlanTimelineItem[] = [
    ...tasks.filter((t) => taskDueToday(t, date)).map((t) => ({
      key: `task:${t.id}`,
      type: 'task' as const,
      start_time: '',
      end_time: '',
      title: t.title,
      subtitle: t.estimated_minutes
        ? `预计 ${t.estimated_minutes} 分钟`
        : t.description,
      ref_id: t.id,
      status: t.status,
    })),
    ...fixed.filter((f) => f.type === 'review'),
    ...miscItems
      .filter((m) => m.status !== 'done' && m.status !== 'cancelled' && !m.preferred_time)
      .map((m) => ({
        key: `misc:${m.id}`,
        type: 'misc' as const,
        start_time: '',
        end_time: '',
        title: m.title,
        ref_id: m.id,
        status: m.status,
      })),
  ]

  const overflow: PlanTimelineItem[] = []
  const scheduled: PlanTimelineItem[] = []
  let freeIndex = 0

  for (const item of flexible) {
    const dur =
      item.type === 'task'
        ? (tasks.find((t) => t.id === item.ref_id)?.estimated_minutes ??
          DEFAULT_TASK_MINUTES)
        : item.type === 'review'
          ? 25
          : (miscItems.find((m) => m.id === item.ref_id)?.duration_minutes ??
            DEFAULT_MISC_MINUTES)
    const slot = freeBlocks[freeIndex]
    if (slot && slot.end - slot.start >= dur) {
      item.start_time = formatStart(slot.start)
      item.end_time = formatEnd(item.start_time, dur)
      slot.start += dur
      scheduled.push(item)
    } else {
      freeIndex += 1
      const next = freeBlocks[freeIndex]
      if (next && next.end - next.start >= dur) {
        item.start_time = formatStart(next.start)
        item.end_time = formatEnd(item.start_time, dur)
        next.start += dur
        scheduled.push(item)
      } else {
        overflow.push(item)
      }
    }
  }

  // 4. 生成自由时间条目 + 排序
  const timeline = [...scheduled, ...fixed.filter((f) => f.type === 'course')].sort(
    (a, b) => timeToMinutes(a.start_time) - timeToMinutes(b.start_time),
  )

  let freeMinutes = 0
  const freeItems: PlanTimelineItem[] = []
  for (const block of freeBlocks) {
    if (block.end - block.start >= minFreeMinutes) {
      freeMinutes += block.end - block.start
      freeItems.push({
        key: `free:${formatStart(block.start)}-${formatStart(block.end)}`,
        type: 'free',
        start_time: formatStart(block.start),
        end_time: formatStart(block.end),
        title: '自由时间',
        subtitle: `可安排 · ${block.end - block.start} 分钟`,
      })
    }
  }

  const all = [...timeline, ...freeItems].sort(
    (a, b) => timeToMinutes(a.start_time) - timeToMinutes(b.start_time),
  )

  return {
    timeline: all,
    stats: {
      courseCount: timeline.filter((t) => t.type === 'course').length,
      taskCount: scheduled.filter((t) => t.type === 'task').length,
      reviewCount: scheduled.filter((t) => t.type === 'review').length,
      miscCount: scheduled.filter((t) => t.type === 'misc').length,
      freeMinutes,
    },
    overflow,
  }
}

function subtractBlocks(outer: TimeBlock, busy: TimeBlock[]): TimeBlock[] {
  const sorted = [...busy].sort((a, b) => a.start - b.start)
  const free: TimeBlock[] = []
  let cursor = outer.start
  for (const b of sorted) {
    if (b.end <= cursor) continue
    if (b.start > outer.end) break
    if (b.start > cursor) {
      free.push({ start: cursor, end: Math.min(b.start, outer.end) })
    }
    cursor = Math.max(cursor, b.end)
  }
  if (cursor < outer.end) free.push({ start: cursor, end: outer.end })
  return free
}

function formatStart(min: number): string {
  return `${String(Math.floor(min / 60)).padStart(2, '0')}:${String(min % 60).padStart(2, '0')}`
}

function formatEnd(start: string, durMinutes: number): string {
  const total = timeToMinutes(start) + durMinutes
  return formatStart(total)
}

/**
 * 应用用户拖拽顺序：非自由条目按 order 排列（未记录的按原时间），
 * 自由时间条目始终按时间插入（不参与拖拽）。
 */
export function applyTimelineOrder(
  timeline: PlanTimelineItem[],
  order: string[],
): PlanTimelineItem[] {
  const free = timeline
    .filter((t) => t.type === 'free')
    .sort((a, b) => timeToMinutes(a.start_time) - timeToMinutes(b.start_time))
  const nonFree = timeline.filter((t) => t.type !== 'free')
  const idxOf = (k: string) => {
    const i = order.indexOf(k)
    return i === -1 ? Number.MAX_SAFE_INTEGER : i
  }
  const ordered = [...nonFree].sort(
    (a, b) => idxOf(a.key) - idxOf(b.key) || timeToMinutes(a.start_time) - timeToMinutes(b.start_time),
  )
  // 按开始时间归并两序列
  const merged: PlanTimelineItem[] = []
  let i = 0
  let j = 0
  while (i < ordered.length && j < free.length) {
    if (timeToMinutes(ordered[i].start_time) <= timeToMinutes(free[j].start_time)) {
      merged.push(ordered[i])
      i += 1
    } else {
      merged.push(free[j])
      j += 1
    }
  }
  return [...merged, ...ordered.slice(i), ...free.slice(j)]
}
