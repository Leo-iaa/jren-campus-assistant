import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { courseApi, knowledgeApi, miscApi, reviewApi, taskApi } from '../api/client'
import { useApi } from './useApi'
import { dayOfWeek, toDateStr } from '../lib/date'
import { buildTimeline, type BuildTimelineResult } from '../lib/plan'
import {
  applyOrderMove,
  loadPlanState,
  loadPreferences,
  savePlanState,
} from '../lib/storage'
import type { PlanLocalState } from '../types'

/** 今日计划：聚合后端数据 + 本地确认/调整状态 */
export function useTodayPlan(now: Date = new Date()) {
  const date = toDateStr(now)
  const dow = dayOfWeek(now)
  const prefs = useMemo(() => loadPreferences(), [date])

  const courses = useApi(() => courseApi.list(), [])
  const tasks = useApi(() => taskApi.list(), [])
  const reviews = useApi(() => reviewApi.list(), [])
  const knowledge = useApi(() => knowledgeApi.list(), [])
  const misc = useApi(() => miscApi.list(), [])

  // 拉取全部课程的全部时间块（courses 就绪后）
  const allSessions = useApi(
    () =>
      courses.data && courses.data.length > 0
        ? Promise.all(courses.data.map((c) => courseApi.sessions(c.id))).then((xs) =>
            xs.flat(),
          )
        : Promise.resolve([]),
    [courses.data],
  )

  const plan = useMemo<BuildTimelineResult | null>(() => {
    if (
      !courses.data ||
      !allSessions.data ||
      !tasks.data ||
      !reviews.data ||
      !knowledge.data ||
      !misc.data
    ) {
      return null
    }
    return buildTimeline({
      date,
      dayOfWeek: dow,
      courses: courses.data,
      sessions: allSessions.data,
      tasks: tasks.data,
      reviews: reviews.data,
      knowledgePoints: knowledge.data,
      miscItems: misc.data,
      studyStart: prefs.studyStart,
      studyEnd: prefs.studyEnd,
      reviewDailyCap: prefs.reviewDailyCap,
    })
  }, [date, dow, prefs.studyStart, prefs.studyEnd, courses.data, allSessions.data, tasks.data, reviews.data, knowledge.data, misc.data])

  // 计划状态（确认/拖拽顺序）
  const [state, setState] = useState<PlanLocalState>(() => loadPlanState(date))
  const [savedAt, setSavedAt] = useState<string | null>(() => {
    const s = loadPlanState(date)
    return s.confirmedDate === date ? s.adjustedAt : null
  })

  const confirm = useCallback(() => {
    const next: PlanLocalState = {
      ...state,
      confirmedDate: date,
      adjustedAt: new Date().toISOString(),
    }
    setState(next)
    savePlanState(date, next)
    setSavedAt(next.adjustedAt)
  }, [state, date])

  const reset = useCallback(() => {
    const next: PlanLocalState = { confirmedDate: null, order: [], adjustedAt: null }
    setState(next)
    savePlanState(date, next)
    setSavedAt(null)
  }, [date])

  /** 计划状态的最新引用（供 moveItem 读取当前值，避免把副作用写进 setState updater） */
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])

  /** 拖拽调整：把 key 移到 targetKey 前面 */
  const moveItem = useCallback(
    (key: string, targetKey: string) => {
      const next: PlanLocalState = {
        ...stateRef.current,
        order: applyOrderMove(stateRef.current.order, key, targetKey),
        adjustedAt: new Date().toISOString(),
      }
      stateRef.current = next
      setState(next)
      savePlanState(date, next)
    },
    [date],
  )

  const isConfirmed = state.confirmedDate === date
  const hasAdjusted = state.order.length > 0

  return {
    date,
    plan,
    state,
    isConfirmed,
    hasAdjusted,
    confirm,
    reset,
    moveItem,
    savedAt,
    prefs,
    loading:
      courses.loading ||
      allSessions.loading ||
      tasks.loading ||
      reviews.loading ||
      knowledge.loading ||
      misc.loading,
    error:
      courses.error ||
      allSessions.error ||
      tasks.error ||
      reviews.error ||
      knowledge.error ||
      misc.error,
    refresh: () => {
      courses.refresh()
      tasks.refresh()
      reviews.refresh()
      knowledge.refresh()
      misc.refresh()
      allSessions.refresh()
    },
  }
}

/** 周视图：7 天聚合（课程按星期几 / 任务按 deadline / 复习按 due_date） */
export function useWeekPlan(anchor: Date = new Date()) {
  const courses = useApi(() => courseApi.list(), [])
  const allSessions = useApi(
    () =>
      courses.data && courses.data.length > 0
        ? Promise.all(courses.data.map((c) => courseApi.sessions(c.id))).then((xs) =>
            xs.flat(),
          )
        : Promise.resolve([]),
    [courses.data],
  )
  const tasks = useApi(() => taskApi.list(), [])
  const reviews = useApi(() => reviewApi.list(), [])
  const knowledge = useApi(() => knowledgeApi.list(), [])

  const courseById = useMemo(
    () => new Map((courses.data ?? []).map((c) => [c.id, c])),
    [courses.data],
  )
  const kpById = useMemo(
    () => new Map((knowledge.data ?? []).map((k) => [k.id, k])),
    [knowledge.data],
  )

  const week = useMemo(() => {
    const days = Array.from({ length: 7 }, () => ({
      date: '',
      courseItems: [] as { id: number; start: string; end: string; name: string; tier: string }[],
      taskItems: [] as { id: number; title: string; status: string }[],
      reviewItems: [] as { id: number; title: string; seq: number; difficulty?: number }[],
    }))
    // 课程：每周重复，按 day_of_week 分布
    for (const s of allSessions.data ?? []) {
      const c = courseById.get(s.course_id)
      days[s.day_of_week].courseItems.push({
        id: s.id,
        start: s.start_time,
        end: s.end_time,
        name: c?.name ?? `课程 #${s.course_id}`,
        tier: c?.tier ?? 'A',
      })
    }
    // 任务：按 deadline 分布
    for (const t of tasks.data ?? []) {
      if (!t.deadline || t.status === 'done' || t.status === 'cancelled') continue
      const idx = weekIndex(t.deadline, anchor)
      if (idx >= 0) days[idx].taskItems.push({ id: t.id, title: t.title, status: t.status })
    }
    // 复习：按 due_date 分布
    for (const r of reviews.data ?? []) {
      if (r.status === 'done' || r.status === 'skipped') continue
      const idx = weekIndex(r.due_date, anchor)
      if (idx >= 0) {
        const kp = kpById.get(r.knowledge_point_id)
        days[idx].reviewItems.push({
          id: r.id,
          title: kp?.title ?? `知识点 #${r.knowledge_point_id}`,
          seq: r.seq,
          difficulty: kp?.difficulty,
        })
      }
    }
    return days
  }, [allSessions.data, tasks.data, reviews.data, courseById, kpById, anchor])

  return {
    week,
    courseById,
    loading:
      courses.loading ||
      allSessions.loading ||
      tasks.loading ||
      reviews.loading ||
      knowledge.loading,
    error:
      courses.error ||
      allSessions.error ||
      tasks.error ||
      reviews.error ||
      knowledge.error,
    refresh: () => {
      courses.refresh()
      tasks.refresh()
      reviews.refresh()
      knowledge.refresh()
      allSessions.refresh()
    },
  }
}

/** 日期是否在本周内（anchor 所在周），返回 0-6，否则 -1 */
function weekIndex(dateStr: string, anchor: Date): number {
  const monday = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() - dayOfWeek(anchor))
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i)
    if (toDateStr(d) === dateStr) return i
  }
  return -1
}
