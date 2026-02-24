/**
 * Prompt Playground Page
 * 
 * Interactive testing environment for Gemini prompts with:
 * - Drag & drop prompt sections
 * - Live JSON preview
 * - Real-time logs via SSE
 * - Test with images
 * - Result visualization
 */
import { useState, useEffect, useRef, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
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
  ArrowUp,
  ArrowDown,
  Eye,
  EyeOff,
  Save,
} from 'lucide-react'
import { toast } from 'sonner'
import { useQuery } from '@tanstack/react-query'
import { playgroundApi, type PlaygroundPromptConfig, type LogEntry, type PlaygroundSection } from '@/services/playgroundApi'
import { trendsService, masterPromptService } from '@/services/api'

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
  const [sessionId] = useState(() => `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`)
  const [config, setConfig] = useState<PlaygroundPromptConfig | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
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
  const [bulkSectionsText, setBulkSectionsText] = useState('')
  const batchTestStopRef = useRef(false)
  
  const logsEndRef = useRef<HTMLDivElement>(null)
  const sseCleanupRef = useRef<(() => void) | null>(null)

  // Load default config on mount
  useEffect(() => {
    loadDefaultConfig()
    loadTrends()
    
    // Setup SSE connection
    const cleanup = playgroundApi.createLogStream(
      sessionId,
      (logEntry: LogEntry) => {
        setLogs((prev) => [...prev, logEntry])
      },
      (error: unknown) => {
        console.error('SSE error:', error)
        toast.error('Lost connection to log stream')
      }
    )
    
    sseCleanupRef.current = cleanup
    
    return () => {
      if (sseCleanupRef.current) {
        sseCleanupRef.current()
      }
    }
  }, [sessionId])

  // Auto-scroll logs
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const loadDefaultConfig = async () => {
    try {
      setIsLoading(true)
      const defaultConfig = await playgroundApi.getDefaultConfig()
      setConfig(defaultConfig)
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
      await playgroundApi.saveToTrend(selectedTrendId, config)
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
    for (let i = 0; i < list.length; i++) {
      try {
        await playgroundApi.saveToTrend(list[i].id, config)
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
        const response = await playgroundApi.testPrompt(trendConfig, image1)
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
      setLogs([])
      
      const response = await playgroundApi.testPrompt(config, image1 ?? undefined)
      const mapped: PlaygroundTestResult = {
        success: !!response.imageUrl,
        imageUrl: response.imageUrl,
        image_b64: response.imageUrl?.startsWith('data:') ? response.imageUrl.split(',')[1] : undefined,
        error: response.error,
      }
      setResult(mapped)
      
      if (response.imageUrl) {
        toast.success('Generation completed')
      } else {
        toast.error(`Generation failed: ${response.error ?? 'Unknown error'}`)
      }
    } catch (error: any) {
      console.error('Test failed:', error)
      toast.error(`Test failed: ${error.message}`)
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

  const toggleSection = (sectionId: string) => {
    if (!config) return
    setConfig({
      ...config,
      sections: config.sections.map((s: PlaygroundSection) =>
        s.id === sectionId ? { ...s, enabled: !s.enabled } : s
      ),
    })
  }

  const updateSectionContent = (sectionId: string, content: string) => {
    if (!config) return
    setConfig({
      ...config,
      sections: config.sections.map((s: PlaygroundSection) =>
        s.id === sectionId ? { ...s, content } : s
      ),
    })
  }

  const moveSectionUp = (index: number) => {
    if (!config || index === 0) return
    const newSections = [...config.sections]
    ;[newSections[index - 1], newSections[index]] = [newSections[index], newSections[index - 1]]
    newSections.forEach((s, i) => (s.order = i))
    setConfig({ ...config, sections: newSections })
  }

  const moveSectionDown = (index: number) => {
    if (!config || index === config.sections.length - 1) return
    const newSections = [...config.sections]
    ;[newSections[index], newSections[index + 1]] = [newSections[index + 1], newSections[index]]
    newSections.forEach((s, i) => (s.order = i))
    setConfig({ ...config, sections: newSections })
  }

  const addThreeDefaultSections = () => {
    if (!config) return
    const ts = Date.now()
    setConfig({
      ...config,
      sections: [
        { id: `section_${ts}_0`, label: 'Scene', content: '', enabled: true, order: 0 },
        { id: `section_${ts}_1`, label: 'Style', content: '', enabled: true, order: 1 },
        { id: `section_${ts}_2`, label: 'Avoid', content: '', enabled: true, order: 2 },
      ],
    })
  }

  function parseBulkSectionsText(text: string): { scene: string; style: string; avoid: string } {
    const marker = /^\s*\[?(Scene|Style|Avoid)\]?\s*:?\s*$/im
    const lines = text.split(/\r?\n/)
    let current: 'scene' | 'style' | 'avoid' = 'scene'
    const acc = { scene: [] as string[], style: [] as string[], avoid: [] as string[] }
    for (const line of lines) {
      const m = line.match(marker)
      if (m) {
        const key = m[1].toLowerCase() as 'scene' | 'style' | 'avoid'
        current = key
        continue
      }
      acc[current].push(line)
    }
    return {
      scene: acc.scene.join('\n').trim(),
      style: acc.style.join('\n').trim(),
      avoid: acc.avoid.join('\n').trim(),
    }
  }

  const applyBulkSections = () => {
    if (!config) return
    const { scene, style, avoid } = parseBulkSectionsText(bulkSectionsText)
    const ts = Date.now()
    setConfig({
      ...config,
      sections: [
        { id: `section_${ts}_0`, label: 'Scene', content: scene, enabled: true, order: 0 },
        { id: `section_${ts}_1`, label: 'Style', content: style, enabled: true, order: 1 },
        { id: `section_${ts}_2`, label: 'Avoid', content: avoid, enabled: true, order: 2 },
      ],
    })
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
    const enabledSections = config.sections
      .filter((s: PlaygroundSection) => s.enabled)
      .sort((a: PlaygroundSection, b: PlaygroundSection) => a.order - b.order)
    const sectionsText = enabledSections
      .map((s: PlaygroundSection) => {
        let content = s.content
        for (const [key, value] of Object.entries(config.variables || {})) {
          content = content.replace(new RegExp(`{{${key}}}`, 'g'), String(value))
        }
        const label = (s.label || '').trim().toLowerCase()
        if (label === 'scene') return '[SCENE]\n' + content.trim()
        if (label === 'style') return '[STYLE]\n' + content.trim()
        if (label === 'avoid') return '[AVOID]\n' + content.trim()
        return content.trim()
      })
      .filter(Boolean)
      .join('\n\n')
    if (sectionsText) textBlocks.push(sectionsText)
    const safetyText = (masterSettings?.safety_constraints || '').trim() || 'no text generation, no chat.'
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
    const imageSizeTier = config.image_size_tier ?? '2K'
    const generationConfig: Record<string, unknown> = {
      responseModalities: ['IMAGE'],
      temperature: config.temperature,
      seed: config.seed != null ? Number(config.seed) : 42,
      imageConfig: {
        aspectRatio,
        imageSize: imageSizeTier,
      },
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
          {/* Prompt Sections */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2">
                  <FileJson className="w-5 h-5" />
                  Prompt Sections
                </CardTitle>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={addThreeDefaultSections}
                >
                  Добавить 3 блока
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Ввод 3 блоков за раз */}
              <div className="rounded-lg border bg-muted/30 p-4 space-y-2">
                <h4 className="font-medium text-sm">Ввод 3 блоков за раз</h4>
                <p className="text-xs text-muted-foreground">
                  Используйте метки Scene:, Style:, Avoid: (каждая с новой строки) для разделения блоков. Подойдут также [Scene], [Style], [Avoid].
                </p>
                <textarea
                  value={bulkSectionsText}
                  onChange={(e) => setBulkSectionsText(e.target.value)}
                  placeholder={'Scene:\nописание сцены\n\nStyle:\nстиль\n\nAvoid:\nчего избегать'}
                  className="w-full p-2 border rounded text-sm font-mono min-h-[120px]"
                  rows={6}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={applyBulkSections}
                  disabled={!config}
                >
                  Применить к секциям
                </Button>
              </div>

              {config?.sections.map((section: PlaygroundSection, index: number) => (
                <div
                  key={section.id}
                  className={`border rounded-lg p-4 ${
                    section.enabled ? 'bg-white' : 'bg-gray-50 opacity-60'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => toggleSection(section.id)}
                      >
                        {section.enabled ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                      </Button>
                      <span className="font-mono font-semibold text-sm">{section.label}</span>
                    </div>
                    
                    <div className="flex items-center gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => moveSectionUp(index)}
                        disabled={index === 0}
                      >
                        <ArrowUp className="w-4 h-4" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => moveSectionDown(index)}
                        disabled={index === config.sections.length - 1}
                      >
                        <ArrowDown className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                  
                  <textarea
                    value={section.content}
                    onChange={(e) => updateSectionContent(section.id, e.target.value)}
                    className="w-full p-2 border rounded text-sm font-mono"
                    rows={4}
                    disabled={!section.enabled}
                  />
                </div>
              ))}
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
          <Tabs defaultValue="json">
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="json">Request JSON</TabsTrigger>
              <TabsTrigger value="logs">Logs</TabsTrigger>
              <TabsTrigger value="result">Result</TabsTrigger>
            </TabsList>
            
            {/* JSON Preview */}
            <TabsContent value="json">
              <Card>
                <CardHeader>
                  <CardTitle>Request JSON (Preview)</CardTitle>
                </CardHeader>
                <CardContent>
                  <pre className="bg-gray-50 p-4 rounded text-xs overflow-auto max-h-[600px] font-mono">
                    {JSON.stringify(buildRequestJson(), null, 2)}
                  </pre>
                </CardContent>
              </Card>
            </TabsContent>
            
            {/* Logs */}
            <TabsContent value="logs">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Terminal className="w-5 h-5" />
                    Real-time Logs
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="bg-black text-green-400 p-4 rounded font-mono text-xs h-[600px] overflow-auto">
                    {logs.length === 0 ? (
                      <div className="text-gray-500">Waiting for logs...</div>
                    ) : (
                      logs.map((log: LogEntry, i: number) => (
                        <div key={i} className="mb-1">
                          <span className={`font-bold ${
                            log.level === 'ERROR' ? 'text-red-400' :
                            log.level === 'WARNING' ? 'text-yellow-400' :
                            'text-green-400'
                          }`}>
                            [{String(log.level)}]
                          </span>{' '}
                          <span className="text-gray-400">{log.timestamp ?? ''}</span>{' '}
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
          </Tabs>
        </div>
      </div>
        </TabsContent>

        <TabsContent value="batch" className="mt-0 space-y-4">
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
