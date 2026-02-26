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
  format: string
  /** Размер изображения (как в тренде: prompt_size), например 1024x1024 */
  size?: string
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
  timestamp?: string
  [key: string]: unknown
}

const DEFAULT_CONFIG: PlaygroundPromptConfig = {
  model: 'gemini-2.5-flash-image',
  temperature: 0.4,
  format: 'png',
  size: '1024x1024',
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
    }
  },

  saveToTrend: async (trendId: string, config: PlaygroundPromptConfig): Promise<{ ok: boolean }> => {
    await api.put(`/admin/playground/trends/${trendId}`, config)
    return { ok: true }
  },

  testPrompt: async (
    config: PlaygroundPromptConfig,
    image1?: File
  ): Promise<{ imageUrl?: string; error?: string }> => {
    const form = new FormData()
    form.append('config', JSON.stringify(config))
    if (image1) form.append('image1', image1)
    const r = await api.post<{ image_url?: string; error?: string }>('/admin/playground/test', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    const d = r.data
    return { imageUrl: d?.image_url, error: d?.error }
  },
}
