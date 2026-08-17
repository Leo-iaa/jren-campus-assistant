/**
 * 日期/时间工具（全部为纯函数，便于测试）。
 */

const WEEKDAY_CN = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

/** Date -> 'YYYY-MM-DD'（本地时区） */
export function toDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** 'YYYY-MM-DD' -> Date（本地时区零点） */
export function fromDateStr(s: string): Date {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}

/** 星期几：0=周一 ... 6=周日（与后端 day_of_week 对齐） */
export function dayOfWeek(d: Date): number {
  return (d.getDay() + 6) % 7
}

export function weekdayCn(d: Date): string {
  return WEEKDAY_CN[dayOfWeek(d)]
}

/** 中文日期标题，如「2026年8月17日 周一」 */
export function formatDateCn(d: Date): string {
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${weekdayCn(d)}`
}

/** 本周（含今天）的 7 个日期字符串，周一开头 */
export function weekDates(anchor: Date = new Date()): string[] {
  const dow = dayOfWeek(anchor)
  const monday = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() - dow)
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i)
    return toDateStr(d)
  })
}

/** 'HH:MM' -> 分钟数 */
export function timeToMinutes(t: string): number {
  const [h, m] = t.split(':').map(Number)
  return h * 60 + m
}

/** 分钟数 -> 'HH:MM' */
export function minutesToTime(min: number): string {
  const h = Math.floor(min / 60)
  const m = min % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

/** 判断一个时间段是否与另一个重叠（含端点相接视为不重叠） */
export function overlaps(
  aStart: string,
  aEnd: string,
  bStart: string,
  bEnd: string,
): boolean {
  return timeToMinutes(aStart) < timeToMinutes(bEnd) && timeToMinutes(bStart) < timeToMinutes(aEnd)
}

/** 'YYYY-MM-DD' 是否等于今天 */
export function isToday(dateStr: string, now: Date = new Date()): boolean {
  return dateStr === toDateStr(now)
}

/** 计划是否逾期：due_date 早于今天 */
export function isOverdue(dateStr: string, now: Date = new Date()): boolean {
  return dateStr < toDateStr(now)
}
