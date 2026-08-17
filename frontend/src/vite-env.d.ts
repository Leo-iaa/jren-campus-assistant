/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端 API 基础地址（默认 http://127.0.0.1:8000） */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
