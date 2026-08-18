import { useState } from 'react'
import { loadPreferences, savePreferences } from '../lib/storage'
import type { Preferences } from '../types'
import { Card } from './Card'

/** 偏好设置：每日复习上限 + 学习时段（暂存 localStorage） */
export function PreferencesForm() {
  const [prefs, setPrefs] = useState<Preferences>(() => loadPreferences())
  const [saved, setSaved] = useState(false)

  const update = (patch: Partial<Preferences>) => {
    setPrefs((p) => ({ ...p, ...patch }))
    setSaved(false)
  }

  const save = () => {
    savePreferences(prefs)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <Card title="个人偏好">
      <div className="form-row">
        <label className="form-label">
          每日复习上限（个知识点）
          <input
            type="number"
            min={1}
            max={50}
            value={prefs.reviewDailyCap}
            onChange={(e) => update({ reviewDailyCap: Number(e.target.value) })}
          />
        </label>
        <label className="form-label">
          学习时段起
          <input
            type="time"
            value={prefs.studyStart}
            onChange={(e) => update({ studyStart: e.target.value })}
          />
        </label>
        <label className="form-label">
          学习时段止
          <input
            type="time"
            value={prefs.studyEnd}
            onChange={(e) => update({ studyEnd: e.target.value })}
          />
        </label>
      </div>
      <p className="muted">
        超出每日上限的复习点不会排入今日时间轴（顺延处理，可在今日页底部待安排区查看）；
        计划只会安排在「学习时段」内的空闲时间。
      </p>
      <div className="form-actions">
        <button className="btn btn--primary btn--sm" onClick={save}>
          💾 保存偏好
        </button>
        {saved && <span className="settings-msg">已保存 ✓</span>}
      </div>
    </Card>
  )
}
