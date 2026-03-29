/**
 * Prompt Playground Page
 *
 * Interactive testing environment for Gemini prompts with:
 * - Full prompt editor
 * - Request JSON preview
 * - Run log from last test (no SSE)
 * - Multi-image input (model-limited)
 * - Multi-candidate image output
 */
import { useState, useEffect, useRef, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Play,
  Upload,
  Download,
  Sparkles,
  Terminal,
  FileJson,
  Image as ImageIcon,
  Settings,
  Loader2,
  Save,
} from 'lucide-react'
import { toast } from 'sonner'
import { useQuery } from '@tanstack/react-query'
import { playgroundApi, type PlaygroundPromptConfig, type PlaygroundSection, type RunLogEntry } from '@/services/playgroundApi'
import { trendsService, masterPromptService } from '@/services/api'
import { parseFullTrendPrompt } from '@/utils/trendPromptParse'

const APPLY_TO_ALL_TRENDS_LIMIT = 50
const BATCH_TEST_TRENDS_LIMIT = 200
const MAX_FILE_SIZE_BYTES = 7 * 1024 * 1024
const MAX_TOTAL_INPUT_BYTES = 50 * 1024 * 1024
/** Официальный id для Nano Banana Pro (image); старые конфиги могли хранить legacy-строку. */
const GEMINI_3_PRO_IMAGE_PREVIEW = 'gemini-3-pro-image-preview'
const LEGACY_GEMINI_3_PRO_IMAGE_MODEL_ID = 'gemini-3.1-pro-preview'

const isGemini3ProImageModel = (model: string | undefined): boolean =>
  model === GEMINI_3_PRO_IMAGE_PREVIEW || model === LEGACY_GEMINI_3_PRO_IMAGE_MODEL_ID

const PLAYGROUND_MODEL_OPTIONS = [
  { value: 'gemini-2.5-flash-image', label: 'Стандарт (gemini-2.5-flash-image)' },
  {
    value: GEMINI_3_PRO_IMAGE_PREVIEW,
    label: `Nano Banana Pro / Gemini 3 Pro Image (${GEMINI_3_PRO_IMAGE_PREVIEW})`,
  },
  { value: 'gemini-3.1-flash-image-preview', label: 'NeoBanana 2 (gemini-3.1-flash-image-preview)' },
] as const

const ASPECT_RATIO_OPTIONS = [
  '1:1', '3:2', '2:3', '3:4', '4:3', '4:5', '5:4',
  '9:16', '16:9', '21:9', '1:4', '4:1', '1:8', '8:1',
] as const

type ModelOption = (typeof PLAYGROUND_MODEL_OPTIONS)[number]['value']
type ThinkingLevel = 'MINIMAL' | 'LOW' | 'MEDIUM' | 'HIGH'

type InputAsset = {
  id: string
  file: File
  previewUrl: string
}

export type PlaygroundTestResult = {
  success?: boolean
  imageUrls?: string[]
  imageUrl?: string
  error?: string
}

const modelInputLimit = (model: string | undefined): number => {
  if (!model) return 3
  if (model === 'gemini-2.5-flash-image') return 3
  if (isGemini3ProImageModel(model) || model === 'gemini-3.1-flash-image-preview') return 14
  return 3
}

const modelMaxCandidateCount = (model: string | undefined): number => {
  if (!model) return 1
  if (isGemini3ProImageModel(model)) return 4
  return 1
}

const modelSupportsMediaResolution = (model: string | undefined): boolean => isGemini3ProImageModel(model)

const modelThinkingLevelOptions = (model: string | undefined): ThinkingLevel[] => {
  if (isGemini3ProImageModel(model)) return ['LOW', 'HIGH']
  if (model === 'gemini-3.1-flash-image-preview') return ['MINIMAL', 'LOW', 'MEDIUM', 'HIGH']
  return []
}

const normalizeThinkingLevel = (value: string | null | undefined): ThinkingLevel | null => {
  const raw = String(value || '').trim().toUpperCase().replace(/^THINKING_LEVEL_/, '')
  if (raw === 'MINIMAL' || raw === 'LOW' || raw === 'MEDIUM' || raw === 'HIGH') return raw
  return null
}

const normalizeThinkingConfig = (
  model: string | undefined,
  cfg: PlaygroundPromptConfig['thinking_config'] | null | undefined
): PlaygroundPromptConfig['thinking_config'] => {
  if (!cfg || typeof cfg !== 'object') return null
  const raw = cfg as Record<string, unknown>
  const supportedLevels = new Set(modelThinkingLevelOptions(model))
  const level = normalizeThinkingLevel((raw.thinking_level as string | undefined) ?? (raw.thinkingLevel as string | undefined))
  const budgetRaw = (raw.thinking_budget as number | string | undefined) ?? (raw.thinkingBudget as number | string | undefined)
  const budget = budgetRaw != null && Number.isFinite(Number(budgetRaw)) ? Math.max(0, Math.trunc(Number(budgetRaw))) : null
  if (level && supportedLevels.has(level)) {
    return { thinking_level: level }
  }
  if (budget != null) {
    return { thinking_budget: budget }
  }
  return null
}

const clamp = (n: number, min: number, max: number): number => Math.max(min, Math.min(max, n))

const buildInputAsset = (file: File): InputAsset => ({
  id: `${Date.now()}_${Math.random().toString(36).slice(2)}`,
  file,
  previewUrl: URL.createObjectURL(file),
})

const normalizePlaygroundConfig = (cfg: PlaygroundPromptConfig): PlaygroundPromptConfig => ({
  ...cfg,
  aspect_ratio: cfg.aspect_ratio || '1:1',
  top_p: cfg.top_p ?? null,
  candidate_count: clamp(
    Number(cfg.candidate_count ?? 1),
    1,
    modelMaxCandidateCount(cfg.model)
  ),
  media_resolution: modelSupportsMediaResolution(cfg.model) ? (cfg.media_resolution ?? null) : null,
  thinking_config: normalizeThinkingConfig(cfg.model, cfg.thinking_config),
})

export default function PromptPlaygroundPage() {
  const { data: masterSettings } = useQuery({
    queryKey: ['master-prompt-settings'],
    queryFn: () => masterPromptService.getSettings(),
  })

  const [config, setConfig] = useState<PlaygroundPromptConfig | null>(null)
  const [lastSentRequest, setLastSentRequest] = useState<Record<string, unknown> | null>(null)
  const [lastRunLog, setLastRunLog] = useState<RunLogEntry[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [result, setResult] = useState<PlaygroundTestResult | null>(null)
  const [inputAssets, setInputAssets] = useState<InputAsset[]>([])
  const [trends, setTrends] = useState<any[]>([])
  const [selectedTrendId, setSelectedTrendId] = useState<string>('')
  const [isSavingToTrend, setIsSavingToTrend] = useState(false)
  const [applyAllProgress, setApplyAllProgress] = useState<{ current: number; total: number } | null>(null)
  const [batchSelectedIds, setBatchSelectedIds] = useState<Set<string>>(new Set())
  const [batchTestRunning, setBatchTestRunning] = useState(false)
  const [batchTestProgress, setBatchTestProgress] = useState<{ current: number; total: number } | null>(null)
  const [batchTestResults, setBatchTestResults] = useState<
    Array<{ trendId: string; trendName: string; trendEmoji: string; status: 'success' | 'error'; duration?: number; error?: string; imageUrl?: string }>
  >([])
  /** Параллельных генераций на сервере (POST /batch-test), 1–20 */
  const [batchConcurrency, setBatchConcurrency] = useState(10)
  const [selectedBatchResultId, setSelectedBatchResultId] = useState<string | null>(null)
  const [batchSortKey, setBatchSortKey] = useState<'trend' | 'status' | 'duration'>('trend')
  const [batchSortDir, setBatchSortDir] = useState<'asc' | 'desc'>('asc')
  const [batchFilterStatus, setBatchFilterStatus] = useState<'all' | 'success' | 'error'>('all')
  const [fullPromptText, setFullPromptText] = useState('')
  const [zoomImageUrl, setZoomImageUrl] = useState<string | null>(null)
  const batchAbortRef = useRef<AbortController | null>(null)
  const logsEndRef = useRef<HTMLDivElement>(null)
  const assetsRef = useRef<InputAsset[]>([])

  useEffect(() => {
    loadDefaultConfig()
    loadTrends()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    assetsRef.current = inputAssets
  }, [inputAssets])

  useEffect(() => {
    return () => {
      assetsRef.current.forEach((asset) => URL.revokeObjectURL(asset.previewUrl))
    }
  }, [])

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lastRunLog])

  const currentModel = config?.model || 'gemini-2.5-flash-image'
  const inputLimit = modelInputLimit(currentModel)
  const totalInputBytes = useMemo(
    () => inputAssets.reduce((acc, asset) => acc + asset.file.size, 0),
    [inputAssets]
  )

  function sectionsToFullText(sections: PlaygroundSection[]): string {
    const ordered = [...(sections || [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    const labelToTag: Record<string, string> = {
      scene: '[]',
      style: '[STYLE]',
      avoid: '[AVOID]',
      composition: '[COMPOSITION]',
    }
    const parts: string[] = []
    for (const s of ordered) {
      const label = (s.label || '').trim().toLowerCase()
      const tag = labelToTag[label] || `[${(s.label || '').toUpperCase()}]`
      parts.push(tag, (s.content || '').trim())
    }
    return parts.join('\n').replace(/\n\n+/g, '\n\n').trim()
  }

  const loadDefaultConfig = async () => {
    try {
      setIsLoading(true)
      const defaultConfig = normalizePlaygroundConfig(await playgroundApi.getDefaultConfig())
      setConfig(defaultConfig)
      setFullPromptText(sectionsToFullText(defaultConfig.sections || []))
    } catch (error) {
      console.error('Failed to load default config:', error)
      toast.error('Failed to load default configuration')
    } finally {
      setIsLoading(false)
    }
  }

  const loadTrends = async () => {
    try {
      const trendsList = await trendsService.list()
      setTrends(trendsList)
    } catch (error) {
      console.error('Failed to load trends:', error)
    }
  }

  const loadTrendIntoPlayground = async (trendId: string) => {
    try {
      setIsLoading(true)
      const trendConfig = normalizePlaygroundConfig(await playgroundApi.loadTrend(trendId))
      setConfig(trendConfig)
      setFullPromptText(sectionsToFullText(trendConfig.sections || []))
      toast.success(`Loaded trend: ${trendId}`)
    } catch (error) {
      console.error('Failed to load trend:', error)
      toast.error('Failed to load trend into playground')
    } finally {
      setIsLoading(false)
    }
  }

  const saveToTrend = async () => {
    if (!selectedTrendId || !config) {
      toast.error('Выберите тренд и настройте промпт')
      return
    }
    try {
      setIsSavingToTrend(true)
      const configToSave: PlaygroundPromptConfig = { ...config, sections: fullPromptTextToSections(fullPromptText) }
      await playgroundApi.saveToTrend(selectedTrendId, configToSave)
      toast.success('Конфиг сохранён в тренд')
    } catch (error) {
      console.error('Failed to save to trend:', error)
      toast.error('Не удалось сохранить в тренд')
    } finally {
      setIsSavingToTrend(false)
    }
  }

  const applyToAllTrends = async () => {
    if (!config) {
      toast.error('Настройте промпт перед применением')
      return
    }
    let list: { id: string; order_index: number }[]
    let totalTrends: number
    try {
      const all = await trendsService.list()
      totalTrends = all.length
      const sorted = [...all].sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0))
      list = sorted.slice(0, APPLY_TO_ALL_TRENDS_LIMIT)
    } catch (e) {
      console.error('Failed to load trends:', e)
      toast.error('Не удалось загрузить список трендов')
      return
    }
    const total = list.length
    if (total === 0) {
      toast.info('Нет трендов для применения')
      return
    }
    const overLimit = totalTrends > APPLY_TO_ALL_TRENDS_LIMIT
    const message = overLimit
      ? `Применить текущий промпт к первым ${APPLY_TO_ALL_TRENDS_LIMIT} трендам (всего ${totalTrends})? Текущие prompt_sections в выбранных трендах будут перезаписаны.`
      : `Применить текущий промпт к ${total} трендам? Текущие prompt_sections в трендах будут перезаписаны.`
    if (!window.confirm(message)) return
    setApplyAllProgress({ current: 0, total })
    let applied = 0
    let failed = 0
    const configToApply: PlaygroundPromptConfig = { ...config, sections: fullPromptTextToSections(fullPromptText) }
    for (let i = 0; i < list.length; i++) {
      try {
        await playgroundApi.saveToTrend(list[i].id, configToApply)
        applied++
      } catch {
        failed++
      }
      setApplyAllProgress({ current: i + 1, total })
    }
    setApplyAllProgress(null)
    if (failed === 0) {
      toast.success(`Применено к ${applied} трендам`)
    } else {
      toast.warning(`Применено к ${applied} трендам, ошибок: ${failed}`)
    }
    loadTrends()
  }

  const runBatchTest = async () => {
    const ids = Array.from(batchSelectedIds).slice(0, BATCH_TEST_TRENDS_LIMIT)
    if (ids.length === 0) {
      toast.error('Выберите хотя бы один тренд')
      return
    }
    if (inputAssets.length === 0) {
      toast.error('Добавьте хотя бы одно фото для теста по трендам')
      return
    }
    if (!config) {
      toast.error('Настройте конфигурацию')
      return
    }

    const files = inputAssets.map((x) => x.file)
    const totalBytes = files.reduce((acc, file) => acc + file.size, 0)
    if (totalBytes > MAX_TOTAL_INPUT_BYTES) {
      toast.error(`Суммарный размер файлов превышает 50 MB (${(totalBytes / 1024 / 1024).toFixed(1)} MB)`)
      return
    }

    const overlay = normalizePlaygroundConfig(config)
    const abort = new AbortController()
    batchAbortRef.current = abort
    setBatchTestResults([])
    setSelectedBatchResultId(null)
    setBatchTestProgress({ current: 0, total: ids.length })
    setBatchTestRunning(true)

    try {
      await playgroundApi.streamBatchTest(
        {
          trendIds: ids,
          configOverlay: overlay,
          images: files,
          concurrency: clamp(batchConcurrency, 1, 20),
          signal: abort.signal,
        },
        (data) => {
          if (data.done === true) {
            const s = Number(data.success ?? 0)
            const e = Number(data.errors ?? 0)
            const okS = Number.isFinite(s) ? s : 0
            const okE = Number.isFinite(e) ? e : 0
            toast.success(`Готово: ${okS} успешно, ${okE} ошибок`)
            return
          }
          const trendId = String(data.trend_id ?? '')
          const row = {
            trendId,
            trendName: String(data.trend_name ?? trendId),
            trendEmoji: String(data.trend_emoji ?? ''),
            status: (data.status === 'success' ? 'success' : 'error') as 'success' | 'error',
            duration: typeof data.duration === 'number' ? data.duration : undefined,
            imageUrl: typeof data.image_url === 'string' ? data.image_url : undefined,
            error: typeof data.error === 'string' ? data.error : undefined,
          }
          setBatchTestResults((prev) => {
            const next = [...prev, row]
            setBatchTestProgress({ current: next.length, total: ids.length })
            return next
          })
        }
      )
    } catch (err: unknown) {
      const name = err && typeof err === 'object' && 'name' in err ? String((err as { name?: string }).name) : ''
      if (name === 'AbortError') {
        toast.info('Остановлено')
      } else {
        const msg = err instanceof Error ? err.message : String(err)
        toast.error(`Батч-тест: ${msg}`)
      }
    } finally {
      batchAbortRef.current = null
      setBatchTestRunning(false)
      setBatchTestProgress(null)
    }
  }

  const stopBatchTest = () => {
    batchAbortRef.current?.abort()
  }

  const toggleBatchTrend = (id: string) => {
    setBatchSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectAllBatch = () => {
    const list = [...trends].sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0))
    setBatchSelectedIds(new Set(list.map((t) => t.id)))
  }

  const deselectAllBatch = () => {
    setBatchSelectedIds(new Set())
  }

  const batchDisplayResults = useMemo(() => {
    let list = batchTestResults
    if (batchFilterStatus !== 'all') {
      list = list.filter((r) => r.status === batchFilterStatus)
    }
    const key = batchSortKey
    const dir = batchSortDir === 'asc' ? 1 : -1
    return [...list].sort((a, b) => {
      if (key === 'trend') return dir * a.trendName.localeCompare(b.trendName)
      if (key === 'status') return dir * a.status.localeCompare(b.status)
      const da = a.duration ?? 0
      const db = b.duration ?? 0
      return dir * (da - db)
    })
  }, [batchTestResults, batchSortKey, batchSortDir, batchFilterStatus])

  const toggleBatchSort = (k: 'trend' | 'status' | 'duration') => {
    setBatchSortKey((prev) => {
      if (prev === k) {
        setBatchSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
        return prev
      }
      setBatchSortDir('asc')
      return k
    })
  }
  const batchSortIndicator = (k: 'trend' | 'status' | 'duration') =>
    batchSortKey === k ? (batchSortDir === 'asc' ? ' ↑' : ' ↓') : ''

  const addInputFiles = (incoming: FileList | File[]) => {
    const files = Array.from(incoming || [])
    if (files.length === 0) return

    const next: InputAsset[] = []
    let rejectedCount = 0

    for (const file of files) {
      if (!file.type.startsWith('image/')) {
        rejectedCount++
        continue
      }
      if (file.size > MAX_FILE_SIZE_BYTES) {
        rejectedCount++
        toast.error(`Файл ${file.name} превышает 7 MB`)
        continue
      }
      next.push(buildInputAsset(file))
    }

    const limit = modelInputLimit(config?.model)
    const availableSlots = Math.max(0, limit - inputAssets.length)
    let totalBytes = inputAssets.reduce((acc, asset) => acc + asset.file.size, 0)
    const accepted: InputAsset[] = []
    let rejectedByLimit = 0
    let rejectedByTotalSize = 0

    for (const asset of next) {
      if (accepted.length >= availableSlots) {
        rejectedByLimit++
        URL.revokeObjectURL(asset.previewUrl)
        continue
      }
      if (totalBytes + asset.file.size > MAX_TOTAL_INPUT_BYTES) {
        rejectedByTotalSize++
        URL.revokeObjectURL(asset.previewUrl)
        continue
      }
      accepted.push(asset)
      totalBytes += asset.file.size
    }

    if (accepted.length > 0) {
      setInputAssets((prev) => [...prev, ...accepted])
    }
    if (rejectedByLimit > 0) {
      toast.warning(`Для модели ${config?.model || 'gemini'} максимум ${limit} входных изображений`)
    }
    if (rejectedByTotalSize > 0) {
      toast.warning('Превышен суммарный лимит 50 MB на запрос')
    }

    if (rejectedCount > 0 && rejectedCount === files.length) {
      toast.error('Не удалось добавить выбранные файлы')
    }
  }

  const removeInputAsset = (id: string) => {
    setInputAssets((prev) => {
      const target = prev.find((x) => x.id === id)
      if (target) URL.revokeObjectURL(target.previewUrl)
      return prev.filter((x) => x.id !== id)
    })
  }

  const clearAllInputAssets = () => {
    setInputAssets((prev) => {
      prev.forEach((x) => URL.revokeObjectURL(x.previewUrl))
      return []
    })
  }

  const handleTestPrompt = async () => {
    if (!config) {
      toast.error('Configuration not loaded')
      return
    }

    const files = inputAssets.map((x) => x.file)
    const limit = modelInputLimit(config.model)
    if (files.length > limit) {
      toast.error(`Слишком много файлов: ${files.length}, максимум для модели ${config.model}: ${limit}`)
      return
    }
    const totalBytes = files.reduce((acc, file) => acc + file.size, 0)
    if (totalBytes > MAX_TOTAL_INPUT_BYTES) {
      toast.error(`Суммарный размер файлов превышает 50 MB (${(totalBytes / 1024 / 1024).toFixed(1)} MB)`)
      return
    }

    try {
      setIsTesting(true)
      setResult(null)
      const configToSend: PlaygroundPromptConfig = { ...config, sections: fullPromptTextToSections(fullPromptText) }
      const response = await playgroundApi.testPrompt(configToSend, files)
      setLastSentRequest(response.sent_request ?? null)
      setLastRunLog(response.run_log ?? [])
      const imageUrls = response.imageUrls && response.imageUrls.length > 0 ? response.imageUrls : (response.imageUrl ? [response.imageUrl] : [])
      const mapped: PlaygroundTestResult = {
        success: imageUrls.length > 0,
        imageUrls,
        imageUrl: imageUrls[0],
        error: response.error,
      }
      setResult(mapped)
      if (imageUrls.length > 0) {
        toast.success(`Generation completed: ${imageUrls.length} image(s)`)
      } else if (response.error) {
        toast.error(`Generation failed: ${response.error}`)
      } else {
        console.warn('Playground test: no image and no error in response', response)
        toast.error('Неожиданный ответ: нет изображения и нет ошибки.')
      }
    } catch (error: any) {
      console.error('Test failed:', error)
      const msg = error?.response?.data?.detail ?? error?.response?.data?.error ?? error?.message ?? String(error)
      toast.error(`Test failed: ${msg}`)
    } finally {
      setIsTesting(false)
    }
  }

  function fullPromptTextToSections(text: string): PlaygroundSection[] {
    const parsed = parseFullTrendPrompt(text)
    const trimmed = text.trim()
    const hasMarkers = [parsed.scene, parsed.style, parsed.avoid, parsed.composition].some((s) => (s || '').trim().length > 0)
    if (!hasMarkers && trimmed) {
      return [{ id: `section_${Date.now()}_0`, label: 'prompt', content: trimmed, enabled: true, order: 0 }]
    }
    const ts = Date.now()
    return [
      { id: `section_${ts}_0`, label: 'Scene', content: parsed.scene, enabled: true, order: 0 },
      { id: `section_${ts}_1`, label: 'Style', content: parsed.style, enabled: true, order: 1 },
      { id: `section_${ts}_2`, label: 'Avoid', content: parsed.avoid, enabled: true, order: 2 },
      { id: `section_${ts}_3`, label: 'Composition', content: parsed.composition, enabled: true, order: 3 },
    ]
  }

  const buildRequestJson = () => {
    if (!config) return {}

    const parts: any[] = []

    const master = (masterSettings as { preview?: { prompt_input?: string; prompt_input_enabled?: boolean; prompt_task?: string; prompt_task_enabled?: boolean; prompt_identity_transfer?: string; prompt_identity_transfer_enabled?: boolean; safety_constraints?: string; safety_constraints_enabled?: boolean } })?.preview
    const textBlocks: string[] = []
    if (master?.prompt_input_enabled !== false && master?.prompt_input?.trim()) {
      textBlocks.push('[INPUT]\n' + master.prompt_input.trim())
    }
    if (master?.prompt_task_enabled !== false && master?.prompt_task?.trim()) {
      textBlocks.push('[TASK]\n' + master.prompt_task.trim())
    }
    if (master?.prompt_identity_transfer_enabled !== false && master?.prompt_identity_transfer?.trim()) {
      textBlocks.push('[IDENTITY TRANSFER]\n' + master.prompt_identity_transfer.trim())
    }

    const parsed = parseFullTrendPrompt(fullPromptText)
    let scene = (parsed.scene || '').trim()
    let style = (parsed.style || '').trim()
    let avoid = (parsed.avoid || '').trim()
    let composition = (parsed.composition || '').trim()
    for (const [key, value] of Object.entries(config.variables || {})) {
      scene = scene.replace(new RegExp(`{{${key}}}`, 'g'), String(value))
      style = style.replace(new RegExp(`{{${key}}}`, 'g'), String(value))
      avoid = avoid.replace(new RegExp(`{{${key}}}`, 'g'), String(value))
      composition = composition.replace(new RegExp(`{{${key}}}`, 'g'), String(value))
    }
    if (scene) textBlocks.push('[]\n' + scene)
    if (style) textBlocks.push('[STYLE]\n' + style)
    if (avoid) textBlocks.push('[AVOID]\n' + avoid)
    if (composition) textBlocks.push('[COMPOSITION]\n' + composition)

    const safetyText = (master?.safety_constraints ?? '').trim()
    if (master?.safety_constraints_enabled !== false && safetyText) {
      textBlocks.push('[SAFETY]\n' + safetyText)
    }

    parts.push({ text: textBlocks.join('\n\n').trim() })

    for (const item of inputAssets) {
      parts.push({
        inlineData: {
          mimeType: item.file.type,
          data: `<${item.file.name}; ${(item.file.size / 1024 / 1024).toFixed(2)} MB; REDACTED>`,
        },
      })
    }

    const modelSupportsImageSize = (config.model || '').toLowerCase().includes('gemini-3')
    const imageConfig: Record<string, unknown> = {
      aspectRatio: config.aspect_ratio || '1:1',
    }
    if (modelSupportsImageSize && config.image_size_tier) {
      imageConfig.imageSize = config.image_size_tier
    }

    const generationConfig: Record<string, unknown> = {
      responseModalities: ['IMAGE'],
      temperature: config.temperature,
      seed: config.seed != null ? Number(config.seed) : 42,
      imageConfig,
      candidateCount: clamp(Number(config.candidate_count ?? 1), 1, modelMaxCandidateCount(config.model)),
    }
    if (config.top_p != null) generationConfig.topP = clamp(Number(config.top_p), 0, 1)
    if (config.media_resolution && modelSupportsMediaResolution(config.model)) {
      generationConfig.mediaResolution = `MEDIA_RESOLUTION_${config.media_resolution}`
    }
    const normalizedThinking = normalizeThinkingConfig(config.model, config.thinking_config)
    if (normalizedThinking?.thinking_level) {
      generationConfig.thinkingConfig = { thinkingLevel: normalizedThinking.thinking_level }
    } else if (normalizedThinking?.thinking_budget != null && Number.isFinite(Number(normalizedThinking.thinking_budget))) {
      generationConfig.thinkingConfig = { thinkingBudget: Number(normalizedThinking.thinking_budget) }
    }

    return {
      model: config.model,
      generationConfig,
      contents: [{ role: 'user', parts }],
    }
  }

  const updateConfig = (patch: Partial<PlaygroundPromptConfig>) => {
    setConfig((prev) => (prev ? { ...prev, ...patch } : prev))
  }

  const renderConfigFields = (keyPrefix: string) => (
    (() => {
      const maxCandidates = modelMaxCandidateCount(config?.model)
      const canUseMediaResolution = modelSupportsMediaResolution(config?.model)
      const thinkingLevels = modelThinkingLevelOptions(config?.model)
      const canUseThinkingLevel = thinkingLevels.length > 0
      return (
    <CardContent className="grid grid-cols-2 md:grid-cols-3 gap-4">
      <div>
        <Label>Model</Label>
        <select
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={config?.model || 'gemini-2.5-flash-image'}
          onChange={(e) => {
            const nextModel = e.target.value as ModelOption
            const limit = modelInputLimit(nextModel)
            setConfig((prev) => {
              if (!prev) return prev
              const nextMaxCandidates = modelMaxCandidateCount(nextModel)
              return {
                ...prev,
                model: nextModel,
                candidate_count: clamp(Number(prev.candidate_count ?? 1), 1, nextMaxCandidates),
                media_resolution: modelSupportsMediaResolution(nextModel) ? prev.media_resolution : null,
                thinking_config: normalizeThinkingConfig(nextModel, prev.thinking_config),
              }
            })
            setInputAssets((prev) => {
              if (prev.length <= limit) return prev
              prev.slice(limit).forEach((x) => URL.revokeObjectURL(x.previewUrl))
              toast.warning(`Обрезано до ${limit} изображений для модели ${nextModel}`)
              return prev.slice(0, limit)
            })
          }}
        >
          {PLAYGROUND_MODEL_OPTIONS.map((modelOption) => (
            <option key={`${keyPrefix}_${modelOption.value}`} value={modelOption.value}>
              {modelOption.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <Label>Aspect Ratio</Label>
        <select
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={config?.aspect_ratio || '1:1'}
          onChange={(e) => updateConfig({ aspect_ratio: e.target.value })}
        >
          {ASPECT_RATIO_OPTIONS.map((ratio) => (
            <option key={`${keyPrefix}_ratio_${ratio}`} value={ratio}>{ratio}</option>
          ))}
        </select>
      </div>
      <div>
        <Label>Image Size</Label>
        <select
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={config?.image_size_tier ?? '2K'}
          onChange={(e) => updateConfig({ image_size_tier: e.target.value || undefined })}
        >
          <option value="256">256px</option>
          <option value="512">512px</option>
          <option value="1K">1K (~1024px)</option>
          <option value="2K">2K (~2048px)</option>
          <option value="4K">4K (~4096px)</option>
        </select>
      </div>
      <div>
        <Label>Temperature (0..2)</Label>
        <Input
          type="number"
          step="0.1"
          min={0}
          max={2}
          value={config?.temperature ?? 0.7}
          onChange={(e) => {
            const v = e.target.value
            const num = v === '' ? 0.7 : parseFloat(v)
            updateConfig({ temperature: Number.isFinite(num) ? clamp(num, 0, 2) : 0.7 })
          }}
        />
      </div>
      <div>
        <Label>topP (0..1)</Label>
        <Input
          type="number"
          step="0.01"
          min={0}
          max={1}
          value={config?.top_p ?? ''}
          onChange={(e) => {
            const val = e.target.value.trim()
            if (!val) return updateConfig({ top_p: null })
            const num = Number(val)
            updateConfig({ top_p: Number.isFinite(num) ? clamp(num, 0, 1) : null })
          }}
        />
      </div>
      <div>
        <Label>candidateCount (1..{maxCandidates})</Label>
        <Input
          type="number"
          min={1}
          max={maxCandidates}
          step={1}
          value={config?.candidate_count ?? 1}
          disabled={maxCandidates === 1}
          onChange={(e) => {
            const val = Number(e.target.value || 1)
            updateConfig({ candidate_count: clamp(Number.isFinite(val) ? Math.trunc(val) : 1, 1, maxCandidates) })
          }}
        />
      </div>
      <div>
        <Label>mediaResolution</Label>
        <select
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={config?.media_resolution ?? ''}
          disabled={!canUseMediaResolution}
          onChange={(e) => updateConfig({ media_resolution: (e.target.value || null) as PlaygroundPromptConfig['media_resolution'] })}
        >
          <option value="">(не задано)</option>
          <option value="LOW">LOW</option>
          <option value="MEDIUM">MEDIUM</option>
          <option value="HIGH">HIGH</option>
        </select>
        {!canUseMediaResolution && (
          <p className="text-xs text-muted-foreground mt-1">
            Доступно только для <code>{GEMINI_3_PRO_IMAGE_PREVIEW}</code> (старые конфиги с{' '}
            <code>{LEGACY_GEMINI_3_PRO_IMAGE_MODEL_ID}</code> тоже учитываются).
          </p>
        )}
      </div>
      <div>
        <Label>thinking_level</Label>
        <select
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={normalizeThinkingLevel(config?.thinking_config?.thinking_level) ?? ''}
          disabled={!canUseThinkingLevel}
          onChange={(e) => {
            const val = normalizeThinkingLevel(e.target.value)
            if (!val) {
              updateConfig({ thinking_config: normalizeThinkingConfig(config?.model, { thinking_budget: config?.thinking_config?.thinking_budget }) })
              return
            }
            updateConfig({ thinking_config: { thinking_level: val } })
          }}
        >
          <option value="">(не задано)</option>
          {thinkingLevels.map((level) => (
            <option key={`${keyPrefix}_thinking_${level}`} value={level}>{level}</option>
          ))}
        </select>
        {!canUseThinkingLevel && (
          <p className="text-xs text-muted-foreground mt-1">Для этой модели используйте <code>thinkingBudget</code>.</p>
        )}
      </div>
      <div>
        <Label>thinkingBudget</Label>
        <Input
          type="number"
          min={0}
          placeholder="пусто = off"
          value={config?.thinking_config?.thinking_budget ?? ''}
          disabled={Boolean(normalizeThinkingLevel(config?.thinking_config?.thinking_level))}
          onChange={(e) => {
            const val = e.target.value.trim()
            if (!val) return updateConfig({ thinking_config: normalizeThinkingConfig(config?.model, { thinking_level: config?.thinking_config?.thinking_level }) })
            const num = Number(val)
            updateConfig({ thinking_config: Number.isFinite(num) ? { thinking_budget: Math.max(0, Math.trunc(num)) } : null })
          }}
        />
      </div>
      <div>
        <Label>Seed</Label>
        <Input
          type="number"
          placeholder="Пусто = дефолт (42)"
          value={config?.seed ?? ''}
          onChange={(e) => {
            const val = e.target.value.trim()
            updateConfig({ seed: val ? parseInt(val, 10) : undefined })
          }}
        />
      </div>
      <div>
        <Label>Format (постобработка)</Label>
        <select
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={config?.format || 'png'}
          onChange={(e) => updateConfig({ format: e.target.value })}
        >
          <option value="png">PNG</option>
          <option value="jpeg">JPEG</option>
          <option value="webp">WebP</option>
        </select>
      </div>
      {keyPrefix === 'batch' && (
        <div className="col-span-2 md:col-span-3">
          <Label>Параллельность батча (1–20)</Label>
          <Input
            type="number"
            min={1}
            max={20}
            value={batchConcurrency}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10)
              setBatchConcurrency(Number.isFinite(v) ? clamp(Math.trunc(v), 1, 20) : 10)
            }}
          />
          <p className="text-xs text-muted-foreground mt-1">
            Одновременных генераций на сервере: одна загрузка фото, параллельный Gemini. Учитывайте квоты API.
          </p>
        </div>
      )}
    </CardContent>
      )
    })()
  )

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="w-8 h-8 animate-spin" />
      </div>
    )
  }

  return (
    <div className="container mx-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Sparkles className="w-8 h-8 text-purple-500" />
            Prompt Playground
          </h1>
          <p className="text-muted-foreground">
            Interactive testing for Gemini prompts with visual feedback
          </p>
        </div>

        <div className="flex items-center gap-2">
          <select
            value={selectedTrendId}
            onChange={(e) => {
              setSelectedTrendId(e.target.value)
              if (e.target.value) loadTrendIntoPlayground(e.target.value)
            }}
            className="px-3 py-2 border rounded-md"
          >
            <option value="">Загрузить тренд...</option>
            {trends.map((trend) => (
              <option key={trend.id} value={trend.id}>
                {trend.emoji} {trend.name}
              </option>
            ))}
          </select>
          <Button
            variant="default"
            onClick={saveToTrend}
            disabled={!selectedTrendId || !config || isSavingToTrend}
          >
            {isSavingToTrend ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Save className="w-4 h-4 mr-2" />
            )}
            Сохранить в тренд
          </Button>
          {applyAllProgress !== null && (
            <div className="flex flex-col gap-1 w-full max-w-xs">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Применение конфига</span>
                <span>{applyAllProgress.current} из {applyAllProgress.total}</span>
              </div>
              <Progress
                value={applyAllProgress.total ? Math.round((applyAllProgress.current / applyAllProgress.total) * 100) : 0}
              />
            </div>
          )}
          <Button
            variant="outline"
            onClick={applyToAllTrends}
            disabled={!config || applyAllProgress !== null}
          >
            {applyAllProgress !== null ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                {applyAllProgress.current} из {applyAllProgress.total}
              </>
            ) : (
              <>
                <Save className="w-4 h-4 mr-2" />
                Применить ко всем трендам
              </>
            )}
          </Button>
          <Button variant="outline" onClick={loadDefaultConfig}>
            <Download className="w-4 h-4 mr-2" />
            Сброс
          </Button>
        </div>
      </div>

      <p className="text-sm text-muted-foreground mb-2">
        Глобальные блоки и перенос личности задаются в{' '}
        <Link to="/master-prompt" className="underline text-primary">
          Мастер промпт
        </Link>
        .
      </p>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ImageIcon className="w-5 h-5" />
            Фото для теста
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Входные изображения для prompt. Лимит: до {inputLimit} файлов для модели <b>{currentModel}</b>, до 7 MB на файл, суммарно до 50 MB.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            <label className="inline-flex">
              <span className="inline-flex items-center px-3 py-2 border rounded-md cursor-pointer hover:bg-muted/50 text-sm">
                <Upload className="w-4 h-4 mr-2" />
                Добавить фото
              </span>
              <input
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={(e) => {
                  if (e.target.files) addInputFiles(e.target.files)
                  e.currentTarget.value = ''
                }}
              />
            </label>
            <Button variant="outline" onClick={clearAllInputAssets} disabled={inputAssets.length === 0}>Очистить</Button>
            <span className="text-xs text-muted-foreground">
              {inputAssets.length} / {inputLimit} • {(totalInputBytes / 1024 / 1024).toFixed(1)} / 50.0 MB
            </span>
          </div>
          {inputAssets.length === 0 ? (
            <div className="text-sm text-muted-foreground border rounded p-4">Добавьте одно или несколько фото для теста.</div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {inputAssets.map((asset, idx) => (
                <div key={asset.id} className="relative border rounded overflow-hidden">
                  <img src={asset.previewUrl} alt={`Input ${idx + 1}`} className="w-full h-28 object-cover" />
                  <button
                    type="button"
                    className="absolute top-1 right-1 bg-red-500 text-white text-xs px-2 py-1 rounded"
                    onClick={() => removeInputAsset(asset.id)}
                  >
                    Удалить
                  </button>
                  <div className="px-2 py-1 text-xs text-muted-foreground truncate">{asset.file.name}</div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Tabs defaultValue="editor" className="w-full">
        <TabsList className="grid w-full max-w-md grid-cols-2 mb-4">
          <TabsTrigger value="editor">Редактор</TabsTrigger>
          <TabsTrigger value="batch">Тест по фото</TabsTrigger>
        </TabsList>

        <TabsContent value="editor" className="mt-0">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <FileJson className="w-5 h-5" />
                    Полный промпт
                  </CardTitle>
                  <p className="text-xs text-muted-foreground">
                    Можно вставить любой промпт. Маркеры [], [STYLE], [AVOID], [COMPOSITION] на отдельных строках разобьют текст на блоки.
                  </p>
                </CardHeader>
                <CardContent>
                  <textarea
                    value={fullPromptText}
                    onChange={(e) => setFullPromptText(e.target.value)}
                    placeholder="Вставьте промпт или опишите сцену…"
                    className="w-full p-3 border rounded-md text-sm font-mono min-h-[280px]"
                    rows={14}
                    aria-label="Полный промпт"
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Settings className="w-5 h-5" />
                    Configuration
                  </CardTitle>
                </CardHeader>
                {renderConfigFields('editor')}
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Play className="w-5 h-5" />
                    Тест промпта
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Используются входные изображения из блока выше.
                  </p>
                </CardHeader>
                <CardContent>
                  <Button className="w-full" size="lg" onClick={handleTestPrompt} disabled={isTesting}>
                    {isTesting ? (
                      <>
                        <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                        Тестирование...
                      </>
                    ) : (
                      <>
                        <Play className="w-5 h-5 mr-2" />
                        Test Prompt
                      </>
                    )}
                  </Button>
                </CardContent>
              </Card>
            </div>

            <div className="space-y-6">
              <Tabs defaultValue="result">
                <TabsList className="grid w-full grid-cols-3">
                  <TabsTrigger value="result">Result</TabsTrigger>
                  <TabsTrigger value="json">Request JSON</TabsTrigger>
                  <TabsTrigger value="logs">Logs</TabsTrigger>
                </TabsList>

                <TabsContent value="result">
                  <Card>
                    <CardHeader>
                      <CardTitle>Generation Result</CardTitle>
                    </CardHeader>
                    <CardContent>
                      {!result ? (
                        <div className="text-center text-gray-500 py-12">No result yet. Click "Test Prompt" to generate.</div>
                      ) : (result.success ?? !!result.imageUrl) ? (
                        <div className="space-y-4">
                          {result.imageUrls && result.imageUrls.length > 0 ? (
                            <>
                              <div className="text-sm text-muted-foreground">Получено кандидатов: {result.imageUrls.length}</div>
                              <div className="text-xs text-muted-foreground">Нажмите на изображение, чтобы увеличить.</div>
                              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                {result.imageUrls.map((url, idx) => (
                                  <div key={idx}>
                                    <Label>Candidate {idx + 1}</Label>
                                    <img
                                      src={url}
                                      alt={`Candidate ${idx + 1}`}
                                      className="w-full rounded border mt-2 cursor-zoom-in max-h-[70vh] object-contain bg-muted/20"
                                      onClick={() => setZoomImageUrl(url)}
                                    />
                                  </div>
                                ))}
                              </div>
                            </>
                          ) : (
                            <div className="text-muted-foreground">Нет изображений в ответе</div>
                          )}
                        </div>
                      ) : (
                        <div className="space-y-4">
                          <div className="text-destructive font-semibold">Generation Failed</div>
                          <div className="text-sm">{result.error != null ? String(result.error) : null}</div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="json">
                  <Card>
                    <CardHeader>
                      <CardTitle>
                        {lastSentRequest != null ? 'Request JSON (отправленный)' : 'Request JSON (Preview)'}
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <pre className="bg-gray-50 p-4 rounded text-xs overflow-auto max-h-[600px] font-mono">
                        {JSON.stringify(lastSentRequest ?? buildRequestJson(), null, 2)}
                      </pre>
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="logs">
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <Terminal className="w-5 h-5" />
                        Лог последнего запроса
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="bg-black text-green-400 p-4 rounded font-mono text-xs h-[600px] overflow-auto">
                        {lastRunLog.length === 0 ? (
                          <div className="text-gray-500">Запустите тест, чтобы увидеть лог последнего запроса.</div>
                        ) : (
                          lastRunLog.map((log: RunLogEntry, i: number) => (
                            <div key={i} className="mb-1">
                              <span className={`font-bold ${
                                log.level === 'error' ? 'text-red-400' :
                                log.level === 'warning' ? 'text-yellow-400' :
                                'text-green-400'
                              }`}>
                                [{String(log.level).toUpperCase()}]
                              </span>{' '}
                              <span className="text-gray-400">
                                {typeof log.timestamp === 'number' ? new Date(log.timestamp * 1000).toISOString() : log.timestamp}
                              </span>{' '}
                              {String(log.message)}
                              {log.extra != null && typeof log.extra === 'object' && Object.keys(log.extra).length > 0 && (
                                <div className="ml-4 text-blue-300">{JSON.stringify(log.extra, null, 2)}</div>
                              )}
                            </div>
                          ))
                        )}
                        <div ref={logsEndRef} />
                      </div>
                    </CardContent>
                  </Card>
                </TabsContent>
              </Tabs>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="batch" className="mt-0 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Settings className="w-5 h-5" />
                Configuration
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                Параметры генерации для запуска по трендам. Промпты берутся из каждого тренда, остальное — из этого конфига.
                Батч на сервере: одна загрузка фото, параллельные вызовы Gemini (поле «Параллельность батча» ниже).
              </p>
            </CardHeader>
            {renderConfigFields('batch')}
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Запуск по трендам</CardTitle>
              <p className="text-sm text-muted-foreground">
                Выберите тренды. Запуск использует фото из блока выше. Будет запущено выбранных трендов: {batchSelectedIds.size}.
                Если <code>candidateCount &gt; 1</code>, в batch учитывается только первый candidate.
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-2 flex-wrap">
                <Button variant="outline" size="sm" onClick={selectAllBatch} disabled={batchTestRunning || trends.length === 0}>
                  Выбрать все
                </Button>
                <Button variant="outline" size="sm" onClick={deselectAllBatch} disabled={batchTestRunning}>
                  Снять все
                </Button>
                {batchSelectedIds.size > BATCH_TEST_TRENDS_LIMIT && (
                  <span className="text-sm text-warning">
                    Выбрано {batchSelectedIds.size} трендов (макс. {BATCH_TEST_TRENDS_LIMIT} за один запуск)
                  </span>
                )}
              </div>
              {trends.length === 0 ? (
                <div className="text-sm text-muted-foreground py-4">Загрузка списка трендов...</div>
              ) : (
                <div className="max-h-48 overflow-y-auto border rounded-md p-2 space-y-1">
                  {[...trends]
                    .sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0))
                    .map((t) => (
                      <label key={t.id} className="flex items-center gap-2 cursor-pointer hover:bg-muted/50 rounded px-2 py-1">
                        <input
                          type="checkbox"
                          checked={batchSelectedIds.has(t.id)}
                          onChange={() => toggleBatchTrend(t.id)}
                          disabled={batchTestRunning}
                          className="rounded border-input"
                        />
                        <span>{t.emoji} {t.name}</span>
                      </label>
                    ))}
                </div>
              )}
              {batchTestProgress !== null && (
                <div className="flex flex-col gap-1 w-full max-w-xs">
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>Тест по трендам</span>
                    <span>{batchTestProgress.current} из {batchTestProgress.total}</span>
                  </div>
                  <Progress
                    value={batchTestProgress.total ? Math.round((batchTestProgress.current / batchTestProgress.total) * 100) : 0}
                  />
                </div>
              )}
              <div className="flex items-center gap-2">
                <Button
                  onClick={runBatchTest}
                  disabled={batchTestRunning || batchSelectedIds.size === 0 || inputAssets.length === 0}
                >
                  {batchTestRunning ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      {batchTestProgress ? `${batchTestProgress.current} из ${batchTestProgress.total}` : 'Запуск...'}
                    </>
                  ) : (
                    <>
                      <Play className="w-4 h-4 mr-2" />
                      Запустить по выбранным трендам
                    </>
                  )}
                </Button>
                <Button variant="outline" onClick={stopBatchTest} disabled={!batchTestRunning}>
                  Остановить
                </Button>
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Результаты</CardTitle>
                <p className="text-sm text-muted-foreground">Сортировка: клик по заголовку столбца. Фильтр по статусу:</p>
                <div className="flex gap-2 mt-2">
                  <Button variant={batchFilterStatus === 'all' ? 'default' : 'outline'} size="sm" onClick={() => setBatchFilterStatus('all')}>Все</Button>
                  <Button variant={batchFilterStatus === 'success' ? 'default' : 'outline'} size="sm" onClick={() => setBatchFilterStatus('success')}>Успех</Button>
                  <Button variant={batchFilterStatus === 'error' ? 'default' : 'outline'} size="sm" onClick={() => setBatchFilterStatus('error')}>Ошибка</Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b">
                        <th className="text-left p-2 cursor-pointer hover:bg-muted/50 rounded" onClick={() => toggleBatchSort('trend')}>Тренд{batchSortIndicator('trend')}</th>
                        <th className="text-left p-2 cursor-pointer hover:bg-muted/50 rounded" onClick={() => toggleBatchSort('status')}>Статус{batchSortIndicator('status')}</th>
                        <th className="text-left p-2 cursor-pointer hover:bg-muted/50 rounded" onClick={() => toggleBatchSort('duration')}>Длительность{batchSortIndicator('duration')}</th>
                        <th className="text-left p-2">Ошибка</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batchDisplayResults.length === 0 ? (
                        <tr>
                          <td colSpan={4} className="p-4 text-muted-foreground text-center">
                            {batchTestResults.length === 0 ? 'Запустите тест, чтобы увидеть результаты' : 'Нет строк по выбранному фильтру'}
                          </td>
                        </tr>
                      ) : (
                        batchDisplayResults.map((r, rowIdx) => (
                          <tr
                            key={`${r.trendId}-${rowIdx}`}
                            className={`border-b cursor-pointer hover:bg-muted/50 ${selectedBatchResultId === r.trendId ? 'bg-muted' : ''}`}
                            onClick={() => setSelectedBatchResultId(r.trendId)}
                          >
                            <td className="p-2">{r.trendEmoji} {r.trendName}</td>
                            <td className="p-2">
                              <span className={r.status === 'success' ? 'text-success' : 'text-destructive'}>
                                {r.status === 'success' ? 'Успех' : 'Ошибка'}
                              </span>
                            </td>
                            <td className="p-2">{r.duration != null ? `${r.duration.toFixed(1)} с` : '—'}</td>
                            <td className="p-2 text-muted-foreground max-w-xs truncate" title={r.error}>{r.error ?? '—'}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Результат для каждого тренда</CardTitle>
                <p className="text-sm text-muted-foreground">Выберите строку в таблице слева, чтобы увидеть картинку.</p>
              </CardHeader>
              <CardContent>
                {!selectedBatchResultId ? (
                  <div className="flex items-center justify-center min-h-[300px] text-muted-foreground">Выберите тренд в таблице</div>
                ) : (() => {
                  const sel = batchTestResults.find((r) => r.trendId === selectedBatchResultId)
                  if (!sel) return <div className="text-muted-foreground">Результат не найден</div>
                  if (sel.status === 'error') {
                    return (
                      <div className="space-y-2">
                        <p className="text-destructive font-medium">{sel.trendEmoji} {sel.trendName}</p>
                        <p className="text-sm text-muted-foreground">{sel.error ?? 'Ошибка'}</p>
                      </div>
                    )
                  }
                  return (
                    <div className="space-y-2">
                      <p className="font-medium">{sel.trendEmoji} {sel.trendName}</p>
                      {sel.imageUrl ? (
                        <img
                          src={sel.imageUrl}
                          alt={sel.trendName}
                          className="w-full rounded border cursor-zoom-in max-h-[70vh] object-contain bg-muted/20"
                          onClick={() => setZoomImageUrl(sel.imageUrl || null)}
                        />
                      ) : (
                        <div className="text-muted-foreground">Нет изображения</div>
                      )}
                    </div>
                  )
                })()}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>

      <Dialog open={Boolean(zoomImageUrl)} onOpenChange={(open) => { if (!open) setZoomImageUrl(null) }}>
        <DialogContent className="max-w-[95vw] w-[95vw] p-2">
          <DialogHeader className="px-3 pt-2 pb-0">
            <DialogTitle>Увеличенный просмотр</DialogTitle>
          </DialogHeader>
          {zoomImageUrl ? (
            <div className="p-2">
              <img src={zoomImageUrl} alt="Zoomed result" className="w-full max-h-[88vh] object-contain rounded border" />
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}
