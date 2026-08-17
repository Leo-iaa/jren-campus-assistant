/**
 * 本地状态存储（localStorage 封装）。
 *
 * 说明：后端暂无 plan / settings API，计划确认/调整与偏好设置先落本地；
 * 后端路由就绪后，将对应读写替换为 API 调用（见 api/client.ts 的注释）。
 */
import type { LlmConfig, PlanLocalState, Preferences } from '../types'

const PREFIX = 'jren:'

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    if (raw === null) return fallback
    return { ...fallback, ...(JSON.parse(raw) as Partial<T>) }
  } catch {
    return fallback
  }
}

function write(key: string, value: unknown): void {
  localStorage.setItem(PREFIX + key, JSON.stringify(value))
}

// ---------- 偏好设置 ----------

export const DEFAULT_PREFERENCES: Preferences = {
  reviewDailyCap: 8,
  studyStart: '08:00',
  studyEnd: '22:00',
}

export function loadPreferences(): Preferences {
  return read<Preferences>('preferences', DEFAULT_PREFERENCES)
}

export function savePreferences(prefs: Preferences): void {
  write('preferences', prefs)
}

// ---------- LLM 配置 ----------

export const DEFAULT_LLM: LlmConfig = {
  provider: 'doubao',
  apiKey: '',
  endpoint: '',
  model: 'doubao-1-5-pro-32k',
}

export function loadLlmConfig(): LlmConfig {
  return read<LlmConfig>('llm', DEFAULT_LLM)
}

export function saveLlmConfig(config: LlmConfig): void {
  write('llm', config)
}

// ---------- 计划确认/调整状态 ----------

const EMPTY_PLAN_STATE: PlanLocalState = {
  confirmedDate: null,
  order: [],
  adjustedAt: null,
}

export function loadPlanState(date: string): PlanLocalState {
  const state = read<PlanLocalState>(`plan:${date}`, EMPTY_PLAN_STATE)
  return state
}

export function savePlanState(date: string, state: PlanLocalState): void {
  write(`plan:${date}`, state)
}

/** 记录一次拖拽调整（把 key 插入到 target 前） */
export function applyOrderMove(
  order: string[],
  key: string,
  targetKey: string,
): string[] {
  const next = order.filter((k) => k !== key)
  const idx = next.indexOf(targetKey)
  if (idx === -1) return [...next, key]
  next.splice(idx, 0, key)
  return next
}
