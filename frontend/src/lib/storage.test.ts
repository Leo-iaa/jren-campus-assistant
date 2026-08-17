import { describe, expect, it } from 'vitest'
import {
  DEFAULT_PREFERENCES,
  applyOrderMove,
  loadPlanState,
  loadPreferences,
  savePlanState,
  savePreferences,
} from './storage'

describe('storage 本地状态', () => {
  it('偏好设置默认值：复习上限 8，学习时段 08:00-22:00', () => {
    expect(loadPreferences()).toEqual(DEFAULT_PREFERENCES)
  })

  it('保存后能读回（合并默认值）', () => {
    savePreferences({ reviewDailyCap: 12, studyStart: '09:00', studyEnd: '21:00' })
    expect(loadPreferences()).toMatchObject({
      reviewDailyCap: 12,
      studyStart: '09:00',
      studyEnd: '21:00',
    })
  })

  it('计划状态按日期隔离', () => {
    const state = { confirmedDate: '2026-08-17', order: ['a', 'b'], adjustedAt: null }
    savePlanState('2026-08-17', state)
    expect(loadPlanState('2026-08-17').confirmedDate).toBe('2026-08-17')
    expect(loadPlanState('2026-08-18').confirmedDate).toBeNull()
  })

  it('applyOrderMove 把 key 移到 target 前，且去重', () => {
    expect(applyOrderMove(['a', 'b', 'c'], 'c', 'a')).toEqual(['c', 'a', 'b'])
    expect(applyOrderMove(['a', 'b'], 'a', 'c')).toEqual(['b', 'a']) // target 不存在 → 追加
  })
})
