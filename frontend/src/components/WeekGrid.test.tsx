import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { toDateStr } from '../lib/date'
import { WeekGrid } from './WeekGrid'

const days = [
  {
    date: '2026-08-17',
    courseItems: [{ id: 1, start: '08:00', end: '09:40', name: '高等数学', tier: 'A' as const }],
    taskItems: [{ id: 1, title: '作业：导数练习', status: 'todo' }],
    reviewItems: [{ id: 1, title: '极限的定义', seq: 2, difficulty: 3 }],
  },
  {
    date: '2026-08-18',
    courseItems: [],
    taskItems: [],
    reviewItems: [],
  },
]

describe('WeekGrid 组件', () => {
  it('渲染 7 天网格与课程/任务/复习条目', () => {
    render(<WeekGrid days={days} />)
    expect(screen.getByTestId('weekgrid')).toBeInTheDocument()
    expect(screen.getByText('周一')).toBeInTheDocument()
    expect(screen.getByText('高等数学')).toBeInTheDocument()
    expect(screen.getByText('作业：导数练习')).toBeInTheDocument()
    expect(screen.getByText('极限的定义')).toBeInTheDocument()
    expect(screen.getAllByText('🔁 2').length).toBeGreaterThan(0)
  })

  it('今天所在列高亮标注「今天」', () => {
    // 只渲染「今天」单列：避免原用例用固定日期撞上真实今天导致出现两个「今天」
    const today = toDateStr(new Date())
    const { container } = render(<WeekGrid days={[{ ...days[0], date: today }]} />)
    expect(container.querySelector('.weekgrid__day--today')).not.toBeNull()
    expect(screen.getByText('今天')).toBeInTheDocument()
  })

  it('空列显示占位符', () => {
    render(<WeekGrid days={days} />)
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })
})
