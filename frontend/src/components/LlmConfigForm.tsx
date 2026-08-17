import { useState } from 'react'
import { loadLlmConfig, saveLlmConfig } from '../lib/storage'
import type { LlmConfig } from '../types'
import { Card } from './Card'

const PROVIDER_PRESETS: Record<LlmConfig['provider'], { endpoint: string; model: string }> = {
  doubao: { endpoint: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-1-5-pro-32k' },
  deepseek: { endpoint: 'https://api.deepseek.com', model: 'deepseek-chat' },
}

/** LLM 配置：豆包 / DeepSeek（暂存 localStorage） */
export function LlmConfigForm() {
  const [config, setConfig] = useState<LlmConfig>(() => loadLlmConfig())
  const [saved, setSaved] = useState(false)

  const switchProvider = (provider: LlmConfig['provider']) => {
    const preset = PROVIDER_PRESETS[provider]
    setConfig((c) => ({ ...c, provider, endpoint: preset.endpoint, model: preset.model }))
    setSaved(false)
  }

  const save = () => {
    saveLlmConfig(config)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <Card title="LLM 配置" extra={<span className="muted">用于知识点提取与计划生成</span>}>
      <div className="form-row">
        <label className="form-label">
          服务商
          <select
            value={config.provider}
            onChange={(e) => switchProvider(e.target.value as LlmConfig['provider'])}
          >
            <option value="doubao">豆包（火山方舟）</option>
            <option value="deepseek">DeepSeek</option>
          </select>
        </label>
        <label className="form-label form-label--wide">
          API Key
          <input
            type="password"
            value={config.apiKey}
            placeholder="sk-..."
            onChange={(e) => setConfig({ ...config, apiKey: e.target.value })}
          />
        </label>
      </div>
      <div className="form-row">
        <label className="form-label form-label--wide">
          Endpoint
          <input
            value={config.endpoint}
            onChange={(e) => setConfig({ ...config, endpoint: e.target.value })}
          />
        </label>
        <label className="form-label">
          模型
          <input value={config.model} onChange={(e) => setConfig({ ...config, model: e.target.value })} />
        </label>
      </div>
      <p className="muted">密钥仅保存在本地浏览器（localStorage），不会上传。</p>
      <div className="form-actions">
        <button className="btn btn--primary btn--sm" onClick={save}>
          💾 保存配置
        </button>
        {saved && <span className="settings-msg">已保存 ✓</span>}
      </div>
    </Card>
  )
}
