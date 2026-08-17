import { describe, expect, it } from 'vitest'
import {
  dayOfWeek,
  formatDateCn,
  isOverdue,
  isToday,
  minutesToTime,
  overlaps,
  timeToMinutes,
  toDateStr,
  weekDates,
  weekdayCn,
} from './date'

describe('date 工具', () => {
  it('toDateStr 输出 YYYY-MM-DD', () => {
    expect(toDateStr(new Date(2026, 7, 17))).toBe('2026-08-17')
  })

  it('dayOfWeek：周一=0 ... 周日=6（与后端对齐）', () => {
    // 2026-08-17 是周一
    expect(dayOfWeek(new Date(2026, 7, 17))).toBe(0)
    expect(dayOfWeek(new Date(2026, 7, 23))).toBe(6)
  })

  it('weekdayCn 中文星期', () => {
    expect(weekdayCn(new Date(2026, 7, 17))).toBe('周一')
  })

  it('formatDateCn 中文日期', () => {
    expect(formatDateCn(new Date(2026, 7, 17))).toBe('2026年8月17日 周一')
  })

  it('weekDates 返回周一开头的 7 天', () => {
    // 2026-08-19 是周三 → 周一应是 08-17
    const dates = weekDates(new Date(2026, 7, 19))
    expect(dates).toHaveLength(7)
    expect(dates[0]).toBe('2026-08-17')
    expect(dates[6]).toBe('2026-08-23')
  })

  it('timeToMinutes / minutesToTime 互逆', () => {
    expect(timeToMinutes('08:30')).toBe(510)
    expect(minutesToTime(510)).toBe('08:30')
    expect(minutesToTime(1440)).toBe('24:00')
  })

  it('overlaps 判断时间段重叠（端点相接不算重叠）', () => {
    expect(overlaps('08:00', '09:00', '08:30', '10:00')).toBe(true)
    expect(overlaps('08:00', '09:00', '09:00', '10:00')).toBe(false)
    expect(overlaps('08:00', '09:00', '07:00', '08:00')).toBe(false)
  })

  it('isToday / isOverdue', () => {
    const now = new Date(2026, 7, 17)
    expect(isToday('2026-08-17', now)).toBe(true)
    expect(isToday('2026-08-18', now)).toBe(false)
    expect(isOverdue('2026-08-16', now)).toBe(true)
    expect(isOverdue('2026-08-17', now)).toBe(false)
  })
})
