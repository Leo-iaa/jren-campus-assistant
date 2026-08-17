import { CourseTierManager } from '../components/CourseTierManager'
import { DataSourcesPanel } from '../components/DataSourcesPanel'
import { LlmConfigForm } from '../components/LlmConfigForm'
import { PreferencesForm } from '../components/PreferencesForm'

/** 设置页：数据源 + 课程档位 + 偏好 + LLM 配置 */
export function SettingsPage() {
  return (
    <div className="page">
      <header className="page__head">
        <h1 className="page__title">设置</h1>
        <p className="page__date">数据源 · 档位 · 偏好 · LLM</p>
      </header>

      <DataSourcesPanel />
      <CourseTierManager />
      <PreferencesForm />
      <LlmConfigForm />
    </div>
  )
}
