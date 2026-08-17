import { useState } from 'react'
import type { PlanTimelineItem } from '../types'
import { ReviewBadge } from './ReviewBadge'

interface TimelineProps {
  items: PlanTimelineItem[]
  /** 是否允许拖拽（确认后可禁用） */
  draggable?: boolean
  onMove?: (key: string, targetKey: string) => void
  /** 空状态文案 */
  emptyText?: string
}

const TYPE_CLASS: Record<PlanTimelineItem['type'], string> = {
  course: 'timeline-item--course',
  task: 'timeline-item--task',
  review: 'timeline-item--review',
  misc: 'timeline-item--misc',
  free: 'timeline-item--free',
}

/** 时间轴：左侧时间列 + 条目卡片（支持拖拽排序） */
export function Timeline({
  items,
  draggable = true,
  onMove,
  emptyText = '今日暂无安排',
}: TimelineProps) {
  const [dragKey, setDragKey] = useState<string | null>(null)
  const [overKey, setOverKey] = useState<string | null>(null)

  if (items.length === 0) {
    return <p className="timeline-empty">{emptyText}</p>
  }

  return (
    <div className="timeline" data-testid="timeline">
      {items.map((item) => {
        const isFree = item.type === 'free'
        const canDrag = draggable && !isFree
        const isDragging = dragKey === item.key
        const isOver = overKey === item.key && dragKey !== null && dragKey !== item.key
        return (
          <div
            key={item.key}
            className={`timeline-item ${TYPE_CLASS[item.type]}${isDragging ? ' timeline-item--dragging' : ''}${isOver ? ' timeline-item--over' : ''}`}
            draggable={canDrag}
            data-testid={`timeline-item-${item.key}`}
            onDragStart={(e) => {
              if (!canDrag) return
              setDragKey(item.key)
              if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'
            }}
            onDragEnd={() => {
              setDragKey(null)
              setOverKey(null)
            }}
            onDragOver={(e) => {
              if (!canDrag || dragKey === null) return
              e.preventDefault()
              setOverKey(item.key)
            }}
            onDrop={(e) => {
              e.preventDefault()
              if (dragKey && dragKey !== item.key && onMove) {
                onMove(dragKey, item.key)
              }
              setDragKey(null)
              setOverKey(null)
            }}
          >
            <div className="timeline-item__time">
              <span>{item.start_time}</span>
              <span className="timeline-item__time-end">{item.end_time}</span>
            </div>
            <div className="timeline-item__body">
              <div className="timeline-item__title-row">
                <span className="timeline-item__title">{item.title}</span>
                {item.type === 'review' && (
                  <ReviewBadge seq={item.review_seq ?? 1} difficulty={item.difficulty} />
                )}
                {item.tier && (
                  <span className={`badge badge--tier badge--tier-${item.tier}`}>
                    {item.tier} 档
                  </span>
                )}
              </div>
              {item.subtitle && (
                <div className="timeline-item__subtitle">{item.subtitle}</div>
              )}
              {item.type === 'course' && item.location && (
                <div className="timeline-item__meta">📍 {item.location}</div>
              )}
            </div>
            {!isFree && (
              <span className="timeline-item__grip" aria-hidden title="拖拽调整">
                ⠿
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
