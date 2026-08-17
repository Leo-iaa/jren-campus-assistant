import { useState } from 'react'
import { dataSourceApi } from '../api/client'
import { useApi } from '../hooks/useApi'
import { DATA_SOURCE_LABELS, type DataSourceType } from '../types'
import { Card } from './Card'

const TYPE_OPTIONS: DataSourceType[] = ['notion', 'obsidian', 'ical', 'caldav']

/** 数据源绑定：列表 / 绑定 / 启停 / 同步 / 解绑 / Notion OAuth */
export function DataSourcesPanel() {
  const { data, loading, error, refresh } = useApi(() => dataSourceApi.list(), [])
  const [formType, setFormType] = useState<DataSourceType>('ical')
  const [formName, setFormName] = useState('')
  const [formConfig, setFormConfig] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [oauthState, setOauthState] = useState<string | null>(null)

  const notify = (m: string) => {
    setMsg(m)
    setTimeout(() => setMsg(null), 5000)
  }

  const createSource = async () => {
    try {
      await dataSourceApi.create({
        source_type: formType,
        name: formName || undefined,
        config: formConfig || undefined,
      })
      setFormName('')
      setFormConfig('')
      refresh()
      notify('✅ 数据源已绑定')
    } catch (e) {
      notify(`❌ ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const toggle = async (id: number, enabled: boolean) => {
    setBusyId(id)
    try {
      await (enabled ? dataSourceApi.disable(id) : dataSourceApi.enable(id))
      refresh()
    } catch (e) {
      notify(`❌ ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusyId(null)
    }
  }

  const sync = async (id: number) => {
    setBusyId(id)
    try {
      const r = await dataSourceApi.sync(id)
      notify(
        `🔄 同步完成：新增 ${r.created} / 更新 ${r.updated} / 跳过 ${r.skipped}` +
          (r.warnings.length ? `（${r.warnings.length} 条警告）` : ''),
      )
      refresh()
    } catch (e) {
      notify(`❌ 同步失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusyId(null)
    }
  }

  const remove = async (id: number) => {
    if (!window.confirm('确定解绑该数据源？')) return
    try {
      await dataSourceApi.remove(id)
      refresh()
      notify('🗑️ 已解绑')
    } catch (e) {
      notify(`❌ ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  /** Notion OAuth：获取授权 URL 并打开新窗口 */
  const startNotionOauth = async () => {
    try {
      const r = await dataSourceApi.notionOauthStart({
        redirect_uri: `${window.location.origin}/oauth/notion/callback`,
      })
      // 回调页通过 localStorage 取 source_id 完成 token 兑换
      localStorage.setItem('jren:notion:source_id', String(r.source_id))
      setOauthState(r.authorization_url)
      window.open(r.authorization_url, '_blank', 'noopener')
      notify('🔗 已打开 Notion 授权页面，完成后自动回调')
      refresh()
    } catch (e) {
      notify(`❌ 发起授权失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  return (
    <Card
      title="数据源绑定"
      extra={
        <button className="btn btn--ghost btn--sm" onClick={refresh}>
          刷新
        </button>
      }
    >
      {msg && <p className="settings-msg">{msg}</p>}

      <div className="sources">
        {loading && <p className="muted">加载中…</p>}
        {error && (
          <p className="error-text">
            无法连接后端（{error}）。请确认后端已启动（uvicorn backend.main:app）。
          </p>
        )}
        {data?.map((s) => (
          <div key={s.id} className="source-row">
            <div className="source-row__info">
              <span className="source-row__name">
                {s.name ?? DATA_SOURCE_LABELS[s.source_type]}
              </span>
              <span className={`badge badge--type`}>{DATA_SOURCE_LABELS[s.source_type]}</span>
              <span className="source-row__meta">
                {s.enabled ? '已启用' : '已停用'}
                {s.last_sync_at && ` · 最近同步 ${s.last_sync_at.slice(0, 16).replace('T', ' ')}`}
              </span>
            </div>
            <div className="source-row__actions">
              <button
                className="btn btn--ghost btn--sm"
                disabled={busyId === s.id}
                onClick={() => sync(s.id)}
              >
                同步
              </button>
              <button
                className="btn btn--ghost btn--sm"
                disabled={busyId === s.id}
                onClick={() => toggle(s.id, s.enabled)}
              >
                {s.enabled ? '停用' : '启用'}
              </button>
              <button className="btn btn--danger btn--sm" onClick={() => remove(s.id)}>
                解绑
              </button>
            </div>
          </div>
        ))}
        {data && data.length === 0 && (
          <p className="muted">尚未绑定数据源。iCal 课表可先绑定后同步，Notion 走 OAuth。</p>
        )}
      </div>

      <div className="source-form">
        <h3 className="panel-title">绑定新数据源</h3>
        <div className="form-row">
          <label className="form-label">
            类型
            <select
              value={formType}
              onChange={(e) => setFormType(e.target.value as DataSourceType)}
            >
              {TYPE_OPTIONS.map((t) => (
                <option key={t} value={t}>
                  {DATA_SOURCE_LABELS[t]}
                </option>
              ))}
            </select>
          </label>
          <label className="form-label">
            名称（可选）
            <input
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder="如：教务课表"
            />
          </label>
          <label className="form-label form-label--wide">
            配置（JSON，可选）
            <input
              value={formConfig}
              onChange={(e) => setFormConfig(e.target.value)}
              placeholder={'如 {"ics_path": "C:/schedule.ics"}'}
            />
          </label>
        </div>
        <div className="form-actions">
          <button className="btn btn--primary btn--sm" onClick={createSource}>
            + 绑定
          </button>
          {formType === 'notion' && (
            <button className="btn btn--primary btn--sm" onClick={startNotionOauth}>
              🔗 Notion OAuth 授权
            </button>
          )}
          {oauthState && (
            <a className="btn btn--ghost btn--sm" href={oauthState} target="_blank" rel="noreferrer">
              重新打开授权页
            </a>
          )}
        </div>
        <p className="muted">
          iCal 课表绑定后点击「同步」即可导入；Notion 建议直接使用 OAuth 授权；Obsidian 配置
          vault 路径后同步会做全文搜索。
        </p>
      </div>
    </Card>
  )
}
