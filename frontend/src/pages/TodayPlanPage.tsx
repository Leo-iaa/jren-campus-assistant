import { useMemo } from 'react'
import { Card } from '../components/Card'
import { ConfirmBanner } from '../components/ConfirmBanner'
import { Timeline } from '../components/Timeline'
import { useTodayPlan } from '../hooks/usePlan'
import { applyTimelineOrder } from '../lib/plan'
import { formatDateCn } from '../lib/date'

/** 今日计划页（首页）：确认横幅 + 时间轴 */
export function TodayPlanPage() {
  const {
    date,
    plan,
    state,
    isConfirmed,
    hasAdjusted,
    confirm,
    reset,
    moveItem,
    prefs,
    loading,
    error,
    refresh,
  } = useTodayPlan()

  const items = useMemo(() => {
    if (!plan) return []
    const sorted = applyTimelineOrder(plan.timeline, state.order)
    return sorted
  }, [plan, state.order])

  return (
    <div className="page">
      <header className="page__head">
        <h1 className="page__title">今日计划</h1>
        <p className="page__date">{formatDateCn(new Date())}</p>
      </header>

      {error && (
        <Card className="card--error">
          <p className="error-text">
            后端连接失败：{error}
            <br />
            <span className="muted">
              请确认已启动：<code>uvicorn backend.main:app</code>（仓库根目录）
            </span>
          </p>
          <button className="btn btn--ghost btn--sm" onClick={refresh}>
            重试
          </button>
        </Card>
      )}

      {plan && (
        <ConfirmBanner
          stats={plan.stats}
          isConfirmed={isConfirmed}
          hasAdjusted={hasAdjusted}
          onConfirm={confirm}
          onReset={reset}
        />
      )}

      <Card title="时间轴" extra={<span className="muted">{date}</span>}>
        {loading ? (
          <p className="muted">正在加载今日安排…</p>
        ) : (
          <Timeline items={items} draggable={!isConfirmed} onMove={moveItem} />
        )}
        {!isConfirmed && !loading && plan && plan.timeline.length > 0 && (
          <p className="muted timeline-hint">
            ✏️ 拖拽卡片可调整顺序（自由时间块会自动重新计算）
          </p>
        )}
        {plan && plan.overflow.length > 0 && (
          <div className="overflow">
            <h3 className="panel-title">⚠️ 未排入时段（学习时段放不下）</h3>
            {plan.overflow.map((o) => (
              <div key={o.key} className="overflow__item">
                <span className="overflow__type">
                  {o.type === 'task' ? '作业' : o.type === 'review' ? '复习' : '杂项'}
                </span>
                {o.title}
              </div>
            ))}
          </div>
        )}
      </Card>
      <p className="muted foot-note">
        学习时段 {prefs.studyStart}-{prefs.studyEnd} · 每日复习上限 {prefs.reviewDailyCap} 个（可在设置页修改）
      </p>
    </div>
  )
}
