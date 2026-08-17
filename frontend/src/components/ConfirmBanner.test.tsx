import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ConfirmBanner } from './ConfirmBanner'

const stats = { courseCount: 3, taskCount: 2, reviewCount: 1, miscCount: 0, freeMinutes: 120 }

describe('ConfirmBanner 组件', () => {
  it('未确认：显示 AI 摘要与确认按钮', () => {
    render(
      <ConfirmBanner stats={stats} isConfirmed={false} hasAdjusted={false} onConfirm={vi.fn()} onReset={vi.fn()} />,
    )
    expect(screen.getByText('AI 已生成今日计划')).toBeInTheDocument()
    expect(screen.getByText(/3 节课/)).toBeInTheDocument()
    expect(screen.getByText(/2 项作业/)).toBeInTheDocument()
    expect(screen.getByText(/1 个复习点/)).toBeInTheDocument()
    expect(screen.getByText(/2 小时自由时间/)).toBeInTheDocument()
  })

  it('点击确认按钮触发 onConfirm', () => {
    const onConfirm = vi.fn()
    render(
      <ConfirmBanner stats={stats} isConfirmed={false} hasAdjusted={false} onConfirm={onConfirm} onReset={vi.fn()} />,
    )
    fireEvent.click(screen.getByText('✅ 确认计划'))
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('已确认：显示确认状态，可撤销', () => {
    const onReset = vi.fn()
    render(
      <ConfirmBanner stats={stats} isConfirmed hasAdjusted onConfirm={vi.fn()} onReset={onReset} />,
    )
    expect(screen.getByText('今日计划已确认')).toBeInTheDocument()
    expect(screen.getByText('（已拖拽调整）')).toBeInTheDocument()
    fireEvent.click(screen.getByText('撤销确认'))
    expect(onReset).toHaveBeenCalledTimes(1)
  })

  it('无安排时显示空摘要', () => {
    const empty = { courseCount: 0, taskCount: 0, reviewCount: 0, miscCount: 0, freeMinutes: 0 }
    render(
      <ConfirmBanner stats={empty} isConfirmed={false} hasAdjusted={false} onConfirm={vi.fn()} onReset={vi.fn()} />,
    )
    expect(screen.getByText('今日暂无安排')).toBeInTheDocument()
  })
})
