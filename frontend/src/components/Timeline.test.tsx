import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Timeline } from './Timeline'
import type { PlanTimelineItem } from '../types'

/** jsdom 无 DataTransfer，提供最小实现 */
function fakeDataTransfer() {
  return {
    effectAllowed: 'move',
    dropEffect: 'none',
    files: [] as File[],
    items: [] as unknown[],
    types: [] as string[],
    setData: vi.fn(),
    getData: () => '',
    clearData: vi.fn(),
    setDragImage: vi.fn(),
  }
}

const items: PlanTimelineItem[] = [
  {
    key: 'course:1',
    type: 'course',
    start_time: '08:00',
    end_time: '09:40',
    title: '高等数学',
    subtitle: '教一 101',
    tier: 'A',
    location: '教一 101',
    ref_id: 1,
  },
  {
    key: 'review:1',
    type: 'review',
    start_time: '10:00',
    end_time: '10:25',
    title: '极限的定义',
    review_seq: 2,
    difficulty: 4,
    ref_id: 1,
  },
  {
    key: 'free:11:00-12:00',
    type: 'free',
    start_time: '11:00',
    end_time: '12:00',
    title: '自由时间',
  },
]

describe('Timeline 组件', () => {
  it('渲染课程 / 复习 / 自由时间条目', () => {
    render(<Timeline items={items} />)
    expect(screen.getByText('高等数学')).toBeInTheDocument()
    expect(screen.getByText('教一 101')).toBeInTheDocument()
    expect(screen.getByText('A 档')).toBeInTheDocument()
    expect(screen.getByText('🔁 第 2 次复习')).toBeInTheDocument()
    expect(screen.getByText('自由时间')).toBeInTheDocument()
  })

  it('复习点难度 ≥4 时显示「难度高」', () => {
    render(<Timeline items={items} />)
    expect(screen.getByText('难度高')).toBeInTheDocument()
  })

  it('空列表显示空状态文案', () => {
    render(<Timeline items={[]} emptyText="今日暂无安排" />)
    expect(screen.getByText('今日暂无安排')).toBeInTheDocument()
  })

  it('拖拽 drop 时回调 onMove(key, targetKey)', () => {
    const onMove = vi.fn()
    render(<Timeline items={items} onMove={onMove} />)
    const course = screen.getByTestId('timeline-item-course:1')
    const review = screen.getByTestId('timeline-item-review:1')

    fireEvent.dragStart(course, { dataTransfer: fakeDataTransfer() })
    fireEvent.dragOver(review)
    fireEvent.drop(review)
    fireEvent.dragEnd(course)

    expect(onMove).toHaveBeenCalledWith('course:1', 'review:1')
  })

  it('draggable=false 时禁用拖拽（确认后）', () => {
    const onMove = vi.fn()
    render(<Timeline items={items} draggable={false} onMove={onMove} />)
    const course = screen.getByTestId('timeline-item-course:1')
    expect(course.getAttribute('draggable')).toBe('false')
    fireEvent.dragStart(course, { dataTransfer: fakeDataTransfer() })
    fireEvent.drop(screen.getByTestId('timeline-item-review:1'))
    expect(onMove).not.toHaveBeenCalled()
  })
})
