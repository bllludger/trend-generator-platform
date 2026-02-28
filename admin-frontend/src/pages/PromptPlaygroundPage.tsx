/**
 * Prompt Playground Page
 * 
 * Interactive testing environment for Gemini prompts with:
 * - Drag & drop prompt sections
 * - Live JSON preview
 * - Run log from last test (no SSE)
 * - Test with images
 * - Result visualization
 */
import { useState, useEffect, useRef, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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

export type PlaygroundTestResult = {
  success?: boolean
  imageUrl?: string
  image_b64?: string
  duration_seconds?: number
  raw_response?: unknown
  error?: string
}

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
  const [image1, setImage1] = useState<File | null>(null)
  const [image1Preview, setImage1Preview] = useState<string | null>(null)
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
  const [selectedBatchResultId, setSelectedBatchResultId] = useState<string | null>(null)
  const [batchSortKey, setBatchSortKey] = useState<'trend' | 'status' | 'duration'>('trend')
  const [batchSortDir, setBatchSortDir] = useState<'asc' | 'desc'>('asc')
  const [batchFilterStatus, setBatchFilterStatus] = useState<'all' | 'success' | 'error'>('all')
  const [fullPromptText, setFullPromptText] = useState('')
  const batchTestStopRef = useRef(false)
  
  const logsEndRef = useRef<HTMLDivElement>(null)

  // Load default config on mount
  useEffect(() => {
    loadDefaultConfig()
    loadTrends()
  }, [])

  // Auto-scroll logs when last run log updates
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lastRunLog])

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
      const defaultConfig = await playgroundApi.getDefaultConfig()
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
      const trendConfig = await playgroundApi.loadTrend(trendId)
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
    if (!image1) {
      toast.error('Загрузите фото (Фото 1) для теста по трендам')
      return
    }
    const trendMap = new Map(trends.map((t) => [t.id, t]))
    setBatchTestResults([])
    setSelectedBatchResultId(null)
    setBatchTestProgress({ current: 0, total: ids.length })
    setBatchTestRunning(true)
    batchTestStopRef.current = false
    const results: typeof batchTestResults = []
    for (let i = 0; i < ids.length; i++) {
      if (batchTestStopRef.current) break
      const trendId = ids[i]
      const t = trendMap.get(trendId)
      const trendName = t?.name ?? trendId
      const trendEmoji = t?.emoji ?? ''
      const start = Date.now()
      try {
        const trendConfig = await playgroundApi.loadTrend(trendId)
        const mergedConfig = config
          ? {
              ...trendConfig,
              model: config.model ?? trendConfig.model,
              temperature: config.temperature ?? trendConfig.temperature,
              format: config.format ?? trendConfig.format,
              size: config.size ?? trendConfig.size,
              seed: config.seed ?? trendConfig.seed,
              image_size_tier: config.image_size_tier ?? trendConfig.image_size_tier,
            }
          : trendConfig
        const response = await playgroundApi.testPrompt(mergedConfig, image1)
        const duration = (Date.now() - start) / 1000
        if (response.imageUrl) {
          results.push({ trendId, trendName, trendEmoji, status: 'success', duration, imageUrl: response.imageUrl })
        } else {
          results.push({
            trendId,
            trendName,
            trendEmoji,
            status: 'error',
            duration,
            error: response.error ?? 'Unknown error',
          })
        }
      } catch (err: unknown) {
        const duration = (Date.now() - start) / 1000
        results.push({
          trendId,
          trendName,
          trendEmoji,
          status: 'error',
          duration,
          error: err instanceof Error ? err.message : String(err),
        })
      }
      setBatchTestResults([...results])
      setBatchTestProgress({ current: i + 1, total: ids.length })
    }
    setBatchTestRunning(false)
    setBatchTestProgress(null)
    toast.success(`Готово: ${results.filter((r) => r.status === 'success').length} успешно, ${results.filter((r) => r.status === 'error').length} ошибок`)
  }

  const stopBatchTest = () => {
    batchTestStopRef.current = true
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
      if (key === 'trend') return dir * (a.trendName.localeCompare(b.trendName))
      if (key === 'status') return dir * (a.status.localeCompare(b.status))
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

  const handleTestPrompt = async () => {
    if (!config) {
      toast.error('Configuration not loaded')
      return
    }

    try {
      setIsTesting(true)
      setResult(null)
      const configToSend: PlaygroundPromptConfig = { ...config, sections: fullPromptTextToSections(fullPromptText) }
      const response = await playgroundApi.testPrompt(configToSend, image1 ?? undefined)
      setLastSentRequest(response.sent_request ?? null)
      setLastRunLog(response.run_log ?? [])
      const mapped: PlaygroundTestResult = {
        success: !!response.imageUrl,
        imageUrl: response.imageUrl,
        image_b64: response.imageUrl?.startsWith('data:') ? response.imageUrl.split(',')[1] : undefined,
        error: response.error,
      }
      setResult(mapped)
      if (response.imageUrl) {
        toast.success('Generation completed')
      } else if (response.error) {
        toast.error(`Generation failed: ${response.error}`)
      } else {
        console.warn('Playground test: no image_url and no error in response', response)
        toast.error('Неожиданный ответ: нет изображения и нет ошибки. Возможно, ответ обрезан (большой размер).')
      }
    } catch (error: any) {
      console.error('Test failed:', error)
      const msg = error?.response?.data?.detail ?? error?.message ?? String(error)
      toast.error(`Test failed: ${msg}`)
    } finally {
      setIsTesting(false)
    }
  }

  const handleImageUpload = (file: File | null) => {
    setImage1(file)
    if (file) {
      const reader = new FileReader()
      reader.onload = (e) => setImage1Preview(e.target?.result as string)
      reader.readAsDataURL(file)
    } else {
      setImage1Preview(null)
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

  const sizeToAspectRatio = (size: string): string => {
    if (!size || !size.includes('x')) return '1:1'
    const [w, h] = size.split('x').map(Number)
    if (!w || !h) return '1:1'
    const g = (a: number, b: number): number => (b ? g(b, a % b) : a)
    const d = g(w, h)
    return `${w / d}:${h / d}`
  }

  const buildRequestJson = () => {
    if (!config) return {}
    
    const parts: any[] = []
    
    // Full prompt: master blocks ([INPUT], [TASK], [IDENTITY TRANSFER]) + sections + [SAFETY]
    const textBlocks: string[] = []
    if (masterSettings?.prompt_input_enabled !== false && masterSettings?.prompt_input?.trim()) {
      textBlocks.push('[INPUT]\n' + masterSettings.prompt_input.trim())
    }
    if (masterSettings?.prompt_task_enabled !== false && masterSettings?.prompt_task?.trim()) {
      textBlocks.push('[TASK]\n' + masterSettings.prompt_task.trim())
    }
    if (masterSettings?.prompt_identity_transfer_enabled !== false && masterSettings?.prompt_identity_transfer?.trim()) {
      textBlocks.push('[IDENTITY TRANSFER]\n' + masterSettings.prompt_identity_transfer.trim())
    }
    const parsed = parseFullTrendPrompt(fullPromptText)
    let scene = (parsed.scene || '').trim()
    let style = (parsed.style || '').trim()
    let avoid = (parsed.avoid || '').trim()
    let composition = (parsed.composition || '').trim()
    const hasMarkers = scene || style || avoid || composition
    for (const [key, value] of Object.entries(config.variables || {})) {
      scene = scene.replace(new RegExp(`{{${key}}}`, 'g'), String(value))
      style = style.replace(new RegExp(`{{${key}}}`, 'g'), String(value))
      avoid = avoid.replace(new RegExp(`{{${key}}}`, 'g'), String(value))
      composition = composition.replace(new RegExp(`{{${key}}}`, 'g'), String(value))
    }
    const sectionsParts: string[] = []
    if (hasMarkers) {
      if (scene) sectionsParts.push('[]\n' + scene)
      if (style) sectionsParts.push('[STYLE]\n' + style)
      if (avoid) sectionsParts.push('[AVOID]\n' + avoid)
      if (composition) sectionsParts.push('[COMPOSITION]\n' + composition)
      const sectionsText = sectionsParts.join('\n\n')
      if (sectionsText) textBlocks.push(sectionsText)
    } else if (fullPromptText.trim()) {
      textBlocks.push(fullPromptText.trim())
    }
    const safetyText = (masterSettings?.safety_constraints ?? '').trim()
    if (masterSettings?.safety_constraints_enabled !== false && safetyText) {
      textBlocks.push('[SAFETY]\n' + safetyText)
    }
    const promptText = textBlocks.join('\n\n')
    parts.push({ text: promptText })

    // Text first (identity lock), then image
    if (image1) {
      parts.push({
        inline_data: {
          mime_type: image1.type,
          data: '<IMAGE_1_BASE64>',
        },
      })
    }
    
    const aspectRatio = (config as any)?.aspect_ratio || (config.size ? sizeToAspectRatio(config.size) : '1:1')
    // imageSize поддерживают gemini-3-pro-image-preview и gemini-3.1-flash-image-preview; для gemini-2.5 не отправляем
    const modelSupportsImageSize = (config.model || '').toLowerCase().includes('gemini-3')
    const imageSizeTier = config.image_size_tier ?? '2K'
    const imageConfig: Record<string, unknown> = { aspectRatio }
    if (modelSupportsImageSize && imageSizeTier) {
      imageConfig.imageSize = imageSizeTier
    }
    const generationConfig: Record<string, unknown> = {
      responseModalities: ['IMAGE'],
      temperature: config.temperature,
      seed: config.seed != null ? Number(config.seed) : 42,
      imageConfig,
    }
    return {
      model: config.model,
      generationConfig,
      contents: [
        {
          role: 'user',
          parts,
        },
      ],
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="w-8 h-8 animate-spin" />
      </div>
    )
  }

  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Sparkles className="w-8 h-8 text-purple-500" />
            Prompt Playground
          </h1>
          <p className="text-muted-foreground">
            Interactive testing for Gemini prompts with real-time logs and visual feedback
          </p>
        </div>
        
        <div className="flex items-center gap-2">
          <select
            value={selectedTrendId}
            onChange={(e) => {
              setSelectedTrendId(e.target.value)
              if (e.target.value) {
                loadTrendIntoPlayground(e.target.value)
              }
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

      {/* Общий блок загрузки фото — используется в Редакторе и в «Тест по фото» */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ImageIcon className="w-5 h-5" />
            Фото для теста
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Фото пользователя для переноса в сцену. Используется в Редакторе и для запуска по трендам во вкладке «Тест по фото».
          </p>
        </CardHeader>
        <CardContent>
          <div className="max-w-xl">
            <Label>Фото для теста (обязательно для теста по трендам)</Label>
            <div className="mt-2">
              {image1Preview ? (
                <div className="relative">
                  <img src={image1Preview} alt="Preview" className="w-full h-32 object-cover rounded border" />
                  <Button
                    size="sm"
                    variant="destructive"
                    className="absolute top-2 right-2"
                    onClick={() => handleImageUpload(null)}
                  >
                    Удалить
                  </Button>
                </div>
              ) : (
                <label className="flex flex-col items-center justify-center w-full h-32 border-2 border-dashed rounded cursor-pointer hover:bg-muted/50">
                  <Upload className="w-8 h-8 mb-2 text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">Загрузить</span>
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => handleImageUpload(e.target.files?.[0] || null)}
                  />
                </label>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="editor" className="w-full">
        <TabsList className="grid w-full max-w-md grid-cols-2 mb-4">
          <TabsTrigger value="editor">Редактор</TabsTrigger>
          <TabsTrigger value="batch">Тест по фото</TabsTrigger>
        </TabsList>

        <TabsContent value="editor" className="mt-0">
      {/* Main Layout - 2 columns */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Column - Prompt Builder */}
        <div className="space-y-6">
          {/* Полный промпт — один способ ввода */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileJson className="w-5 h-5" />
                Полный промпт
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                Можно вставить любой промпт. Опционально: маркеры [], [STYLE], [AVOID], [COMPOSITION] на отдельных строках разобьют текст на блоки ([] — сцена).
              </p>
            </CardHeader>
            <CardContent>
              <textarea
                value={fullPromptText}
                onChange={(e) => setFullPromptText(e.target.value)}
                placeholder="Вставьте промпт или опишите сцену…"
                className="w-full p-3 border rounded-md text-sm font-mono min-h-[280px]"
                rows={14}
                aria-label="Полный промпт (любой текст или блоки [], [STYLE], [AVOID], [COMPOSITION])"
              />
            </CardContent>
          </Card>

          {/* Configuration */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Settings className="w-5 h-5" />
                Configuration
              </CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <div>
                <Label>Model</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={config?.model || 'gemini-2.5-flash-image'}
                  onChange={(e) => setConfig(config ? { ...config, model: e.target.value } : null)}
                >
                  <option value="gemini-2.5-flash-image">Стандарт (gemini-2.5-flash-image)</option>
                  <option value="gemini-3-pro-image-preview">Gemini 3 Pro (gemini-3-pro-image-preview)</option>
                  <option value="gemini-3.1-flash-image-preview">Nano Banana 2 (gemini-3.1-flash-image-preview)</option>
                </select>
              </div>
              <div>
                <Label>Aspect Ratio</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={(config as any)?.aspect_ratio || '1:1'}
                  onChange={(e) => setConfig(config ? { ...config, aspect_ratio: e.target.value } as any : null)}
                >
                  <option value="1:1">1:1 (квадрат)</option>
                  <option value="16:9">16:9 (широкий)</option>
                  <option value="9:16">9:16 (вертикальный)</option>
                  <option value="4:3">4:3</option>
                  <option value="3:4">3:4</option>
                </select>
              </div>
              <div>
                <Label>Image Size</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={config?.image_size_tier ?? '2K'}
                  onChange={(e) => setConfig(config ? { ...config, image_size_tier: e.target.value || undefined } : null)}
                >
                  <option value="256">256px</option>
                  <option value="512">512px</option>
                  <option value="1K">1K (~1024px)</option>
                  <option value="2K">2K (~2048px)</option>
                  <option value="4K">4K (~4096px)</option>
                </select>
              </div>
              <div>
                <Label>Temperature</Label>
                <Input
                  type="number"
                  step="0.1"
                  min={0}
                  max={2}
                  value={config?.temperature ?? 0.7}
                  onChange={(e) => {
                    const v = e.target.value
                    const num = v === '' ? 0.7 : parseFloat(v)
                    setConfig(config ? { ...config, temperature: Number.isFinite(num) ? num : 0 } : null)
                  }}
                />
                {(config?.model || '').toLowerCase().includes('gemini-3-pro') && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Для gemini-3-pro: 0.3–0.5 лучше сохраняют лицо.
                  </p>
                )}
              </div>
              <div>
                <Label>Seed</Label>
                <Input
                  type="number"
                  placeholder="Пусто = дефолт (42)"
                  value={config?.seed ?? ''}
                  onChange={(e) => {
                    const val = e.target.value.trim()
                    setConfig(config ? { ...config, seed: val ? parseInt(val, 10) : undefined } : null)
                  }}
                />
                <p className="text-xs text-muted-foreground mt-1">Для воспроизводимости</p>
              </div>
              <div>
                <Label>Format (постобработка)</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={config?.format || 'png'}
                  onChange={(e) => setConfig(config ? { ...config, format: e.target.value } : null)}
                >
                  <option value="png">PNG</option>
                  <option value="jpeg">JPEG</option>
                  <option value="webp">WebP</option>
                </select>
                <p className="text-xs text-muted-foreground mt-1">Конвертация на нашей стороне</p>
              </div>
            </CardContent>
          </Card>

          {/* Тест одного промпта — фото берётся из общего блока выше */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Play className="w-5 h-5" />
                Тест промпта
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                Фото загружается выше. Результат — одна картинка по текущему конфигу тренда.
              </p>
            </CardHeader>
            <CardContent>
              <Button
                className="w-full"
                size="lg"
                onClick={handleTestPrompt}
                disabled={isTesting}
              >
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

        {/* Right Column - Preview & Results */}
        <div className="space-y-6">
          <Tabs defaultValue="result">
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="result">Result</TabsTrigger>
              <TabsTrigger value="json">Request JSON</TabsTrigger>
              <TabsTrigger value="logs">Logs</TabsTrigger>
            </TabsList>
            
            {/* Result */}
            <TabsContent value="result">
              <Card>
                <CardHeader>
                  <CardTitle>Generation Result</CardTitle>
                </CardHeader>
                <CardContent>
                  {!result ? (
                    <div className="text-center text-gray-500 py-12">
                      No result yet. Click "Test Prompt" to generate.
                    </div>
                  ) : (result.success ?? !!result.imageUrl) ? (
                    <div className="space-y-4">
                      {/* Generated Image */}
                      {result.imageUrl && (
                        <div>
                          <Label>Generated Image</Label>
                          <img
                            src={result.imageUrl}
                            alt="Generated"
                            className="w-full rounded border mt-2"
                          />
                        </div>
                      )}
                      
                      {/* Duration */}
                      {result.duration_seconds != null && (
                        <div className="text-sm text-gray-600">
                          Duration: {result.duration_seconds}s
                        </div>
                      )}
                      
                      {/* Raw Response */}
                      <div>
                        <Label>Raw Gemini Response</Label>
                        <pre className="bg-gray-50 p-4 rounded text-xs overflow-auto max-h-96 font-mono mt-2">
                          {JSON.stringify(result.raw_response, null, 2)}
                        </pre>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <div className="text-red-600 font-semibold">
                        Generation Failed
                      </div>
                      <div className="text-sm">
                        {result.error != null ? String(result.error) : null}
                      </div>
                      {result.raw_response != null ? (
                        <div>
                          <Label>Error Details</Label>
                          <pre className="bg-red-50 p-4 rounded text-xs overflow-auto max-h-96 font-mono mt-2">
                            {JSON.stringify(result.raw_response, null, 2)}
                          </pre>
                        </div>
                      ) : null}
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* Request JSON: sent (after test) or preview */}
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

            {/* Logs: last run only */}
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
                            <div className="ml-4 text-blue-300">
                              {JSON.stringify(log.extra, null, 2)}
                            </div>
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
          {/* Конфиг для запуска по трендам — общие параметры для всех выбранных трендов */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Settings className="w-5 h-5" />
                Configuration
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                Параметры генерации для запуска по трендам. Промпты берутся из каждого тренда, остальное — из этого конфига.
              </p>
            </CardHeader>
            <CardContent className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <div>
                <Label>Model</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={config?.model || 'gemini-2.5-flash-image'}
                  onChange={(e) => setConfig(config ? { ...config, model: e.target.value } : null)}
                >
                  <option value="gemini-2.5-flash-image">Стандарт (gemini-2.5-flash-image)</option>
                  <option value="gemini-3-pro-image-preview">Gemini 3 Pro (gemini-3-pro-image-preview)</option>
                  <option value="gemini-3.1-flash-image-preview">Nano Banana 2 (gemini-3.1-flash-image-preview)</option>
                </select>
              </div>
              <div>
                <Label>Aspect Ratio</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={(config as { aspect_ratio?: string })?.aspect_ratio || '1:1'}
                  onChange={(e) => setConfig(config ? { ...config, aspect_ratio: e.target.value } as typeof config : null)}
                >
                  <option value="1:1">1:1 (квадрат)</option>
                  <option value="16:9">16:9 (широкий)</option>
                  <option value="9:16">9:16 (вертикальный)</option>
                  <option value="4:3">4:3</option>
                  <option value="3:4">3:4</option>
                </select>
              </div>
              <div>
                <Label>Image Size</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={config?.image_size_tier ?? '2K'}
                  onChange={(e) => setConfig(config ? { ...config, image_size_tier: e.target.value || undefined } : null)}
                >
                  <option value="256">256px</option>
                  <option value="512">512px</option>
                  <option value="1K">1K (~1024px)</option>
                  <option value="2K">2K (~2048px)</option>
                  <option value="4K">4K (~4096px)</option>
                </select>
              </div>
              <div>
                <Label>Temperature</Label>
                <Input
                  type="number"
                  step="0.1"
                  min={0}
                  max={2}
                  value={config?.temperature ?? 0.7}
                  onChange={(e) => {
                    const v = e.target.value
                    const num = v === '' ? 0.7 : parseFloat(v)
                    setConfig(config ? { ...config, temperature: Number.isFinite(num) ? num : 0 } : null)
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
                    setConfig(config ? { ...config, seed: val ? parseInt(val, 10) : undefined } : null)
                  }}
                />
                <p className="text-xs text-muted-foreground mt-1">Для воспроизводимости</p>
              </div>
              <div>
                <Label>Format (постобработка)</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={config?.format || 'png'}
                  onChange={(e) => setConfig(config ? { ...config, format: e.target.value } : null)}
                >
                  <option value="png">PNG</option>
                  <option value="jpeg">JPEG</option>
                  <option value="webp">WebP</option>
                </select>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Запуск по трендам</CardTitle>
              <p className="text-sm text-muted-foreground">
                Выберите тренды. Запуск использует фото из блока выше. Будет запущено выбранных трендов: {batchSelectedIds.size}.
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
                  <span className="text-sm text-amber-600">
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
                  disabled={batchTestRunning || batchSelectedIds.size === 0 || !image1}
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
                <Button
                  variant="outline"
                  onClick={stopBatchTest}
                  disabled={!batchTestRunning}
                >
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
                  <Button
                    variant={batchFilterStatus === 'all' ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setBatchFilterStatus('all')}
                  >
                    Все
                  </Button>
                  <Button
                    variant={batchFilterStatus === 'success' ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setBatchFilterStatus('success')}
                  >
                    Успех
                  </Button>
                  <Button
                    variant={batchFilterStatus === 'error' ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setBatchFilterStatus('error')}
                  >
                    Ошибка
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b">
                        <th className="text-left p-2 cursor-pointer hover:bg-muted/50 rounded" onClick={() => toggleBatchSort('trend')}>
                          Тренд{batchSortIndicator('trend')}
                        </th>
                        <th className="text-left p-2 cursor-pointer hover:bg-muted/50 rounded" onClick={() => toggleBatchSort('status')}>
                          Статус{batchSortIndicator('status')}
                        </th>
                        <th className="text-left p-2 cursor-pointer hover:bg-muted/50 rounded" onClick={() => toggleBatchSort('duration')}>
                          Длительность{batchSortIndicator('duration')}
                        </th>
                        <th className="text-left p-2">Ошибка</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batchDisplayResults.length === 0 ? (
                        <tr>
                          <td colSpan={4} className="p-4 text-muted-foreground text-center">
                            {batchTestResults.length === 0
                              ? 'Запустите тест, чтобы увидеть результаты'
                              : 'Нет строк по выбранному фильтру'}
                          </td>
                        </tr>
                      ) : (
                        batchDisplayResults.map((r) => (
                          <tr
                            key={r.trendId}
                            className={`border-b cursor-pointer hover:bg-muted/50 ${selectedBatchResultId === r.trendId ? 'bg-muted' : ''}`}
                            onClick={() => setSelectedBatchResultId(r.trendId)}
                          >
                            <td className="p-2">{r.trendEmoji} {r.trendName}</td>
                            <td className="p-2">
                              <span className={r.status === 'success' ? 'text-green-600' : 'text-red-600'}>
                                {r.status === 'success' ? 'Успех' : 'Ошибка'}
                              </span>
                            </td>
                            <td className="p-2">{r.duration != null ? `${r.duration.toFixed(1)} с` : '—'}</td>
                            <td className="p-2 text-muted-foreground max-w-xs truncate" title={r.error}>
                              {r.error ?? '—'}
                            </td>
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
                <p className="text-sm text-muted-foreground">
                  Выберите строку в таблице слева, чтобы увидеть картинку.
                </p>
              </CardHeader>
              <CardContent>
                {!selectedBatchResultId ? (
                  <div className="flex items-center justify-center min-h-[300px] text-muted-foreground">
                    Выберите тренд в таблице
                  </div>
                ) : (() => {
                  const sel = batchTestResults.find((r) => r.trendId === selectedBatchResultId)
                  if (!sel) return <div className="text-muted-foreground">Результат не найден</div>
                  if (sel.status === 'error') {
                    return (
                      <div className="space-y-2">
                        <p className="text-red-600 font-medium">{sel.trendEmoji} {sel.trendName}</p>
                        <p className="text-sm text-muted-foreground">{sel.error ?? 'Ошибка'}</p>
                      </div>
                    )
                  }
                  return (
                    <div className="space-y-2">
                      <p className="font-medium">{sel.trendEmoji} {sel.trendName}</p>
                      {sel.imageUrl ? (
                        <img src={sel.imageUrl} alt={sel.trendName} className="w-full rounded border" />
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
    </div>
  )
}
