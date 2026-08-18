import { describe, expect, it } from 'vitest'
import {
  applyTimelineOrder,
  buildTimeline,
  reviewDueToday,
  taskDueToday,
  type BuildTimelineInput,
} from './plan'
import {
  makeCourse,
  makeKp,
  makeMisc,
  makeReview,
  makeSession,
  makeTask,
} from '../test/factories'

function baseInput(overrides: Partial<BuildTimelineInput> = {}): BuildTimelineInput {
  return {
    date: '2026-08-17', // 周一
    dayOfWeek: 0,
    courses: [makeCourse()],
    sessions: [],
    tasks: [],
    reviews: [],
    knowledgePoints: [],
    miscItems: [],
    ...overrides,
  }
}

describe('taskDueToday / reviewDueToday', () => {
  it('今天到期的未完成任务算今日；已完成/已取消不算', () => {
    expect(taskDueToday(makeTask(), '2026-08-17')).toBe(true)
    expect(taskDueToday(makeTask({ deadline: '2026-08-18' }), '2026-08-17')).toBe(false)
    expect(taskDueToday(makeTask({ status: 'done' }), '2026-08-17')).toBe(false)
    expect(taskDueToday(makeTask({ status: 'doing', deadline: null }), '2026-08-17')).toBe(true)
  })

  it('复习点：due 今天且未完成才算', () => {
    expect(reviewDueToday(makeReview(), '2026-08-17')).toBe(true)
    expect(reviewDueToday(makeReview({ due_date: '2026-08-18' }), '2026-08-17')).toBe(false)
    expect(reviewDueToday(makeReview({ status: 'done' }), '2026-08-17')).toBe(false)
  })
})

describe('buildTimeline 时间轴聚合', () => {
  it('课程按星期几过滤并显示档位/地点', () => {
    const result = buildTimeline(
      baseInput({
        sessions: [
          makeSession({ id: 1, day_of_week: 0, start_time: '08:00', end_time: '09:40' }),
          // 周二课程不应出现在周一
          makeSession({ id: 2, day_of_week: 1, start_time: '10:00', end_time: '11:40' }),
        ],
      }),
    )
    const courses = result.timeline.filter((t) => t.type === 'course')
    expect(courses).toHaveLength(1)
    expect(courses[0]).toMatchObject({
      title: '高等数学',
      tier: 'A',
      location: '教一 101',
      start_time: '08:00',
      end_time: '09:40',
    })
    expect(result.stats.courseCount).toBe(1)
  })

  it('任务塞入课程后的空闲时段，复习点标注第几次', () => {
    const result = buildTimeline(
      baseInput({
        sessions: [makeSession({ start_time: '08:00', end_time: '09:40' })],
        tasks: [makeTask({ id: 1, title: '作业：导数练习', estimated_minutes: 60 })],
        reviews: [makeReview({ id: 1, seq: 2, knowledge_point_id: 1 })],
        knowledgePoints: [makeKp({ id: 1, title: '极限的定义', difficulty: 4 })],
        studyStart: '08:00',
        studyEnd: '12:00',
      }),
    )
    const task = result.timeline.find((t) => t.type === 'task')
    expect(task).toBeDefined()
    // 空闲从 09:40 开始，任务 60 分钟 → 09:40-10:40
    expect(task?.start_time).toBe('09:40')
    expect(task?.end_time).toBe('10:40')
    const review = result.timeline.find((t) => t.type === 'review')
    expect(review?.review_seq).toBe(2)
    expect(review?.difficulty).toBe(4)
    expect(result.stats.taskCount).toBe(1)
    expect(result.stats.reviewCount).toBe(1)
  })

  it('超出学习时段的灵活项进入 overflow，不进入时间轴', () => {
    const result = buildTimeline(
      baseInput({
        sessions: [makeSession({ start_time: '08:00', end_time: '11:40' })],
        tasks: [makeTask({ id: 1, estimated_minutes: 60 })],
        studyStart: '08:00',
        studyEnd: '12:00',
      }),
    )
    // 课程 08:00-11:40，剩余 20 分钟 < 60 → 放不下
    expect(result.overflow).toHaveLength(1)
    expect(result.overflow[0].type).toBe('task')
    expect(result.timeline.some((t) => t.type === 'task')).toBe(false)
  })

  it('自由时间块：≥30 分钟的空闲生成 free 条目', () => {
    const result = buildTimeline(
      baseInput({
        sessions: [makeSession({ start_time: '08:00', end_time: '09:00' })],
        studyStart: '08:00',
        studyEnd: '12:00',
        minFreeMinutes: 30,
      }),
    )
    const free = result.timeline.filter((t) => t.type === 'free')
    expect(free.length).toBeGreaterThanOrEqual(1)
    expect(free[0].start_time).toBe('09:00')
    expect(result.stats.freeMinutes).toBe(180)
  })

  it('C 档课程 + release_slot：课程照常展示（释放逻辑由后端规划器负责）', () => {
    const result = buildTimeline(
      baseInput({
        courses: [makeCourse({ tier: 'C' })],
        sessions: [makeSession({ release_slot: 1, start_time: '14:00', end_time: '15:00' })],
      }),
    )
    const course = result.timeline.find((t) => t.type === 'course')
    expect(course?.tier).toBe('C')
  })

  it('带时间的杂项进入时间轴并占用空闲时段', () => {
    const result = buildTimeline(
      baseInput({
        sessions: [makeSession({ start_time: '08:00', end_time: '09:00' })],
        miscItems: [
          makeMisc({ id: 1, title: '取快递', preferred_time: '10:00', duration_minutes: 30 }),
        ],
        studyStart: '08:00',
        studyEnd: '12:00',
      }),
    )
    const misc = result.timeline.find((t) => t.type === 'misc' && t.title === '取快递')
    expect(misc).toBeDefined()
    expect(misc?.start_time).toBe('10:00')
    expect(misc?.end_time).toBe('10:30')
    expect(result.stats.miscCount).toBe(1)
    // 定时杂项占用空闲：课程 08:00-09:00 + 杂项 10:00-10:30，剩余自由时间不含该段
    const free = result.timeline.filter((t) => t.type === 'free')
    expect(free.some((f) => f.start_time === '10:00')).toBe(false)
  })

  it('超出每日复习上限的复习点进入 overflow 并标注顺延', () => {
    const result = buildTimeline(
      baseInput({
        reviews: [
          makeReview({ id: 1, knowledge_point_id: 1 }),
          makeReview({ id: 2, knowledge_point_id: 2 }),
          makeReview({ id: 3, knowledge_point_id: 3 }),
        ],
        knowledgePoints: [
          makeKp({ id: 1, title: '知识点A' }),
          makeKp({ id: 2, title: '知识点B' }),
          makeKp({ id: 3, title: '知识点C' }),
        ],
        reviewDailyCap: 2,
      }),
    )
    expect(result.stats.reviewCount).toBe(2)
    const deferred = result.overflow.filter((t) => t.type === 'review')
    expect(deferred).toHaveLength(1)
    expect(deferred[0].subtitle).toContain('顺延')
  })

  it('first-fit：任务可跳过多个小块落入后续大块（此前会误入 overflow）', () => {
    const result = buildTimeline(
      baseInput({
        sessions: [
          makeSession({ id: 1, start_time: '08:00', end_time: '09:00' }),
          makeSession({ id: 2, start_time: '09:30', end_time: '10:00' }),
          makeSession({ id: 3, start_time: '10:30', end_time: '11:00' }),
        ],
        tasks: [makeTask({ id: 1, title: '45 分钟作业', estimated_minutes: 45 })],
        studyStart: '08:00',
        studyEnd: '12:00',
      }),
    )
    const task = result.timeline.find((t) => t.type === 'task')
    expect(task).toBeDefined()
    expect(task?.start_time).toBe('11:00')
    expect(result.overflow).toHaveLength(0)
  })
})

describe('applyTimelineOrder 拖拽顺序', () => {
  const items = [
    { key: 'course:1', type: 'course' as const, start_time: '08:00', end_time: '09:00', title: 'A' },
    { key: 'task:1', type: 'task' as const, start_time: '09:30', end_time: '10:30', title: 'B' },
    { key: 'free:11:00-12:00', type: 'free' as const, start_time: '11:00', end_time: '12:00', title: '自由' },
  ]

  it('order 指定后按 order 排列，未记录的按时间', () => {
    const ordered = applyTimelineOrder(items, ['task:1', 'course:1'])
    expect(ordered.map((i) => i.key)).toEqual(['task:1', 'course:1', 'free:11:00-12:00'])
  })

  it('自由时间条目不参与排序，始终按时间插入', () => {
    const ordered = applyTimelineOrder(items, ['task:1'])
    // task 被排到最前，course 其次，free 仍按时间位
    expect(ordered.map((i) => i.key)).toEqual(['task:1', 'course:1', 'free:11:00-12:00'])
  })

  it('空 order 保持原时间序', () => {
    const ordered = applyTimelineOrder(items, [])
    expect(ordered.map((i) => i.key)).toEqual(['course:1', 'task:1', 'free:11:00-12:00'])
  })
})
