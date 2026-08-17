import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { dataSourceApi } from '../api/client'
import { Card } from '../components/Card'

/**
 * Notion OAuth 回调页：后端约定的默认 redirect_uri 为
 * http://localhost:5173/oauth/notion/callback（本路由）。
 * 拿到 code + state 后调用后端 /notion/oauth/callback 兑换 token。
 */
export function NotionCallbackPage() {
  const [params] = useSearchParams()
  const [status, setStatus] = useState<'processing' | 'done' | 'error'>('processing')
  const [message, setMessage] = useState('正在完成 Notion 授权…')
  const done = useRef(false)

  useEffect(() => {
    if (done.current) return
    done.current = true
    const code = params.get('code')
    const state = params.get('state')
    // 后端 start 接口创建数据源后返回 source_id，回调时通过 localStorage 传递
    const sourceId = Number(localStorage.getItem('jren:notion:source_id') ?? '0')

    if (!code || !state) {
      setStatus('error')
      setMessage('缺少 code 或 state 参数，授权未完成')
      return
    }
    if (!sourceId) {
      setStatus('error')
      setMessage('缺少数据源 ID，请从设置页重新发起授权')
      return
    }

    dataSourceApi
      .notionOauthCallback({ source_id: sourceId, code, state })
      .then(() => {
        localStorage.removeItem('jren:notion:source_id')
        setStatus('done')
        setMessage('Notion 授权成功！可以返回设置页使用了。')
      })
      .catch((e: unknown) => {
        setStatus('error')
        setMessage(`授权失败：${e instanceof Error ? e.message : String(e)}`)
      })
  }, [params])

  return (
    <div className="page">
      <Card title="Notion 授权">
        <p className={status === 'error' ? 'error-text' : status === 'done' ? 'ok-text' : 'muted'}>
          {message}
        </p>
        <p>
          <a className="btn btn--primary btn--sm" href="/settings">
            返回设置页
          </a>
        </p>
      </Card>
    </div>
  )
}
