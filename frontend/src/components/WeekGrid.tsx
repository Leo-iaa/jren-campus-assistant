import { toDateStr, weekdayCn } from '../lib/date'

interface WeekGridProps {
  /** 本周 7 天，周一开头 */
  days: {
    date: string
    courseItems: { id: number; start: string; end: string; name: string; tier: string }[]
    taskItems: { id: number; title: string; status: string }[]
    reviewItems: { id: number; title: string; seq: number; difficulty?: number }[]
  }[]
}

/** 周视图：7 天网格，课程 + 任务 + 复习点 */
export function WeekGrid({ days }: WeekGridProps) {
  const todayStr = toDateStr(new Date())
  return (
    <div className="weekgrid" data-testid="weekgrid">
      {days.map((day) => {
        const dateObj = new Date(`${day.date}T00:00:00`)
        const isToday = day.date === todayStr
        return (
          <div
            key={day.date}
            className={`weekgrid__day${isToday ? ' weekgrid__day--today' : ''}`}
          >
            <header className="weekgrid__head">
              <span className="weekgrid__weekday">{weekdayCn(dateObj)}</span>
              <span className="weekgrid__date">{day.date.slice(5)}</span>
              {isToday && <span className="weekgrid__today">今天</span>}
            </header>
            <div className="weekgrid__body">
              {day.courseItems.length === 0 &&
                day.taskItems.length === 0 &&
                day.reviewItems.length === 0 && (
                  <p className="weekgrid__empty">—</p>
                )}
              {day.courseItems.map((c) => (
                <div key={`c${c.id}`} className="weekgrid__item weekgrid__item--course">
                  <span className="weekgrid__time">
                    {c.start}-{c.end}
                  </span>
                  <span className="weekgrid__text">{c.name}</span>
                  <span className={`badge badge--tier badge--tier-${c.tier}`}>{c.tier}</span>
                </div>
              ))}
              {day.taskItems.map((t) => (
                <div key={`t${t.id}`} className="weekgrid__item weekgrid__item--task">
                  <span className="weekgrid__label">作业</span>
                  <span className="weekgrid__text">{t.title}</span>
                </div>
              ))}
              {day.reviewItems.map((r) => (
                <div key={`r${r.id}`} className="weekgrid__item weekgrid__item--review">
                  <span className="weekgrid__label">🔁 {r.seq}</span>
                  <span className="weekgrid__text">{r.title}</span>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
