import { HashRouter, Route, Routes } from 'react-router-dom'
import { TabBar } from './components/TabBar'
import { NotionCallbackPage } from './pages/NotionCallbackPage'
import { SettingsPage } from './pages/SettingsPage'
import { TodayPlanPage } from './pages/TodayPlanPage'
import { WeekViewPage } from './pages/WeekViewPage'

/**
 * 应用入口：三页面 + OAuth 回调。
 * 使用 HashRouter：PWA 静态托管无需服务端 rewrite，安卓添加到主屏幕更稳。
 */
export default function App() {
  return (
    <HashRouter>
      <div className="app">
        <main className="app__main">
          <Routes>
            <Route path="/" element={<TodayPlanPage />} />
            <Route path="/week" element={<WeekViewPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/oauth/notion/callback" element={<NotionCallbackPage />} />
          </Routes>
        </main>
        <TabBar />
      </div>
    </HashRouter>
  )
}
