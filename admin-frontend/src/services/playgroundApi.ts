/**
 * Playground API: default config, load/save trend, test prompt, log stream.
 */
import api from '@/lib/api'

export interface PlaygroundSection {
  id: string
  label: string
  content: string
  enabled: boolean
  order: number
}

export interface PlaygroundPromptConfig {
  model: string
  temperature: number
  top_p?: number | null
  candidate_count?: number | null
  media_resolution?: 'LOW' | 'MEDIUM' | 'HIGH' | null
  thinking_config?: {
    thinking_budget?: number
    thinking_level?: 'MINIMAL' | 'LOW' | 'MEDIUM' | 'HIGH'
  } | null
  format: string
  /** Размер изображения (как в тренде: prompt_size), например 1024x1024 */
  size?: string
  /** Явный aspect ratio для imageConfig.aspectRatio */
  aspect_ratio?: string | null
  sections: PlaygroundSection[]
  variables: Record<string, string>
  /** Seed для воспроизводимости генерации */
  seed?: number | null
  /** Tier размера изображения: 256, 512, 1K, 2K, 4K */
  image_size_tier?: string | null
}

export interface LogEntry {
  level: string
  message: string
  timestamp?: string | number
  extra?: Record<string, unknown>
  [key: string]: unknown
}

/** Run log entry from POST /admin/playground/test (snake_case from backend). */
export interface RunLogEntry {
  level: string
  message: string
  timestamp: number
  extra?: Record<string, unknown>
}

export interface PlaygroundTestResponse {
  image_urls?: string[]
  image_url?: string
  error?: string
  sent_request?: Record<string, unknown>
  run_log?: RunLogEntry[]
}

const DEFAULT_CONFIG: PlaygroundPromptConfig = {
  model: 'gemini-2.5-flash-image',
  temperature: 0.4,
  top_p: null,
  candidate_count: 1,
  media_resolution: null,
  thinking_config: null,
  format: 'png',
  size: '1024x1024',
  aspect_ratio: '1:1',
  sections: [
    { id: '1', label: 'Scene', content: '', enabled: true, order: 0 },
    { id: '2', label: 'Style', content: '', enabled: true, order: 1 },
    { id: '3', label: 'Avoid', content: '', enabled: true, order: 2 },
    { id: '4', label: 'Composition', content: '', enabled: true, order: 3 },
  ],
  variables: {},
  seed: undefined,
  image_size_tier: undefined,
}

export const playgroundApi = {
  getDefaultConfig: async (): Promise<PlaygroundPromptConfig> => {
    try {
      const r = await api.get<PlaygroundPromptConfig>('/admin/playground/config')
      return r.data ?? DEFAULT_CONFIG
    } catch {
      return DEFAULT_CONFIG
    }
  },

  createLogStream: (
    _sessionId: string,
    onLog: (entry: LogEntry) => void,
    onError: (err: unknown) => void
  ): (() => void) => {
    let aborted = false
    const token =
      typeof localStorage !== 'undefined' ? localStorage.getItem('access_token') : null
    const qs = token ? `?token=${encodeURIComponent(token)}` : ''
    const url = `${api.defaults.baseURL}/admin/playground/logs/stream${qs}`
    const eventSource = new EventSource(url)
    eventSource.onmessage = (e) => {
      if (aborted) return
      try {
        const entry = JSON.parse(e.data) as LogEntry
        onLog(entry)
      } catch (err) {
        onError(err)
      }
    }
    eventSource.onerror = () => {
      if (!aborted) onError(new Error('EventSource error'))
      eventSource.close()
    }
    return () => {
      aborted = true
      eventSource.close()
    }
  },

  /** Load trend's current prompt from DB into Playground config (backend is single source of truth). */
  loadTrend: async (trendId: string): Promise<PlaygroundPromptConfig> => {
    const r = await api.get<PlaygroundPromptConfig>(`/admin/trends/${trendId}/playground-config`)
    const data = r.data
    if (!data) return DEFAULT_CONFIG
    return {
      ...DEFAULT_CONFIG,
      sections: Array.isArray(data.sections) ? data.sections : DEFAULT_CONFIG.sections,
      model: data.model ?? DEFAULT_CONFIG.model,
      temperature: data.temperature ?? DEFAULT_CONFIG.temperature,
      format: data.format ?? DEFAULT_CONFIG.format,
      size: data.size ?? DEFAULT_CONFIG.size,
      variables: data.variables && typeof data.variables === 'object' ? data.variables : {},
      seed: data.seed ?? undefined,
      image_size_tier: data.image_size_tier ?? undefined,
      aspect_ratio: data.aspect_ratio ?? DEFAULT_CONFIG.aspect_ratio,
      top_p: data.top_p ?? DEFAULT_CONFIG.top_p,
      candidate_count: data.candidate_count ?? DEFAULT_CONFIG.candidate_count,
      media_resolution: data.media_resolution ?? DEFAULT_CONFIG.media_resolution,
      thinking_config: data.thinking_config ?? DEFAULT_CONFIG.thinking_config,
    }
  },

  saveToTrend: async (trendId: string, config: PlaygroundPromptConfig): Promise<{ ok: boolean }> => {
    await api.put(`/admin/playground/trends/${trendId}`, config)
    return { ok: true }
  },

  testPrompt: async (
    config: PlaygroundPromptConfig,
    images?: File[]
  ): Promise<{
    imageUrls?: string[]
    imageUrl?: string
    error?: string
    sent_request?: Record<string, unknown>
    run_log?: RunLogEntry[]
  }> => {
    const form = new FormData()
    form.append('config', JSON.stringify(config))
    for (const img of images || []) {
      form.append('images', img)
    }
    const r = await api.post<PlaygroundTestResponse>('/admin/playground/test', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
      maxContentLength: 120 * 1024 * 1024,
      maxBodyLength: 120 * 1024 * 1024,
    })
    const d = r.data
    return {
      imageUrls: d?.image_urls,
      imageUrl: d?.image_url,
      error: d?.error,
      sent_request: d?.sent_request,
      run_log: d?.run_log,
    }
  },

  /**
   * POST /admin/playground/batch-test — SSE stream (data: JSON lines).
   * configOverlay: поля глобального конфига вкладки batch; сервер мержит только overlay-ключи с промптом тренда.
   */
  streamBatchTest: async (
    params: {
      trendIds: string[]
      configOverlay: PlaygroundPromptConfig
      images: File[]
      concurrency: number
      signal?: AbortSignal
    },
    onEvent: (data: Record<string, unknown>) => void
  ): Promise<void> => {
    const form = new FormData()
    form.append('trend_ids', JSON.stringify(params.trendIds))
    form.append('config_overlay', JSON.stringify(params.configOverlay))
    form.append('concurrency', String(params.concurrency))
    for (const img of params.images) {
      form.append('images', img)
    }
    const token =
      typeof localStorage !== 'undefined' ? localStorage.getItem('access_token') : null
    const base = api.defaults.baseURL || ''
    const url = `${String(base).replace(/\/$/, '')}/admin/playground/batch-test`
    const res = await fetch(url, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
      signal: params.signal,
    })
    if (!res.ok) {
      const text = await res.text()
      let detail = `HTTP ${res.status}`
      if (text) {
        try {
          const j = JSON.parse(text) as { detail?: unknown }
          if (j?.detail != null) {
            detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
          } else {
            detail = text.slice(0, 500)
          }
        } catch {
          detail = text.slice(0, 500)
        }
      }
      throw new Error(detail)
    }
    const reader = res.body?.getReader()
    if (!reader) throw new Error('No response body')
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (value) {
        buffer += decoder.decode(value, { stream: true })
      }
      let nl: number
      while ((nl = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, nl).trimEnd()
        buffer = buffer.slice(nl + 1)
        if (line.startsWith('data: ')) {
          const raw = line.slice(6)
          try {
            onEvent(JSON.parse(raw) as Record<string, unknown>)
          } catch {
            /* ignore malformed chunk */
          }
        }
      }
      if (done) {
        const tail = buffer.trim()
        if (tail.startsWith('data: ')) {
          try {
            onEvent(JSON.parse(tail.slice(6)) as Record<string, unknown>)
          } catch {
            /* ignore */
          }
        }
        break
      }
    }
  },
}
