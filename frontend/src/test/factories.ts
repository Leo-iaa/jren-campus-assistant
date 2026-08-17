import type {
  Course,
  CourseSession,
  KnowledgePoint,
  MiscItem,
  ReviewSchedule,
  Task,
} from '../types'

/** 测试数据工厂：构造最小合法对象 */

export function makeCourse(overrides: Partial<Course> = {}): Course {
  return {
    id: 1,
    name: '高等数学',
    code: 'MATH101',
    tier: 'A',
    color: null,
    teacher: null,
    notes: null,
    created_at: '2026-08-17T00:00:00',
    ...overrides,
  }
}

export function makeSession(overrides: Partial<CourseSession> = {}): CourseSession {
  return {
    id: 1,
    course_id: 1,
    day_of_week: 0, // 周一
    start_time: '08:00',
    end_time: '09:40',
    location: '教一 101',
    release_slot: 0,
    ...overrides,
  }
}

export function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 1,
    course_id: 1,
    title: '作业：导数练习',
    description: null,
    deadline: '2026-08-17',
    estimated_minutes: 60,
    source: 'manual',
    source_ref: null,
    status: 'todo',
    created_at: '2026-08-17T00:00:00',
    ...overrides,
  }
}

export function makeKp(overrides: Partial<KnowledgePoint> = {}): KnowledgePoint {
  return {
    id: 1,
    course_id: 1,
    title: '极限的定义',
    content_snapshot: null,
    difficulty: 3,
    source_path: null,
    status: 'active',
    created_at: '2026-08-17T00:00:00',
    ...overrides,
  }
}

export function makeReview(overrides: Partial<ReviewSchedule> = {}): ReviewSchedule {
  return {
    id: 1,
    knowledge_point_id: 1,
    seq: 1,
    due_date: '2026-08-17',
    status: 'pending',
    completed_at: null,
    ...overrides,
  }
}

export function makeMisc(overrides: Partial<MiscItem> = {}): MiscItem {
  return {
    id: 1,
    title: '取快递',
    duration_minutes: 30,
    preferred_time: null,
    deadline: null,
    status: 'todo',
    created_at: '2026-08-17T00:00:00',
    ...overrides,
  }
}
