import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  masterPromptService,
  transferPolicyService,
  type MasterPromptSettings,
  type TransferPolicySettings,
} from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Loader2, Save, FileText, UserCog, TrendingUp } from 'lucide-react'
import { useState, useEffect } from 'react'
import { toast } from 'sonner'

const MASTER_BLOCK_MARKERS = ['[INPUT]', '[TASK]', '[IDENTITY TRANSFER]', '[SAFETY]'] as const

function masterBlocksToFullText(s: Partial<MasterPromptSettings>): string {
  const parts = [
    '[INPUT]',
    (s.prompt_input ?? '').trim(),
    '[TASK]',
    (s.prompt_task ?? '').trim(),
    '[IDENTITY TRANSFER]',
    (s.prompt_identity_transfer ?? '').trim(),
    '[SAFETY]',
    (s.safety_constraints ?? '').trim(),
  ]
  return parts.join('\n\n')
}

function parseMasterBlocksFullText(text: string): {
  prompt_input: string
  prompt_task: string
  prompt_identity_transfer: string
  safety_constraints: string
} {
  const result = {
    prompt_input: '',
    prompt_task: '',
    prompt_identity_transfer: '',
    safety_constraints: '',
  }
  const keys: (keyof typeof result)[] = ['prompt_input', 'prompt_task', 'prompt_identity_transfer', 'safety_constraints']
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
  const [globalForm, setGlobalForm] = useState<Partial<TransferPolicySettings>>({})
  const [trendsForm, setTrendsForm] = useState<Partial<TransferPolicySettings>>({})

  useEffect(() => {
    if (masterSettings) {
      setMasterForm(masterSettings)
      setMasterBlocksText(masterBlocksToFullText(masterSettings))
    }
  }, [masterSettings])
  useEffect(() => {
    if (transferSettings?.global) setGlobalForm(transferSettings.global)
  }, [transferSettings?.global])
  useEffect(() => {
    if (transferSettings?.trends) setTrendsForm(transferSettings.trends)
  }, [transferSettings?.trends])

  const masterMutation = useMutation({
    mutationFn: (payload: Partial<MasterPromptSettings>) => masterPromptService.updateSettings(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['master-prompt-settings'] })
      toast.success('Системный промпт сохранён')
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
      ...masterSettings,
      ...masterForm,
      ...parsed,
      prompt_input_enabled: true,
      prompt_task_enabled: true,
      prompt_identity_transfer_enabled: true,
      safety_constraints_enabled: true,
    })
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
  if (isLoading || !masterSettings || !transferSettings) {
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

  const masterCurrent = { ...masterSettings, ...masterForm }
  const globalCurrent = { ...transferSettings.global, ...globalForm }
  const trendsCurrent = { ...transferSettings.trends, ...trendsForm }

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
            Блоки [INPUT], [TASK], [IDENTITY TRANSFER], [SAFETY] (все опциональны) и дефолты модели. Для трендов [IDENTITY], [COMPOSITION], [AVOID] берутся из вкладки «Перенос (для трендов)».
          </p>
          <form onSubmit={handleMasterSubmit}>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Блоки и дефолты</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-2">
                  <Label htmlFor="master-blocks">Блоки [INPUT], [TASK], [IDENTITY TRANSFER], [SAFETY] (опционально)</Label>
                  <Textarea
                    id="master-blocks"
                    rows={16}
                    className="font-mono text-sm"
                    value={masterBlocksText}
                    onChange={(e) => setMasterBlocksText(e.target.value)}
                    placeholder={'[INPUT]\n\n[TASK]\n\n[IDENTITY TRANSFER]\n\n[SAFETY]'}
                  />
                </div>
                <div className="grid grid-cols-2 gap-4 pt-2 border-t">
                  <div className="grid gap-2">
                    <Label>default_model</Label>
                    <select
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      value={masterCurrent.default_model ?? 'gemini-2.5-flash-image'}
                      onChange={(e) => setMasterForm((prev) => ({ ...prev, default_model: e.target.value }))}
                    >
                      <option value="gemini-2.5-flash-image">gemini-2.5-flash-image</option>
                      <option value="gemini-3-pro-image-preview">gemini-3-pro-image-preview</option>
                      <option value="gemini-3.1-flash-image-preview">gemini-3.1-flash-image-preview (Nano Banana 2)</option>
                    </select>
                  </div>
                  <div className="grid gap-2">
                    <Label>default_size</Label>
                    <Input
                      value={masterCurrent.default_size ?? ''}
                      onChange={(e) => setMasterForm((prev) => ({ ...prev, default_size: e.target.value }))}
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label>default_format</Label>
                    <Input
                      value={masterCurrent.default_format ?? ''}
                      onChange={(e) => setMasterForm((prev) => ({ ...prev, default_format: e.target.value }))}
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label>default_temperature</Label>
                    <Input
                      type="number"
                      step="0.1"
                      min={0}
                      max={2}
                      value={masterCurrent.default_temperature ?? 0.7}
                      onChange={(e) =>
                        setMasterForm((prev) => ({ ...prev, default_temperature: parseFloat(e.target.value) || 0.7 }))
                      }
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label>default_image_size_tier</Label>
                    <Input
                      value={masterCurrent.default_image_size_tier ?? ''}
                      onChange={(e) =>
                        setMasterForm((prev) => ({ ...prev, default_image_size_tier: e.target.value }))
                      }
                      placeholder="1K"
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label>default_aspect_ratio</Label>
                    <Input
                      value={masterCurrent.default_aspect_ratio ?? ''}
                      onChange={(e) =>
                        setMasterForm((prev) => ({ ...prev, default_aspect_ratio: e.target.value }))
                      }
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
