import { useState } from 'react'
import { courseApi } from '../api/client'
import { useApi } from '../hooks/useApi'
import { TIERS, TIER_LABELS, TIER_REVIEW_SEQ, type Tier } from '../types'
import { Card } from './Card'

/** 课程档位管理：列表 + 档位下拉（S/A/B/C）+ 新建课程 */
export function CourseTierManager() {
  const { data, loading, error, refresh } = useApi(() => courseApi.list(), [])
  const [newName, setNewName] = useState('')
  const [newTier, setNewTier] = useState<Tier>('A')
  const [msg, setMsg] = useState<string | null>(null)

  const notify = (m: string) => {
    setMsg(m)
    setTimeout(() => setMsg(null), 5000)
  }

  const changeTier = async (id: number, tier: Tier) => {
    try {
      await courseApi.update(id, { tier })
      refresh()
    } catch (e) {
      notify(`❌ ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const createCourse = async () => {
    if (!newName.trim()) return
    try {
      await courseApi.create({ name: newName.trim(), tier: newTier })
      setNewName('')
      refresh()
      notify('✅ 课程已添加')
    } catch (e) {
      notify(`❌ ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  return (
    <Card title="课程档位管理" extra={<span className="muted">档位决定复习策略</span>}>
      {msg && <p className="settings-msg">{msg}</p>}
      {loading && <p className="muted">加载中…</p>}
      {error && <p className="error-text">无法加载课程：{error}</p>}

      <div className="course-tier-list">
        {data?.map((c) => (
          <div key={c.id} className="course-row">
            <span className="course-row__name">{c.name}</span>
            <span className="course-row__seq">
              {TIER_REVIEW_SEQ[c.tier].length > 0
                ? `复习序列：当晚 + ${TIER_REVIEW_SEQ[c.tier].join('/')} 天`
                : '不安排复习'}
            </span>
            <select
              className="tier-select"
              value={c.tier}
              aria-label={`${c.name} 档位`}
              onChange={(e) => changeTier(c.id, e.target.value as Tier)}
            >
              {TIERS.map((t) => (
                <option key={t} value={t}>
                  {t} · {TIER_LABELS[t]}
                </option>
              ))}
            </select>
          </div>
        ))}
        {data && data.length === 0 && <p className="muted">暂无课程，可先在下方添加。</p>}
      </div>

      <div className="source-form">
        <h3 className="panel-title">添加课程</h3>
        <div className="form-row">
          <label className="form-label form-label--wide">
            课程名称
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="如：高等数学"
            />
          </label>
          <label className="form-label">
            档位
            <select value={newTier} onChange={(e) => setNewTier(e.target.value as Tier)}>
              {TIERS.map((t) => (
                <option key={t} value={t}>
                  {t} · {TIER_LABELS[t]}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="form-actions">
          <button className="btn btn--primary btn--sm" onClick={createCourse}>
            + 添加
          </button>
        </div>
      </div>
    </Card>
  )
}
