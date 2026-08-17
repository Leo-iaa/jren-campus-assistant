import type { PropsWithChildren } from 'react'

interface CardProps {
  className?: string
  title?: string
  /** 卡片右上角附加内容 */
  extra?: React.ReactNode
}

/** 简洁卡片风基础容器 */
export function Card({ className = '', title, extra, children }: PropsWithChildren<CardProps>) {
  return (
    <section className={`card ${className}`}>
      {(title || extra) && (
        <header className="card__header">
          {title && <h2 className="card__title">{title}</h2>}
          {extra && <div className="card__extra">{extra}</div>}
        </header>
      )}
      <div className="card__body">{children}</div>
    </section>
  )
}
