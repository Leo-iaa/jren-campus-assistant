import type {
  Course,
  CourseSession,
  DataSource,
  DataSourceType,
  KnowledgePoint,
  MiscItem,
  OAuthStartResult,
  ReviewSchedule,
  ReviewStatus,
  SyncResult,
  Task,
  TaskStatus,
  Tier,
} from '../types'

/** 后端 API 基础地址：优先 .env 的 VITE_API_BASE，默认本地后端 */
const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://127.0.0.1:8000'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // 非 JSON 响应，保留默认信息
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const json = (method: string) => (body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
})

// ---------- 课程 ----------

export const courseApi = {
  list: (tier?: Tier) =>
    request<Course[]>(`/api/courses${tier ? `?tier=${tier}` : ''}`),
  create: (payload: Partial<Course>) =>
    request<Course>('/api/courses', { ...json('POST')(payload) }),
  update: (id: number, payload: Partial<Course>) =>
    request<Course>(`/api/courses/${id}`, { ...json('PATCH')(payload) }),
  remove: (id: number) => request<void>(`/api/courses/${id}`, json('DELETE')()),
  sessions: (courseId: number) =>
    request<CourseSession[]>(`/api/courses/${courseId}/sessions`),
  createSession: (courseId: number, payload: Partial<CourseSession>) =>
    request<CourseSession>(`/api/courses/${courseId}/sessions`, {
      ...json('POST')(payload),
    }),
}

// ---------- 知识点 / 复习计划 ----------

export const knowledgeApi = {
  list: (courseId?: number) =>
    request<KnowledgePoint[]>(
      `/api/knowledge-points${courseId ? `?course_id=${courseId}` : ''}`,
    ),
  create: (payload: Partial<KnowledgePoint>) =>
    request<KnowledgePoint>('/api/knowledge-points', {
      ...json('POST')(payload),
    }),
  update: (id: number, payload: Partial<KnowledgePoint>) =>
    request<KnowledgePoint>(`/api/knowledge-points/${id}`, {
      ...json('PATCH')(payload),
    }),
}

export const reviewApi = {
  list: (status?: ReviewStatus) =>
    request<ReviewSchedule[]>(
      `/api/review-schedules${status ? `?status=${status}` : ''}`,
    ),
  update: (id: number, payload: Partial<ReviewSchedule>) =>
    request<ReviewSchedule>(`/api/review-schedules/${id}`, {
      ...json('PATCH')(payload),
    }),
}

// ---------- 作业任务 / 杂事项 ----------

export const taskApi = {
  list: (status?: TaskStatus) =>
    request<Task[]>(`/api/tasks${status ? `?status=${status}` : ''}`),
  create: (payload: Partial<Task>) =>
    request<Task>('/api/tasks', { ...json('POST')(payload) }),
  update: (id: number, payload: Partial<Task>) =>
    request<Task>(`/api/tasks/${id}`, { ...json('PATCH')(payload) }),
}

export const miscApi = {
  list: () => request<MiscItem[]>('/api/misc-items'),
  create: (payload: Partial<MiscItem>) =>
    request<MiscItem>('/api/misc-items', { ...json('POST')(payload) }),
  update: (id: number, payload: Partial<MiscItem>) =>
    request<MiscItem>(`/api/misc-items/${id}`, { ...json('PATCH')(payload) }),
}

// ---------- 数据源 ----------

export const dataSourceApi = {
  list: () => request<DataSource[]>('/api/data-sources'),
  create: (payload: {
    source_type: DataSourceType
    name?: string
    config?: string
  }) => request<DataSource>('/api/data-sources', { ...json('POST')(payload) }),
  update: (id: number, payload: Partial<DataSource>) =>
    request<DataSource>(`/api/data-sources/${id}`, {
      ...json('PATCH')(payload),
    }),
  remove: (id: number) =>
    request<void>(`/api/data-sources/${id}`, json('DELETE')()),
  enable: (id: number) =>
    request<DataSource>(`/api/data-sources/${id}/enable`, json('POST')()),
  disable: (id: number) =>
    request<DataSource>(`/api/data-sources/${id}/disable`, json('POST')()),
  sync: (id: number, payload?: { mode?: 'merge' | 'overwrite' }) =>
    request<SyncResult>(`/api/data-sources/${id}/sync`, {
      ...json('POST')(payload ?? {}),
    }),
  notionOauthStart: (payload?: {
    source_id?: number
    redirect_uri?: string
  }) =>
    request<OAuthStartResult>('/api/data-sources/notion/oauth/start', {
      ...json('POST')(payload ?? {}),
    }),
  notionOauthCallback: (payload: {
    source_id: number
    code: string
    state: string
  }) =>
    request<{ source_id: number; ok: boolean }>(
      '/api/data-sources/notion/oauth/callback',
      { ...json('POST')(payload) },
    ),
}

export { API_BASE }
