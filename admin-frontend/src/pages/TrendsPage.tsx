import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { themesService, trendsService } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Plus, Power, PowerOff, Pencil, ImagePlus, Trash2, ChevronUp, ChevronDown, ChevronRight, FolderPlus, GripVertical } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  DndContext,
  type DragEndEvent,
  type DraggableAttributes,
  type DraggableSyntheticListeners,
  useDraggable,
  useDroppable,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { toast } from 'sonner'
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { parseFullTrendPrompt, buildFullTrendPrompt } from '@/utils/trendPromptParse'
import { cn } from '@/lib/utils'

import type { Theme, Trend } from '@/types'

const DROPPABLE_ID_NONE = 'no-theme'

type ApiErrorShape = { response?: { data?: { detail?: string } }; message?: string }
type ValidationErrorShape = { response?: { data?: { detail?: string | Array<{ msg?: string }> } } }

function getErrorMessage(err: unknown, fallback: string): string {
  const e = err as ApiErrorShape
  const msg = e?.response?.data?.detail ?? e?.message ?? fallback
  return typeof msg === 'string' ? msg : JSON.stringify(msg)
}

function getValidationErrorMessage(err: unknown, fallback: string): string {
  const e = err as ValidationErrorShape
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg
  return fallback
}

function TrendExampleThumb({
  trendId,
  hasExample,
  refreshKey = 0,
}: {
  trendId: string
  hasExample?: boolean
  refreshKey?: number
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const urlRef = useRef<string | null>(null)
  useEffect(() => {
    if (!hasExample) return
    trendsService.getExampleBlobUrl(trendId).then((url) => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
      urlRef.current = url
      setBlobUrl(url)
    })
    return () => {
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current)
        urlRef.current = null
      }
    }
  }, [trendId, hasExample, refreshKey])
  if (!hasExample || !blobUrl) return null
  return (
    <img
      src={blobUrl}
      alt="Пример результата"
      className="w-full h-full object-cover border-0 rounded-none"
    />
  )
}

function TrendStyleRefThumb({
  trendId,
  hasStyleRef,
  refreshKey = 0,
}: {
  trendId: string
  hasStyleRef?: boolean
  refreshKey?: number
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const urlRef = useRef<string | null>(null)
  useEffect(() => {
    if (!hasStyleRef) return
    trendsService
      .getStyleReferenceBlobUrl(trendId)
      .then((url) => {
        if (urlRef.current) URL.revokeObjectURL(urlRef.current)
        urlRef.current = url
        setBlobUrl(url)
      })
      .catch(() => {})
    return () => {
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current)
        urlRef.current = null
      }
    }
  }, [trendId, hasStyleRef, refreshKey])
  if (!hasStyleRef || !blobUrl) return null
  return (
    <img
      src={blobUrl}
      alt="Референс стиля"
      className="w-full h-full object-cover border-0 rounded-none"
    />
  )
}

function DroppableSection({
  id,
  children,
  className,
}: {
  id: string
  children: React.ReactNode
  className?: string
}) {
  const { setNodeRef, isOver } = useDroppable({ id })
  return (
    <section
      ref={setNodeRef}
      className={cn(className, isOver && 'ring-2 ring-primary ring-offset-2 rounded-lg transition-shadow')}
    >
      {children}
    </section>
  )
}

function DraggableTrendCard({
  trend,
  children,
}: {
  trend: Trend
  children: (props: { attributes: DraggableAttributes; listeners: DraggableSyntheticListeners; isDragging: boolean }) => React.ReactNode
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: trend.id })
  return (
    <div ref={setNodeRef} className={isDragging ? 'opacity-50' : ''}>
      {children({ attributes, listeners, isDragging })}
    </div>
  )
}

function ConfigTypeBadge({ trend }: { trend: Trend }) {
  const src = trend.prompt_config_source ?? (trend.prompt_sections && trend.prompt_sections.length > 0 ? 'playground' : 'scene')
  const sections = Array.isArray(trend.prompt_sections) ? trend.prompt_sections.length : 0
  if (src === 'playground' && sections > 0) {
    return (
      <Badge variant="secondary" className="text-xs">
        Playground ({sections} секций)
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="text-xs">
      Сценарный промпт
    </Badge>
  )
}

export function TrendsPage() {
  const queryClient = useQueryClient()
  const [editingTrend, setEditingTrend] = useState<Trend | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [promptPreview, setPromptPreview] = useState<{
    prompt: string
    model: string
    size: string
    format: string
    ratio?: string
    request_as_seen?: string
    request_parts?: Array<{ type: string; order: number; description: string }>
  } | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [mediaRefreshKey, setMediaRefreshKey] = useState(0)
  const [formData, setFormData] = useState<{
    name: string
    description: string
    emoji: string
    order_index: number
    theme_id: string | null
    scene_prompt: string
    negative_scene: string
    subject_mode: string
    framing_hint: string
    style_preset_str: string
    style_preset_mode: 'json' | 'string'
    max_images: number
    enabled: boolean
    system_prompt: string
    subject_prompt: string
    negative_prompt: string
  }>({
    name: '',
    description: '',
    emoji: '',
    order_index: 0,
    theme_id: null,
    scene_prompt: '',
    negative_scene: '',
    subject_mode: 'face',
    framing_hint: 'portrait',
    style_preset_str: '{}',
    style_preset_mode: 'json',
    max_images: 1,
    enabled: true,
    system_prompt: '',
    subject_prompt: '',
    negative_prompt: '',
  })
  const exampleFileInputRef = useRef<HTMLInputElement>(null)
  const styleRefFileInputRef = useRef<HTMLInputElement>(null)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [uploadStyleRefProgress, setUploadStyleRefProgress] = useState<number | null>(null)
  const editButtonRef = useRef<HTMLButtonElement | null>(null)
  const dialogContentRef = useRef<HTMLDivElement>(null)

  const [editingTheme, setEditingTheme] = useState<Theme | null>(null)
  const [isCreatingTheme, setIsCreatingTheme] = useState(false)
  const [themeFormData, setThemeFormData] = useState({ name: '', emoji: '' })
  const [trendFormTab, setTrendFormTab] = useState('basic')
  const [fullPromptText, setFullPromptText] = useState('')
  const [fullPromptDetailsOpen, setFullPromptDetailsOpen] = useState(false)
  const [showSceneError, setShowSceneError] = useState(false)

  const { data: themes = [], isLoading: themesLoading } = useQuery({
    queryKey: ['themes'],
    queryFn: themesService.list,
  })
  const { data: trends = [], isLoading: trendsLoading } = useQuery({
    queryKey: ['trends'],
    queryFn: trendsService.list,
  })

  const groupedByTheme = useMemo(() => {
    const groups: Array<{ theme: Theme | null; trends: Trend[] }> = []
    for (const theme of themes) {
      groups.push({
        theme,
        trends: trends.filter((t) => t.theme_id === theme.id),
      })
    }
    groups.push({
      theme: null,
      trends: trends.filter((t) => t.theme_id == null || t.theme_id === ''),
    })
    return groups
  }, [themes, trends])

  const isLoading = themesLoading || trendsLoading

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      trendsService.update(id, { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trends'] })
      toast.success('Тренд обновлён')
    },
    onError: () => {
      toast.error('Ошибка при обновлении тренда')
    },
  })

  const moveOrderMutation = useMutation({
    mutationFn: ({ id, direction }: { id: string; direction: 'up' | 'down' }) =>
      trendsService.moveOrder(id, direction),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trends'] })
      toast.success('Порядок обновлён')
    },
    onError: () => {
      toast.error('Ошибка при изменении порядка')
    },
  })

  const themeToggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      themesService.update(id, { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['themes'] })
      toast.success('Тематика обновлена')
    },
    onError: () => {
      toast.error('Ошибка при обновлении тематики')
    },
  })

  const themeMoveOrderMutation = useMutation({
    mutationFn: ({ id, direction }: { id: string; direction: 'up' | 'down' }) =>
      themesService.moveOrder(id, direction),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['themes'] })
      toast.success('Порядок тематик обновлён')
    },
    onError: () => {
      toast.error('Ошибка при изменении порядка')
    },
  })

  const themeCreateMutation = useMutation({
    mutationFn: (data: { name: string; emoji: string }) => themesService.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['themes'] })
      toast.success('Тематика создана')
      setIsCreatingTheme(false)
      setThemeFormData({ name: '', emoji: '' })
    },
    onError: (err: unknown) => {
      toast.error(getErrorMessage(err as ApiErrorShape, 'Ошибка при создании тематики'))
    },
  })

  const themeUpdateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name: string; emoji: string } }) =>
      themesService.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['themes'] })
      toast.success('Тематика сохранена')
      setEditingTheme(null)
    },
    onError: (err: unknown) => {
      toast.error(getErrorMessage(err as ApiErrorShape, 'Ошибка при сохранении'))
    },
  })

  const themeDeleteMutation = useMutation({
    mutationFn: (id: string) => themesService.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['themes', 'trends'] })
      toast.success('Тематика удалена, тренды перенесены в «Без тематики»')
      setEditingTheme(null)
    },
    onError: (err: unknown) => {
      toast.error(getErrorMessage(err as ApiErrorShape, 'Ошибка при удалении'))
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Record<string, unknown> }) =>
      trendsService.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trends'] })
      toast.success('Тренд сохранён')
      setEditingTrend(null)
    },
    onError: (err: unknown) => {
      toast.error(getValidationErrorMessage(err, 'Ошибка при сохранении тренда'))
    },
  })

  const moveToThemeMutation = useMutation({
    mutationFn: ({ id, theme_id, order_index }: { id: string; theme_id: string | null; order_index: number }) =>
      trendsService.update(id, { theme_id, order_index }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['trends'] })
      const targetLabel = variables.theme_id == null ? 'Без тематики' : 'тематику'
      toast.success(`Тренд перенесён в ${targetLabel}`)
    },
    onError: () => {
      toast.error('Ошибка при переносе тренда')
    },
  })

  const uploadExampleMutation = useMutation({
    mutationFn: ({
      id,
      file,
      onProgress,
    }: {
      id: string
      file: File
      onProgress?: (percent: number) => void
    }) => trendsService.uploadExample(id, file, onProgress),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['trends'] })
      toast.success('Пример загружен')
      if (editingTrend && editingTrend.id === variables.id) {
        setEditingTrend({ ...editingTrend, has_example: true })
        setMediaRefreshKey((k) => k + 1)
      }
    },
    onError: (err: unknown) => {
      toast.error(getErrorMessage(err, 'Ошибка загрузки примера'))
    },
    onSettled: () => {
      setUploadProgress(null)
    },
  })

  const deleteExampleMutation = useMutation({
    mutationFn: (id: string) => trendsService.deleteExample(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trends'] })
      toast.success('Пример удалён')
      if (editingTrend) setEditingTrend({ ...editingTrend, has_example: false })
    },
    onError: () => {
      toast.error('Ошибка удаления примера')
    },
  })

  const uploadStyleRefMutation = useMutation({
    mutationFn: ({
      id,
      file,
      onProgress,
    }: {
      id: string
      file: File
      onProgress?: (percent: number) => void
    }) => trendsService.uploadStyleReference(id, file, onProgress),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['trends'] })
      toast.success('Референс стиля загружен')
      if (editingTrend && editingTrend.id === variables.id) {
        setEditingTrend({ ...editingTrend, has_style_reference: true })
        setMediaRefreshKey((k) => k + 1)
      }
    },
    onError: (err: unknown) => {
      toast.error(getErrorMessage(err, 'Ошибка загрузки референса'))
    },
    onSettled: () => {
      setUploadStyleRefProgress(null)
    },
  })

  const deleteStyleRefMutation = useMutation({
    mutationFn: (id: string) => trendsService.deleteStyleReference(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trends'] })
      toast.success('Референс стиля удалён')
      if (editingTrend) setEditingTrend({ ...editingTrend, has_style_reference: false })
    },
    onError: () => {
      toast.error('Ошибка удаления референса')
    },
  })

  const createMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => trendsService.create(data as Parameters<typeof trendsService.create>[0]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trends'] })
      toast.success('Тренд создан')
      setIsCreating(false)
      resetForm()
    },
    onError: (err: unknown) => {
      toast.error(getValidationErrorMessage(err, 'Ошибка при создании тренда'))
    },
  })

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },
    })
  )

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event
      if (!over || active.id === over.id) return
      const trendId = String(active.id)
      const overId = String(over.id)
      const trend = trends.find((t) => t.id === trendId)
      if (!trend) return
      const currentThemeId = trend.theme_id ?? DROPPABLE_ID_NONE
      let targetDroppableId = overId
      const overAsTrend = trends.find((t) => t.id === overId)
      if (overAsTrend) {
        targetDroppableId = overAsTrend.theme_id ?? DROPPABLE_ID_NONE
      }
      if (targetDroppableId === currentThemeId) return
      const targetThemeId = targetDroppableId === DROPPABLE_ID_NONE ? null : targetDroppableId
      const targetGroup = groupedByTheme.find(
        (g) => (g.theme?.id ?? DROPPABLE_ID_NONE) === targetDroppableId
      )
      const targetTrends = targetGroup?.trends ?? []
      const newOrderIndex =
        targetTrends.length === 0
          ? 0
          : Math.max(...targetTrends.map((t) => t.order_index), -1) + 1
      moveToThemeMutation.mutate({
        id: trendId,
        theme_id: targetThemeId,
        order_index: newOrderIndex,
      })
    },
    [trends, groupedByTheme, moveToThemeMutation]
  )

  const resetForm = useCallback(() => {
    setFormData({
      name: '',
      description: '',
      emoji: '',
      order_index: (trends?.length ?? 0) + 1,
      theme_id: null,
      scene_prompt: '',
      negative_scene: '',
      subject_mode: 'face',
      framing_hint: 'portrait',
      style_preset_str: '{}',
      style_preset_mode: 'json',
      max_images: 1,
      enabled: true,
      system_prompt: '',
      subject_prompt: '',
      negative_prompt: '',
    })
    setShowSceneError(false)
    setFullPromptDetailsOpen(false)
  }, [trends?.length])

  const handleCreate = (themeId?: string | null) => {
    const nextOrder = Math.max(...(trends?.map((t) => t.order_index) ?? [0]), 0) + 1
    setTrendFormTab('basic')
    setIsCreating(true)
    resetForm()
    setFormData((prev) => ({ ...prev, order_index: nextOrder, theme_id: themeId ?? null }))
  }

  const handleToggle = (id: string, currentEnabled: boolean) => {
    toggleMutation.mutate({ id, enabled: !currentEnabled })
  }

  const handleEdit = (trend: Trend, buttonRef?: HTMLButtonElement | null) => {
    editButtonRef.current = buttonRef ?? null
    setTrendFormTab('basic')
    trendsService.get(trend.id).then((full) => {
      setEditingTrend(full)
      setShowSceneError(false)
      setFullPromptDetailsOpen(false)
      const raw = full.style_preset
    let style_preset_mode: 'json' | 'string' = 'json'
    let style_preset_str: string
    if (raw != null && typeof raw === 'object' && !Array.isArray(raw)) {
      style_preset_mode = 'json'
      style_preset_str = JSON.stringify(raw as Record<string, unknown>, null, 2)
    } else if (typeof raw === 'string') {
      style_preset_mode = 'string'
      style_preset_str = raw
    } else {
      style_preset_str = '{}'
    }
    setFormData({
      name: full.name,
      description: full.description || '',
      emoji: full.emoji || '',
      order_index: full.order_index,
      theme_id: full.theme_id ?? null,
      scene_prompt: (full.scene_prompt as string) || '',
      negative_scene: full.negative_scene || '',
      subject_mode: full.subject_mode || 'face',
      framing_hint: full.framing_hint || 'portrait',
      style_preset_str,
      style_preset_mode,
      max_images: full.max_images ?? 1,
      enabled: full.enabled,
      system_prompt: full.system_prompt || '',
      subject_prompt: full.subject_prompt || '',
      negative_prompt: full.negative_prompt || '',
    })
    setPromptPreview(null)
    setPreviewError(null)
    loadPromptPreview(full.id)
    }).catch(() => {
      toast.error('Не удалось загрузить тренд')
    })
  }

  const loadPromptPreview = async (trendId: string) => {
    setPreviewLoading(true)
    setPreviewError(null)
    try {
      const data = await trendsService.getPromptPreview(trendId)
      setPromptPreview(data as typeof promptPreview)
    } catch (err: unknown) {
      setPreviewError(getErrorMessage(err, 'Ошибка загрузки превью'))
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleSave = (e?: React.MouseEvent) => {
    e?.preventDefault()
    e?.stopPropagation()
    if (!formData.name.trim()) {
      toast.error('Введите название тренда')
      setTrendFormTab('basic')
      return
    }
    if (!formData.emoji.trim()) {
      toast.error('Выберите эмодзи')
      setTrendFormTab('basic')
      return
    }
    const hasScene = !!formData.scene_prompt.trim()
    const hasLegacy = !!formData.system_prompt.trim()
    if (!hasScene && !hasLegacy) {
      setShowSceneError(true)
      setTrendFormTab('prompts')
      toast.error(
        'Заполните блок [SCENE] на вкладке «Промпты».'
      )
      return
    }

    let style_preset: Record<string, unknown> | string
    if (formData.style_preset_mode === 'string') {
      style_preset = formData.style_preset_str
    } else {
      style_preset = {}
      try {
        const trimmed = formData.style_preset_str.trim()
        if (trimmed) {
          const parsed = JSON.parse(formData.style_preset_str)
          if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
            style_preset = parsed
          } else if (typeof parsed === 'string') {
            try {
              const inner = JSON.parse(parsed)
              style_preset =
                typeof inner === 'object' && inner !== null && !Array.isArray(inner) ? inner : {}
            } catch {
              style_preset = {}
            }
          }
        }
      } catch {
        toast.error('Ошибка в JSON style_preset')
        return
      }
    }

    const payload = {
      name: formData.name,
      emoji: formData.emoji,
      description: formData.description,
      order_index: formData.order_index,
      theme_id: formData.theme_id ?? null,
      scene_prompt: formData.scene_prompt,
      negative_scene: formData.negative_scene,
      subject_mode: formData.subject_mode,
      framing_hint: formData.framing_hint,
      style_preset,
      enabled: formData.enabled,
      max_images: formData.max_images,
      system_prompt: formData.system_prompt,
      subject_prompt: formData.subject_prompt,
      negative_prompt: formData.negative_prompt,
    }

    if (editingTrend) {
      updateMutation.mutate({ id: editingTrend.id, data: payload })
    } else {
      createMutation.mutate(payload)
    }
  }

  const handleDialogOpenChange = (open: boolean) => {
    if (!open) {
      setEditingTrend(null)
      setIsCreating(false)
      setTrendFormTab('basic')
      resetForm()
      if (editButtonRef.current && typeof editButtonRef.current.focus === 'function') {
        editButtonRef.current.focus()
      }
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Тренды</h1>
          <p className="text-muted-foreground mt-2">
            Управление трендами генерации изображений
          </p>
          <p className="text-sm text-muted-foreground mt-1">
            Глобальные блоки и перенос личности задаются в{' '}
            <Link to="/master-prompt" className="underline text-primary">
              Мастер промпт
            </Link>
            .
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => { setIsCreatingTheme(true); setThemeFormData({ name: '', emoji: '' }) }}>
            <FolderPlus className="h-4 w-4 mr-2" />
            Создать тематику
          </Button>
          <Button onClick={() => handleCreate()}>
            <Plus className="h-4 w-4 mr-2" />
            Создать тренд
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="overflow-hidden">
              <Skeleton className="aspect-video w-full rounded-t-lg" />
              <CardHeader className="pb-3">
                <Skeleton className="h-6 w-32" />
                <Skeleton className="h-4 w-24 mt-2" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-4 w-full mb-2" />
                <Skeleton className="h-4 w-3/4 mb-4" />
                <div className="flex gap-2">
                  <Skeleton className="h-9 flex-1" />
                  <Skeleton className="h-9 w-24" />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
          <div className="space-y-8">
            {groupedByTheme.map(({ theme, trends: groupTrends }) => {
              const themeLabel = theme ? `${theme.emoji || ''} ${theme.name}`.trim() || theme.name : 'Без тематики'
              const themeIndex = theme ? themes.findIndex((t) => t.id === theme.id) : -1
              const canThemeMoveUp = theme != null && themeIndex > 0
              const canThemeMoveDown = theme != null && themeIndex >= 0 && themeIndex < themes.length - 1
              const droppableId = theme?.id ?? DROPPABLE_ID_NONE
              return (
                <DroppableSection key={droppableId} id={droppableId} className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2 border-b pb-2">
                    <h2 className="text-xl font-semibold">{themeLabel}</h2>
                    {theme != null && (
                      <>
                        <div className="flex items-center rounded-md border border-input">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => themeMoveOrderMutation.mutate({ id: theme.id, direction: 'up' })}
                            disabled={!canThemeMoveUp || themeMoveOrderMutation.isPending}
                            aria-label="Поднять тематику"
                          >
                            <ChevronUp className="h-4 w-4" />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => themeMoveOrderMutation.mutate({ id: theme.id, direction: 'down' })}
                            disabled={!canThemeMoveDown || themeMoveOrderMutation.isPending}
                            aria-label="Опустить тематику"
                          >
                            <ChevronDown className="h-4 w-4" />
                          </Button>
                        </div>
                        <Badge variant={theme.enabled ? 'default' : 'secondary'}>
                          {theme.enabled ? 'Вкл.' : 'Выкл.'}
                        </Badge>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => themeToggleMutation.mutate({ id: theme.id, enabled: !theme.enabled })}
                          disabled={themeToggleMutation.isPending}
                        >
                          {theme.enabled ? 'Выключить тему' : 'Включить тему'}
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setEditingTheme(theme)}
                          aria-label={`Редактировать тематику ${theme.name}`}
                        >
                          <Pencil className="h-4 w-4 mr-1" />
                          Редактировать
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => themeDeleteMutation.mutate(theme.id)}
                          disabled={themeDeleteMutation.isPending}
                          aria-label={`Удалить тематику ${theme.name}`}
                        >
                          <Trash2 className="h-4 w-4 mr-1" />
                          Удалить
                        </Button>
                      </>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleCreate(theme?.id ?? null)}
                      aria-label={`Добавить тренд в ${themeLabel}`}
                    >
                      <Plus className="h-4 w-4 mr-1" />
                      Добавить тренд
                    </Button>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                    {groupTrends.map((trend, index) => (
                      <DraggableTrendCard key={trend.id} trend={trend}>
                        {({ attributes, listeners }) => (
                          <Card className="overflow-hidden">
                            {trend.has_example && (
                              <div className="aspect-video bg-muted overflow-hidden rounded-t-lg">
                                <TrendExampleThumb trendId={trend.id} hasExample={trend.has_example} />
                              </div>
                            )}
                            <CardHeader className="pb-3">
                              <div className="flex items-start justify-between gap-2">
                                <div className="flex flex-col gap-1 min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span
                                      {...attributes}
                                      {...listeners}
                                      className="cursor-grab touch-none shrink-0 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                                      aria-label="Перетащить в другую тематику"
                                    >
                                      <GripVertical className="h-5 w-5" />
                                    </span>
                                    <span className="text-3xl shrink-0">{trend.emoji}</span>
                                    <div className="min-w-0">
                                      <CardTitle className="text-lg truncate">{trend.name}</CardTitle>
                                      <p className="text-xs text-muted-foreground mt-1">
                                        Порядок: {trend.order_index}
                                        {trend.has_example && ' · Есть пример'}
                                        {trend.has_style_reference && ' · Референс'}
                                      </p>
                                    </div>
                                  </div>
                                  <ConfigTypeBadge trend={trend} />
                                </div>
                                <Badge variant={trend.enabled ? 'success' : 'error'}>
                                  {trend.enabled ? 'Включен' : 'Выключен'}
                                </Badge>
                              </div>
                            </CardHeader>
                            <CardContent>
                              <p className="text-sm text-muted-foreground line-clamp-2 mb-4">
                                {trend.description}
                              </p>
                              <div className="flex flex-wrap items-center gap-2">
                                <div className="flex items-center rounded-md border border-input">
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8"
                                    onClick={() => moveOrderMutation.mutate({ id: trend.id, direction: 'up' })}
                                    disabled={moveOrderMutation.isPending || index === 0}
                                    aria-label="Поднять в списке"
                                  >
                                    <ChevronUp className="h-4 w-4" />
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8"
                                    onClick={() => moveOrderMutation.mutate({ id: trend.id, direction: 'down' })}
                                    disabled={moveOrderMutation.isPending || index >= groupTrends.length - 1}
                                    aria-label="Опустить в списке"
                                  >
                                    <ChevronDown className="h-4 w-4" />
                                  </Button>
                                </div>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="flex-1 min-w-0"
                                  onClick={() => handleToggle(trend.id, trend.enabled)}
                                  disabled={toggleMutation.isPending}
                                >
                                  {trend.enabled ? (
                                    <>
                                      <PowerOff className="h-4 w-4 mr-2" />
                                      Выключить
                                    </>
                                  ) : (
                                    <>
                                      <Power className="h-4 w-4 mr-2" />
                                      Включить
                                    </>
                                  )}
                                </Button>
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  onClick={(e) => handleEdit(trend, e.currentTarget)}
                                  aria-label={`Редактировать тренд ${trend.name}`}
                                >
                                  <Pencil className="h-4 w-4 mr-2" />
                                  Редактировать
                                </Button>
                              </div>
                            </CardContent>
                          </Card>
                        )}
                      </DraggableTrendCard>
                    ))}
                  </div>
                </DroppableSection>
              )
            })}
          </div>
        </DndContext>
      )}

      <Dialog open={!!editingTrend || isCreating} onOpenChange={handleDialogOpenChange}>
        <DialogContent
          ref={dialogContentRef}
          className="sm:max-w-[900px] max-h-[90vh] overflow-y-auto"
          onCloseAutoFocus={(e) => {
            if (editButtonRef.current) {
              e.preventDefault()
              editButtonRef.current.focus()
            }
          }}
          onEscapeKeyDown={() => handleDialogOpenChange(false)}
        >
          <DialogHeader>
            <DialogTitle id="trend-dialog-title">
              {editingTrend ? 'Редактирование тренда' : 'Создание нового тренда'}
            </DialogTitle>
            <DialogDescription id="trend-dialog-desc">
              {editingTrend
                ? 'Все параметры генерации в одном месте'
                : 'Заполните все поля для создания нового тренда'}
            </DialogDescription>
          </DialogHeader>

          <Tabs value={trendFormTab} onValueChange={setTrendFormTab} className="w-full">
            <TabsList className="grid w-full grid-cols-4" role="tablist" aria-label="Вкладки формы тренда">
              <TabsTrigger value="basic" role="tab">Основное</TabsTrigger>
              <TabsTrigger value="prompts" role="tab">Промпты</TabsTrigger>
              <TabsTrigger value="media" role="tab">Медиа</TabsTrigger>
              <TabsTrigger value="preview" role="tab">Превью</TabsTrigger>
            </TabsList>

            <TabsContent value="basic" className="mt-4 space-y-6">
              <fieldset className="space-y-4 rounded-lg border p-4">
                <legend className="text-sm font-medium px-1">Основные данные</legend>
                <div className="grid gap-2">
                  <Label htmlFor="theme">Тематика</Label>
                  <Select
                    value={formData.theme_id ?? '__none__'}
                    onValueChange={(v) =>
                      setFormData({ ...formData, theme_id: v === '__none__' ? null : v })
                    }
                  >
                    <SelectTrigger id="theme" aria-label="Тематика">
                      <SelectValue placeholder="Без тематики" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none__">Без тематики</SelectItem>
                      {themes.map((t) => (
                        <SelectItem key={t.id} value={t.id}>
                          {t.emoji ? `${t.emoji} ` : ''}{t.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="name">Название *</Label>
                  <Input
                    id="name"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="Любовный взгляд"
                    aria-required
                  />
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div className="grid gap-2">
                    <Label htmlFor="emoji">Эмодзи *</Label>
                    <Input
                      id="emoji"
                      value={formData.emoji}
                      onChange={(e) => setFormData({ ...formData, emoji: e.target.value })}
                      placeholder="❤️"
                      className="text-2xl"
                      aria-required
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="order">Порядок</Label>
                    <Input
                      id="order"
                      type="number"
                      value={formData.order_index}
                      onChange={(e) =>
                        setFormData({ ...formData, order_index: parseInt(e.target.value, 10) || 0 })
                      }
                      aria-label="Порядок отображения"
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="max_images">Макс. изображений</Label>
                    <Input
                      id="max_images"
                      type="number"
                      value={formData.max_images}
                      onChange={(e) =>
                        setFormData({ ...formData, max_images: parseInt(e.target.value, 10) || 1 })
                      }
                      min={1}
                      aria-label="Максимум изображений"
                    />
                  </div>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="description">Описание</Label>
                  <Textarea
                    id="description"
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    rows={2}
                    aria-describedby="description-hint"
                  />
                </div>
              </fieldset>

              <fieldset className="space-y-4 rounded-lg border p-4">
                <legend className="text-sm font-medium px-1">Параметры кадра</legend>
                <div className="grid gap-2">
                  <Label htmlFor="subject_mode">Область объекта</Label>
                  <Select
                    value={formData.subject_mode}
                    onValueChange={(v) => setFormData({ ...formData, subject_mode: v })}
                  >
                    <SelectTrigger id="subject_mode" aria-label="Область объекта">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="face">Лицо</SelectItem>
                      <SelectItem value="head_torso">Голова и торс</SelectItem>
                      <SelectItem value="full_body">В полный рост</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="framing_hint">Кадрирование</Label>
                  <Select
                    value={formData.framing_hint}
                    onValueChange={(v) => setFormData({ ...formData, framing_hint: v })}
                  >
                    <SelectTrigger id="framing_hint" aria-label="Кадрирование">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="close_up">Крупный план</SelectItem>
                      <SelectItem value="portrait">Портрет</SelectItem>
                      <SelectItem value="half_body">По пояс</SelectItem>
                      <SelectItem value="full_body">В полный рост</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </fieldset>

              <fieldset className="space-y-4 rounded-lg border p-4">
                <legend className="text-sm font-medium px-1">Публикация</legend>
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="enabled"
                    checked={formData.enabled}
                    onChange={(e) => setFormData({ ...formData, enabled: e.target.checked })}
                    className="h-4 w-4"
                    aria-describedby="enabled-desc"
                  />
                  <Label id="enabled-desc" htmlFor="enabled" className="cursor-pointer">
                    Включить тренд сразу после создания
                  </Label>
                </div>
              </fieldset>
            </TabsContent>

            <TabsContent value="prompts" className="mt-4 space-y-6">
              <div className="rounded-lg border bg-muted/30">
                <button
                  type="button"
                  onClick={() => setFullPromptDetailsOpen((o) => !o)}
                  className="flex w-full cursor-pointer items-center gap-2 px-4 py-2 text-left font-medium"
                  aria-expanded={fullPromptDetailsOpen}
                >
                  {fullPromptDetailsOpen ? (
                    <ChevronDown className="h-4 w-4 shrink-0" aria-hidden />
                  ) : (
                    <ChevronRight className="h-4 w-4 shrink-0" aria-hidden />
                  )}
                  Вставить полным текстом
                </button>
                {fullPromptDetailsOpen && (
                  <div className="border-t p-4 space-y-3">
                    <p className="text-xs text-muted-foreground">
                      Формат: на отдельных строках [SCENE], [STYLE], [AVOID], далее текст до следующего блока. Порядок блоков любой.
                    </p>
                    <Textarea
                      value={fullPromptText}
                      onChange={(e) => setFullPromptText(e.target.value)}
                      rows={8}
                      placeholder={'[SCENE]\nсцена...\n[STYLE]\n{}\n[AVOID]\nнегатив'}
                      className="font-mono text-sm"
                      aria-label="Полный промпт тренда: блоки [SCENE], [STYLE], [AVOID]"
                    />
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() => {
                          const parsed = parseFullTrendPrompt(fullPromptText)
                          setFormData((prev) => ({
                            ...prev,
                            scene_prompt: parsed.scene,
                            negative_scene: parsed.avoid,
                            style_preset_str: parsed.style,
                            style_preset_mode: parsed.styleParsedAsJson ? 'json' : 'string',
                          }))
                          toast.success('Поля Сцена, Стиль и Негатив заполнены')
                          if (!parsed.styleParsedAsJson && parsed.style.trim()) {
                            toast.info('Стиль сохранён как текст (JSON не распознан)')
                          }
                        }}
                        aria-label="Разобрать полный промпт в блоки Сцена, Стиль, Негатив"
                      >
                        Разобрать в блоки
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          const built = buildFullTrendPrompt(
                            formData.scene_prompt,
                            formData.style_preset_str,
                            formData.negative_scene
                          )
                          setFullPromptText(built)
                        }}
                        aria-label="Собрать из блоков Сцена, Стиль, Негатив в один текст"
                      >
                        Собрать из блоков
                      </Button>
                    </div>
                  </div>
                )}
              </div>

              <p className="rounded-md border border-border/50 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                Тренд состоит из трёх блоков. Глобальные блоки (
                [IDENTITY TRANSFER], [COMPOSITION]) — в{' '}
                <Link to="/master-prompt" className="underline text-primary">
                  Мастер промпт
                </Link>
                .
              </p>

              <div className="space-y-4 rounded-lg border border-border/50 bg-muted/30 p-4">
                <h3 className="text-sm font-medium">
                  <span className="font-mono text-muted-foreground">[SCENE]</span> Сцена *
                </h3>
                <div className="grid gap-2">
                  <Label htmlFor="scene_prompt" className="sr-only">Сцена</Label>
                  <Textarea
                    id="scene_prompt"
                    value={formData.scene_prompt}
                    onChange={(e) => {
                      setFormData({ ...formData, scene_prompt: e.target.value })
                      if (e.target.value.trim()) setShowSceneError(false)
                    }}
                    rows={4}
                    placeholder="Опиши окружение, свет, атмосферу..."
                    className={cn(
                      'font-mono text-sm',
                      showSceneError && 'border-destructive focus-visible:ring-destructive'
                    )}
                    aria-required
                    aria-invalid={showSceneError}
                    aria-describedby={showSceneError ? 'scene_prompt_error' : undefined}
                  />
                  {showSceneError && (
                    <p id="scene_prompt_error" className="text-xs text-destructive">
                      Поле не должно быть пустым.
                    </p>
                  )}
                </div>
              </div>

              <div className="space-y-4 rounded-lg border border-border/50 bg-muted/30 p-4">
                <h3 className="text-sm font-medium">
                  <span className="font-mono text-muted-foreground">[STYLE]</span> Стиль
                </h3>
                <div className="grid gap-2">
                  <div className="flex items-center gap-4 text-sm">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="style_preset_mode"
                        checked={formData.style_preset_mode === 'json'}
                        onChange={() => setFormData({ ...formData, style_preset_mode: 'json' })}
                        className="rounded border-input"
                        aria-label="JSON объект"
                      />
                      <span>JSON</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="style_preset_mode"
                        checked={formData.style_preset_mode === 'string'}
                        onChange={() => setFormData({ ...formData, style_preset_mode: 'string' })}
                        className="rounded border-input"
                        aria-label="Текст"
                      />
                      <span>Текст</span>
                    </label>
                  </div>
                  <Textarea
                    id="style_preset"
                    value={formData.style_preset_str}
                    onChange={(e) => setFormData({ ...formData, style_preset_str: e.target.value })}
                    rows={3}
                    placeholder={
                      formData.style_preset_mode === 'json'
                        ? '{"style": "cinematic", "quality": "high"}'
                        : 'Произвольный текст стиля...'
                    }
                    className="font-mono text-sm"
                    aria-label="[STYLE] Стиль"
                  />
                </div>
              </div>

              <div className="space-y-4 rounded-lg border border-border/50 bg-muted/30 p-4">
                <h3 className="text-sm font-medium">
                  <span className="font-mono text-muted-foreground">[AVOID]</span> Негатив сцены
                </h3>
                <div className="grid gap-2">
                  <Label htmlFor="negative_scene" className="sr-only">Негатив сцены</Label>
                  <Textarea
                    id="negative_scene"
                    value={formData.negative_scene}
                    onChange={(e) => setFormData({ ...formData, negative_scene: e.target.value })}
                    rows={2}
                    placeholder="Что исключить из сцены..."
                    aria-label="[AVOID] Негатив сцены"
                  />
                </div>
              </div>
            </TabsContent>

            <TabsContent value="media" className="space-y-4 mt-4">
              {editingTrend && (
                <>
                  <div className="grid gap-2">
                    <Label>Пример результата</Label>
                    <p className="text-xs text-muted-foreground">
                      Показывается пользователю в боте после выбора тренда. Форматы: JPG, PNG, WebP.
                    </p>
                    {editingTrend.has_example && (
                      <div className="flex items-center gap-2">
                        <div className="flex-1 min-h-[80px] rounded border bg-muted flex items-center justify-center overflow-hidden">
                          <TrendExampleThumb
                            trendId={editingTrend.id}
                            hasExample={editingTrend.has_example}
                            refreshKey={mediaRefreshKey}
                          />
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => deleteExampleMutation.mutate(editingTrend.id)}
                          disabled={deleteExampleMutation.isPending}
                          aria-label="Удалить пример"
                        >
                          <Trash2 className="h-4 w-4 mr-1" />
                          Удалить
                        </Button>
                      </div>
                    )}
                    {uploadProgress !== null && (
                      <div className="space-y-1">
                        <div className="flex justify-between text-xs text-muted-foreground">
                          <span>Загрузка...</span>
                          <span>{uploadProgress}%</span>
                        </div>
                        <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full bg-primary transition-[width] duration-200"
                            style={{ width: `${uploadProgress}%` }}
                          />
                        </div>
                      </div>
                    )}
                    <div className="flex gap-2">
                      <input
                        ref={exampleFileInputRef}
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        className="hidden"
                        aria-hidden
                        onChange={(e) => {
                          const file = e.target.files?.[0]
                          if (file && editingTrend) {
                            setUploadProgress(0)
                            uploadExampleMutation.mutate({
                              id: editingTrend.id,
                              file,
                              onProgress: setUploadProgress,
                            })
                            e.target.value = ''
                          }
                        }}
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => exampleFileInputRef.current?.click()}
                        disabled={uploadExampleMutation.isPending}
                        aria-label={editingTrend.has_example ? 'Заменить пример' : 'Загрузить пример'}
                      >
                        <ImagePlus className="h-4 w-4 mr-1" />
                        {editingTrend.has_example ? 'Заменить пример' : 'Загрузить пример'}
                      </Button>
                    </div>
                  </div>
                  <div className="grid gap-2">
                    <Label>Референс стиля (для Gemini)</Label>
                    <p className="text-xs text-muted-foreground">
                      Отправляется в Gemini как IMAGE_2: освещение, композиция, настроение.
                    </p>
                    {editingTrend.has_style_reference && (
                      <div className="flex items-center gap-2">
                        <div className="flex-1 min-h-[80px] rounded border bg-muted flex items-center justify-center overflow-hidden">
                          <TrendStyleRefThumb
                            trendId={editingTrend.id}
                            hasStyleRef={editingTrend.has_style_reference}
                            refreshKey={mediaRefreshKey}
                          />
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => deleteStyleRefMutation.mutate(editingTrend.id)}
                          disabled={deleteStyleRefMutation.isPending}
                          aria-label="Удалить референс стиля"
                        >
                          <Trash2 className="h-4 w-4 mr-1" />
                          Удалить
                        </Button>
                      </div>
                    )}
                    {uploadStyleRefProgress !== null && (
                      <div className="space-y-1">
                        <div className="flex justify-between text-xs text-muted-foreground">
                          <span>Загрузка референса...</span>
                          <span>{uploadStyleRefProgress}%</span>
                        </div>
                        <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full bg-primary transition-[width] duration-200"
                            style={{ width: `${uploadStyleRefProgress}%` }}
                          />
                        </div>
                      </div>
                    )}
                    <div className="flex gap-2">
                      <input
                        ref={styleRefFileInputRef}
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        className="hidden"
                        aria-hidden
                        onChange={(e) => {
                          const file = e.target.files?.[0]
                          if (file && editingTrend) {
                            setUploadStyleRefProgress(0)
                            uploadStyleRefMutation.mutate({
                              id: editingTrend.id,
                              file,
                              onProgress: setUploadStyleRefProgress,
                            })
                            e.target.value = ''
                          }
                        }}
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => styleRefFileInputRef.current?.click()}
                        disabled={uploadStyleRefMutation.isPending}
                        aria-label={
                          editingTrend.has_style_reference ? 'Заменить референс' : 'Загрузить референс'
                        }
                      >
                        <ImagePlus className="h-4 w-4 mr-1" />
                        {editingTrend.has_style_reference ? 'Заменить референс' : 'Загрузить референс'}
                      </Button>
                    </div>
                  </div>
                </>
              )}
              {!editingTrend && (
                <p className="text-sm text-muted-foreground">
                  Сохраните тренд, затем откройте редактирование, чтобы загрузить пример и референс стиля.
                </p>
              )}
            </TabsContent>

            <TabsContent value="preview" className="space-y-4 mt-4">
              {editingTrend && (
                <div className="grid gap-2">
                  <Label>Prompt Preview (Gemini)</Label>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => loadPromptPreview(editingTrend.id)}
                      disabled={previewLoading}
                      aria-label="Обновить превью промпта"
                    >
                      {previewLoading ? 'Загрузка...' : 'Обновить превью'}
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      Финальный промпт (TransferPolicy + тренд).
                    </span>
                  </div>
                  {previewError && (
                    <p className="text-xs text-red-500" role="alert">
                      {previewError}
                    </p>
                  )}
                  {promptPreview && (
                    <>
                      <p className="text-xs text-muted-foreground">
                        {promptPreview.request_as_seen ??
                          'contents[0].parts = [ image (user photo), text (prompt) ]'}
                      </p>
                      <pre className="whitespace-pre-wrap rounded-md bg-muted p-3 text-xs leading-relaxed">
                        {promptPreview.prompt}
                      </pre>
                      <p className="text-xs text-muted-foreground">
                        model: {promptPreview.model} · size: {promptPreview.size} · format:{' '}
                        {promptPreview.format}
                      </p>
                    </>
                  )}
                </div>
              )}
              {!editingTrend && (
                <p className="text-sm text-muted-foreground">
                  Сохраните тренд и откройте редактирование, чтобы увидеть превью промпта.
                </p>
              )}
            </TabsContent>
          </Tabs>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => handleDialogOpenChange(false)}
              type="button"
              aria-label="Отмена"
            >
              Отмена
            </Button>
            <Button
              type="button"
              onClick={(e) => handleSave(e)}
              disabled={updateMutation.isPending || createMutation.isPending}
              aria-label={editingTrend ? 'Сохранить изменения' : 'Создать тренд'}
            >
              {updateMutation.isPending || createMutation.isPending
                ? 'Сохранение...'
                : editingTrend
                  ? 'Сохранить изменения'
                  : 'Создать тренд'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={isCreatingTheme || editingTheme !== null}
        onOpenChange={(open) => {
          if (!open) {
            setIsCreatingTheme(false)
            setEditingTheme(null)
          }
        }}
      >
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle>
              {editingTheme ? 'Редактирование тематики' : 'Новая тематика'}
            </DialogTitle>
            <DialogDescription>
              {editingTheme
                ? 'Измените название и эмодзи тематики.'
                : 'Тематики группируют тренды (например, «23 февраля», «14 февраля»).'}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="theme-name">Название</Label>
              <Input
                id="theme-name"
                value={editingTheme ? editingTheme.name : themeFormData.name}
                onChange={(e) =>
                  editingTheme
                    ? setEditingTheme({ ...editingTheme, name: e.target.value })
                    : setThemeFormData((prev) => ({ ...prev, name: e.target.value }))
                }
                placeholder="23 февраля"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="theme-emoji">Эмодзи</Label>
              <Input
                id="theme-emoji"
                value={editingTheme ? editingTheme.emoji : themeFormData.emoji}
                onChange={(e) =>
                  editingTheme
                    ? setEditingTheme({ ...editingTheme, emoji: e.target.value })
                    : setThemeFormData((prev) => ({ ...prev, emoji: e.target.value }))
                }
                placeholder="🎖"
                className="text-2xl"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setIsCreatingTheme(false)
                setEditingTheme(null)
              }}
            >
              Отмена
            </Button>
            {editingTheme ? (
              <>
                <Button
                  variant="destructive"
                  onClick={() => {
                    if (confirm('Удалить тематику? Тренды перейдут в «Без тематики».')) {
                      themeDeleteMutation.mutate(editingTheme.id)
                    }
                  }}
                  disabled={themeDeleteMutation.isPending}
                >
                  Удалить
                </Button>
                <Button
                  onClick={() =>
                    themeUpdateMutation.mutate({
                      id: editingTheme.id,
                      data: {
                        name: editingTheme.name,
                        emoji: editingTheme.emoji || '',
                      },
                    })
                  }
                  disabled={themeUpdateMutation.isPending || !editingTheme.name.trim()}
                >
                  {themeUpdateMutation.isPending ? 'Сохранение...' : 'Сохранить'}
                </Button>
              </>
            ) : (
              <Button
                onClick={() =>
                  themeCreateMutation.mutate({
                    name: themeFormData.name.trim(),
                    emoji: themeFormData.emoji.trim() || '',
                  })
                }
                disabled={themeCreateMutation.isPending || !themeFormData.name.trim()}
              >
                {themeCreateMutation.isPending ? 'Создание...' : 'Создать'}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
