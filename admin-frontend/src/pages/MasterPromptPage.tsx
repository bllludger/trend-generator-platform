import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  masterPromptService,
  transferPolicyService,
  type MasterPromptSettings,
  type MasterPromptSettingsResponse,
  type TransferPolicySettings,
} from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Loader2, Save, FileText, UserCog, TrendingUp, Zap } from 'lucide-react'
import { useState, useEffect } from 'react'
import { toast } from 'sonner'

const MASTER_BLOCK_MARKERS = ['[INPUT]', '[TASK]'] as const

function masterBlocksToFullText(s: Partial<MasterPromptSettings>): string {
  const parts = [
    '[INPUT]',
    (s.prompt_input ?? '').trim(),
    '[TASK]',
    (s.prompt_task ?? '').trim(),
  ]
  return parts.join('\n\n')
}

function parseMasterBlocksFullText(text: string): { prompt_input: string; prompt_task: string } {
  const result = { prompt_input: '', prompt_task: '' }
  const keys: (keyof typeof result)[] = ['prompt_input', 'prompt_task']
  let currentKey: keyof typeof result | null = null
  const lines = text.split(/\r?\n/)
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const marker = MASTER_BLOCK_MARKERS.find((m) => line.trim() === m)
    if (marker) {
      const idx = MASTER_BLOCK_MARKERS.indexOf(marker)
      currentKey = keys[idx]
      continue
    }
    if (currentKey) {
      result[currentKey] = (result[currentKey] + (result[currentKey] ? '\n' : '') + line).trim()
    }
  }
  return result
}

export function MasterPromptPage() {
  const queryClient = useQueryClient()

  const { data: masterSettings, isLoading: masterLoading } = useQuery({
    queryKey: ['master-prompt-settings'],
    queryFn: () => masterPromptService.getSettings(),
  })
  const { data: transferSettings, isLoading: transferLoading } = useQuery({
    queryKey: ['transfer-policy-settings'],
    queryFn: () => transferPolicyService.getSettings(),
  })

  const [masterForm, setMasterForm] = useState<Partial<MasterPromptSettings>>({})
  const [masterBlocksText, setMasterBlocksText] = useState('')
  const [previewForm, setPreviewForm] = useState<Partial<MasterPromptSettings>>({})
  const [releaseForm, setReleaseForm] = useState<Partial<MasterPromptSettings>>({})
  const [globalForm, setGlobalForm] = useState<Partial<TransferPolicySettings>>({})
  const [trendsForm, setTrendsForm] = useState<Partial<TransferPolicySettings>>({})
  useEffect(() => {
    if (masterSettings?.preview) {
      setMasterForm(masterSettings.preview)
      setMasterBlocksText(masterBlocksToFullText(masterSettings.preview))
    }
  }, [masterSettings?.preview])
  useEffect(() => {
    if (masterSettings?.preview) setPreviewForm(masterSettings.preview)
  }, [masterSettings?.preview])
  useEffect(() => {
    if (masterSettings?.release) setReleaseForm(masterSettings.release)
  }, [masterSettings?.release])
  useEffect(() => {
    if (transferSettings?.global) setGlobalForm(transferSettings.global)
  }, [transferSettings?.global])
  useEffect(() => {
    if (transferSettings?.trends) setTrendsForm(transferSettings.trends)
  }, [transferSettings?.trends])

  const masterMutation = useMutation({
    mutationFn: masterPromptService.updateSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['master-prompt-settings'] })
      toast.success('Настройки сохранены')
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail ?? (err as Error).message
      toast.error(typeof msg === 'string' ? msg : 'Ошибка сохранения')
    },
  })
  const transferMutation = useMutation({
    mutationFn: (payload: { global?: Partial<TransferPolicySettings>; trends?: Partial<TransferPolicySettings> }) =>
      transferPolicyService.updateSettings(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transfer-policy-settings'] })
      toast.success('Настройки переноса личности сохранены')
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail ?? (err as Error).message
      toast.error(typeof msg === 'string' ? msg : 'Ошибка сохранения')
    },
  })

  const handleMasterSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const parsed = parseMasterBlocksFullText(masterBlocksText)
    masterMutation.mutate({
      preview: {
        ...masterSettings?.preview,
        ...masterForm,
        ...parsed,
        prompt_input_enabled: true,
        prompt_task_enabled: true,
        prompt_identity_transfer_enabled: false,
        safety_constraints_enabled: false,
      },
    })
  }
  const handlePreviewSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    masterMutation.mutate({ preview: { ...masterSettings?.preview, ...previewForm } })
  }
  const handleReleaseSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    masterMutation.mutate({ release: { ...masterSettings?.release, ...releaseForm } })
  }
  const handleGlobalSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    transferMutation.mutate({ global: { ...transferSettings?.global, ...globalForm } })
  }
  const handleTrendsSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    transferMutation.mutate({ trends: { ...transferSettings?.trends, ...trendsForm } })
  }

  const isLoading = masterLoading || transferLoading
  const masterData = masterSettings as MasterPromptSettingsResponse | undefined
  if (isLoading || !masterData?.preview || !masterData?.release || !transferSettings) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  const renderTransferForm = (
    scope: 'global' | 'trends',
    current: TransferPolicySettings,
    setForm: React.Dispatch<React.SetStateAction<Partial<TransferPolicySettings>>>,
    onSubmit: (e: React.FormEvent) => void,
    pending: boolean
  ) => {
    const handleChange = (key: keyof TransferPolicySettings, value: string) => {
      setForm((prev) => ({ ...prev, [key]: value }))
    }
    return (
      <form onSubmit={onSubmit}>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {scope === 'global' ? 'Для Copy style, Playground и др.' : 'Для генерации по трендам'}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2">
              <Label>subject_reference_name</Label>
              <Input
                value={current.subject_reference_name ?? ''}
                onChange={(e) => handleChange('subject_reference_name', e.target.value)}
                placeholder="IMAGE_1"
              />
            </div>
            <div className="grid gap-2">
              <Label>identity_lock_level</Label>
              <Input
                value={current.identity_lock_level ?? ''}
                onChange={(e) => handleChange('identity_lock_level', e.target.value)}
                placeholder="strict"
              />
            </div>
            <div className="grid gap-2">
              <Label>identity_rules_text → [IDENTITY TRANSFER]</Label>
              <Textarea
                rows={4}
                className="font-mono text-sm"
                value={current.identity_rules_text ?? ''}
                onChange={(e) => handleChange('identity_rules_text', e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label>composition_rules_text → [COMPOSITION]</Label>
              <Textarea
                rows={3}
                className="font-mono text-sm"
                value={current.composition_rules_text ?? ''}
                onChange={(e) => handleChange('composition_rules_text', e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label>avoid_default_items → [AVOID]</Label>
              <Textarea
                rows={8}
                className="font-mono text-sm"
                placeholder="По одному на строку или через ;"
                value={current.avoid_default_items ?? ''}
                onChange={(e) => handleChange('avoid_default_items', e.target.value)}
              />
            </div>
            <Button type="submit" disabled={pending}>
              {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Сохранить
            </Button>
          </CardContent>
        </Card>
      </form>
    )
  }

  const globalCurrent = { ...transferSettings.global, ...globalForm }
  const trendsCurrent = { ...transferSettings.trends, ...trendsForm }

  const GLOBAL_MODEL_OPTIONS = [
    { value: 'gemini-2.5-flash-image', label: 'gemini-2.5-flash-image' },
    { value: 'gemini-3-pro-image-preview', label: 'gemini-3-pro-image-preview (Nano Banana Pro)' },
    { value: 'gemini-3.1-flash-image-preview', label: 'gemini-3.1-flash-image-preview (NeoBanana 2)' },
  ] as const

  const renderGlobalDefaultsForm = (
    _profile: 'preview' | 'release',
    current: Partial<MasterPromptSettings>,
    setForm: React.Dispatch<React.SetStateAction<Partial<MasterPromptSettings>>>,
    onSubmit: (e: React.FormEvent) => void,
    title: string,
    description: string
  ) => (
    <form onSubmit={onSubmit}>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{title}</CardTitle>
          <p className="text-sm text-muted-foreground">{description}</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label>default_model</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={current.default_model ?? 'gemini-2.5-flash-image'}
                onChange={(e) => setForm((prev) => ({ ...prev, default_model: e.target.value }))}
              >
                {GLOBAL_MODEL_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div className="grid gap-2">
              <Label>default_size</Label>
              <Input
                value={current.default_size ?? ''}
                onChange={(e) => setForm((prev) => ({ ...prev, default_size: e.target.value }))}
                placeholder="1024x1024"
              />
            </div>
            <div className="grid gap-2">
              <Label>default_format</Label>
              <Input
                value={current.default_format ?? ''}
                onChange={(e) => setForm((prev) => ({ ...prev, default_format: e.target.value }))}
                placeholder="png"
              />
            </div>
            <div className="grid gap-2">
              <Label>default_temperature</Label>
              <Input
                type="number"
                step="0.1"
                min={0}
                max={2}
                value={current.default_temperature ?? 0.7}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, default_temperature: parseFloat(e.target.value) || 0.7 }))
                }
              />
            </div>
            <div className="grid gap-2">
              <Label>default_image_size_tier (качество)</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={current.default_image_size_tier ?? '4K'}
                onChange={(e) => setForm((prev) => ({ ...prev, default_image_size_tier: e.target.value }))}
              >
                <option value="1K">1K</option>
                <option value="2K">2K</option>
                <option value="4K">4K (макс. качество)</option>
              </select>
              <p className="text-xs text-muted-foreground">Для «На релиз» рекомендуется 4K — все текущие модели поддерживают.</p>
            </div>
            <div className="grid gap-2">
              <Label>default_aspect_ratio</Label>
              <Input
                value={current.default_aspect_ratio ?? ''}
                onChange={(e) => setForm((prev) => ({ ...prev, default_aspect_ratio: e.target.value }))}
                placeholder="1:1"
              />
            </div>
          </div>
          <Button type="submit" disabled={masterMutation.isPending}>
            {masterMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Сохранить
          </Button>
        </CardContent>
      </Card>
    </form>
  )

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <FileText className="h-7 w-7" />
          Мастер промпт
        </h1>
        <p className="text-muted-foreground mt-1">
          Глобальные блоки системного промпта и настройки переноса личности. Используются в{' '}
          <Link to="/trends" className="underline text-primary">Трендах</Link>,{' '}
          <Link to="/prompt-playground" className="underline text-primary">Playground</Link>,{' '}
          <Link to="/copy-style" className="underline text-primary">Сделать такую же</Link>.
        </p>
      </div>

      {/* Глобальная конфигурация модели: два блока Превью / На релиз. Весь трафик кроме Playground идёт через выбранную модель и профиль «На релиз». */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-lg">Глобальная конфигурация модели</CardTitle>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Выбор глобальной модели из трёх вариантов; весь трафик (бот, тренды, Copy style), кроме Playground, идёт через выбранную модель и настройки блока «На релиз». Провайдер (Gemini / другой) задаётся в .env (IMAGE_PROVIDER).
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground rounded-md border border-border bg-muted/30 p-4">
            Настройки вотермарка и превью (формат, качество, макс. сторона для Take и Job) — в разделе{' '}
            <Link to="/preview-policy" className="font-medium underline text-primary">Политика превью</Link>.
          </p>
          <div className="grid md:grid-cols-2 gap-6 pt-2 border-t">
            {renderGlobalDefaultsForm(
              'preview',
              { ...masterData.preview, ...previewForm },
              setPreviewForm,
              handlePreviewSubmit,
              'Превью',
              'Настройки для профиля «Превью» (Playground и др.). Для качества как на проде задайте те же модель, размер и tier, что и в блоке «На релиз».'
            )}
            {renderGlobalDefaultsForm(
              'release',
              { ...masterData.release, ...releaseForm },
              setReleaseForm,
              handleReleaseSubmit,
              'На релиз',
              'Качество и параметры для всего трафика (бот, тренды, Copy style). Для максимального качества выставьте default_image_size_tier = 4K и нужный default_size.'
            )}
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="system" className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="system" className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            Системный промпт
          </TabsTrigger>
          <TabsTrigger value="global" className="flex items-center gap-2">
            <UserCog className="h-4 w-4" />
            Перенос (глобально)
          </TabsTrigger>
          <TabsTrigger value="trends" className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Перенос (для трендов)
          </TabsTrigger>
        </TabsList>

        <TabsContent value="system" className="space-y-4 mt-4">
          <p className="text-sm text-muted-foreground">
            Блоки [INPUT] и [TASK] (опционально). Дефолты модели задаются выше в блоках «Превью» и «На релиз». Для трендов [IDENTITY], [COMPOSITION], [AVOID] — вкладка «Перенос (для трендов)».
          </p>
          <form onSubmit={handleMasterSubmit}>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Блоки промпта</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-2">
                  <Label htmlFor="master-blocks">Блоки [INPUT] и [TASK] (опционально)</Label>
                  <Textarea
                    id="master-blocks"
                    rows={12}
                    className="font-mono text-sm"
                    value={masterBlocksText}
                    onChange={(e) => setMasterBlocksText(e.target.value)}
                    placeholder={'[INPUT]\n\n[TASK]'}
                  />
                </div>
                <Button type="submit" disabled={masterMutation.isPending}>
                  {masterMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  Сохранить
                </Button>
              </CardContent>
            </Card>
          </form>
        </TabsContent>

        <TabsContent value="global" className="mt-4">
          {renderTransferForm(
            'global',
            globalCurrent,
            setGlobalForm,
            handleGlobalSubmit,
            transferMutation.isPending
          )}
        </TabsContent>

        <TabsContent value="trends" className="mt-4">
          {renderTransferForm(
            'trends',
            trendsCurrent,
            setTrendsForm,
            handleTrendsSubmit,
            transferMutation.isPending
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
