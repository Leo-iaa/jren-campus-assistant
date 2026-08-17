import type { BuildTimelineResult } from '../lib/plan'

interface ConfirmBannerProps {
  stats: BuildTimelineResult['stats']
  isConfirmed: boolean
  hasAdjusted: boolean
  onConfirm: () => void
  onReset: () => void
}

/**
 * AI 计划确认横幅：
 * - 未确认：展示「AI 已生成今日计划」摘要 + ✅ 确认 / ✏️ 拖拽调整提示
 * - 已确认：绿色状态 + 撤销
 */
export function ConfirmBanner({
  stats,
  isConfirmed,
  hasAdjusted,
  onConfirm,
  onReset,
}: ConfirmBannerProps) {
  const summary = [
    stats.courseCount > 0 && `${stats.courseCount} 节课`,
    stats.taskCount > 0 && `${stats.taskCount} 项作业`,
    stats.reviewCount > 0 && `${stats.reviewCount} 个复习点`,
    stats.freeMinutes > 0 && `${Math.round(stats.freeMinutes / 60 * 10) / 10} 小时自由时间`,
  ]
    .filter(Boolean)
    .join(' · ')

  if (isConfirmed) {
    return (
      <div className="banner banner--confirmed" role="status">
        <span className="banner__icon" aria-hidden>
          ✅
        </span>
        <div className="banner__text">
          <strong>今日计划已确认</strong>
          {hasAdjusted && <span className="banner__hint">（已拖拽调整）</span>}
          <div className="banner__summary">{summary || '今日无安排'}</div>
        </div>
        <button className="btn btn--ghost btn--sm" onClick={onReset}>
          撤销确认
        </button>
      </div>
    )
  }

  return (
    <div className="banner banner--ai">
      <span className="banner__icon" aria-hidden>
        🤖
      </span>
      <div className="banner__text">
        <strong>AI 已生成今日计划</strong>
        <div className="banner__summary">{summary || '今日暂无安排'}</div>
        <div className="banner__hint">可以拖拽调整顺序，满意后确认生效</div>
      </div>
      <button className="btn btn--primary btn--sm" onClick={onConfirm}>
        ✅ 确认计划
      </button>
    </div>
  )
}
