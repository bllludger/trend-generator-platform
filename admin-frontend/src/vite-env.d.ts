/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE: string
  readonly VITE_TELEMETRY_OVERVIEW_V3?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
