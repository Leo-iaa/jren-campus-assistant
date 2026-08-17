import { NavLink } from 'react-router-dom'

const TABS = [
  { to: '/', label: '今日计划', icon: '📅' },
  { to: '/week', label: '周视图', icon: '🗓️' },
  { to: '/settings', label: '设置', icon: '⚙️' },
]

/** 底部 Tab 导航（移动端友好，桌面端固定底部居中） */
export function TabBar() {
  return (
    <nav className="tabbar" aria-label="主导航">
      {TABS.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.to === '/'}
          className={({ isActive }) => `tabbar__item${isActive ? ' tabbar__item--active' : ''}`}
        >
          <span className="tabbar__icon" aria-hidden>
            {t.icon}
          </span>
          <span className="tabbar__label">{t.label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
