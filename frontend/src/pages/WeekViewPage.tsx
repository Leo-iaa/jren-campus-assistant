import { Card } from '../components/Card'
import { WeekGrid } from '../components/WeekGrid'
import { useWeekPlan } from '../hooks/usePlan'
import { weekDates } from '../lib/date'

/** 周视图：7 天网格（课程 + 任务 + 复习点） */
export function WeekViewPage() {
  const { week, loading, error, refresh } = useWeekPlan()
  const dates = weekDates(new Date())

  return (
    <div className="page">
      <header className="page__head">
        <h1 className="page__title">周视图</h1>
        <p className="page__date">
          {dates[0]} ~ {dates[6]}
        </p>
      </header>

      {error && (
        <Card className="card--error">
          <p className="error-text">后端连接失败：{error}</p>
          <button className="btn btn--ghost btn--sm" onClick={refresh}>
            重试
          </button>
        </Card>
      )}

      <Card
        title="本周安排"
        extra={
          <button className="btn btn--ghost btn--sm" onClick={refresh}>
            刷新
          </button>
        }
      >
        {loading ? (
          <p className="muted">正在加载本周安排…</p>
        ) : (
          <WeekGrid
            days={week.map((d, i) => ({ ...d, date: dates[i] }))}
          />
        )}
        <p className="muted legend">
          <span className="legend__item legend__item--course">■ 课程</span>
          <span className="legend__item legend__item--task">■ 作业</span>
          <span className="legend__item legend__item--review">■ 复习点</span>
        </p>
      </Card>
    </div>
  )
}
