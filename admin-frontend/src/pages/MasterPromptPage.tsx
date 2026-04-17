import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  masterPromptService,
  transferPolicyService,
  type MasterPromptPayloadPreviewResponse,
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
import { Loader2, Save, FileText, UserCog, TrendingUp, Zap, FileJson, Copy } from 'lucide-react'
import { useState, useEffect, useMemo } from 'react'
import { toast } from 'sonner'

const ASPECT_RATIO_OPTIONS = [
  '1:1', '3:2', '2:3', '3:4', '4:3', '4:5', '5:4',
  '9:16', '16:9', '21:9', '1:4', '4:1', '1:8', '8:1',
] as const
const MODEL_OPTIONS = [
  { value: 'gemini-2.5-flash-image', label: 'gemini-2.5-flash-image' },
  { value: 'gemini-3-pro-image-preview', label: 'gemini-3-pro-image-preview (Nano Banana Pro)' },
  { value: 'gemini-3.1-flash-image-preview', label: 'gemini-3.1-flash-image-preview (NeoBanana 2)' },
] as const

type ProfileKey = 'preview' | 'release'
const PROFILE_META: Record<ProfileKey, { title: string; description: string }> = {
  preview: {
    title: 'Preview',
    description: 'Профиль для предпросмотров и безопасного тюнинга.',
  },
  release: {
    title: 'Release',
    description: 'Профиль production flow, который реально используется в боте.',
  },
}

/** Старые БД: prompt_task сливаем в одно поле для UI и дальше храним только prompt_input. */
function coalesceMasterPromptForState(p: MasterPromptSettings): MasterPromptSettings {
  const input = (p.prompt_input ?? '').trim()
  const task = (p.prompt_task ?? '').trim()
  const combined = task ? (input ? `${input}\n\n${task}` : task) : (p.prompt_input ?? '')
  return { ...p, prompt_input: combined, prompt_task: '' }
}

function legacySizeFromAspectRatio(aspectRatio: string | undefined): string {
  const raw = (aspectRatio || '3:4').trim()
  if (!raw.includes(':')) return '768x1024'
  const [wRaw, hRaw] = raw.split(':', 2)
  const w = Number(wRaw)
  const h = Number(hRaw)
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return '768x1024'
  if (w >= h) {
    return `${Math.max(1, Math.round((w / h) * 1024))}x1024`
  }
  return `1024x${Math.max(1, Math.round((h / w) * 1024))}`
}

type PreviewState = {
  loading: boolean
  data: MasterPromptPayloadPreviewResponse | null
  error: string | null
}

const EMPTY_PREVIEW_STATE: PreviewState = { loading: false, data: null, error: null }

const TREND_TAKE_SYNC_FIELDS = [
  'default_temperature_a',
  'default_temperature_b',
  'default_temperature_c',
  'default_top_p_a',
  'default_top_p_b',
  'default_top_p_c',
] as const

function syncPreviewTrendTakeOverrides(
  preview: Partial<MasterPromptSettings>,
  release: Partial<MasterPromptSettings>
): Partial<MasterPromptSettings> {
  const synced = { ...preview }
  for (const key of TREND_TAKE_SYNC_FIELDS) {
    synced[key] = release[key] ?? null
  }
  return synced
}

function parseNullableNumber(raw: string): number | null {
  const v = raw.trim()
  if (!v) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
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

  const [previewForm, setPreviewForm] = useState<Partial<MasterPromptSettings>>({})
  const [releaseForm, setReleaseForm] = useState<Partial<MasterPromptSettings>>({})
  const [activeProfile, setActiveProfile] = useState<ProfileKey>('release')
  const [globalForm, setGlobalForm] = useState<Partial<TransferPolicySettings>>({})
  const [trendsForm, setTrendsForm] = useState<Partial<TransferPolicySettings>>({})
  const [payloadPreview, setPayloadPreview] = useState<Record<ProfileKey, PreviewState>>({
    preview: EMPTY_PREVIEW_STATE,
    release: EMPTY_PREVIEW_STATE,
  })

  useEffect(() => {
    if (masterSettings?.preview) {
      setPreviewForm(coalesceMasterPromptForState(masterSettings.preview))
    }
  }, [masterSettings?.preview])
  useEffect(() => {
    if (masterSettings?.release) setReleaseForm(coalesceMasterPromptForState(masterSettings.release))
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

  const masterData = masterSettings as MasterPromptSettingsResponse | undefined

  const draftPreview = useMemo<Partial<MasterPromptSettings>>(() => {
    const merged = {
      ...(masterData?.preview ?? {}),
      ...previewForm,
      prompt_input_enabled: true,
      prompt_task_enabled: true,
      prompt_identity_transfer_enabled: false,
      safety_constraints_enabled: false,
    }
    return {
      ...merged,
      default_size: legacySizeFromAspectRatio(merged.default_aspect_ratio),
    }
  }, [masterData?.preview, previewForm])

  const draftRelease = useMemo<Partial<MasterPromptSettings>>(() => {
    const merged = { ...(masterData?.release ?? {}), ...releaseForm, default_candidate_count: 1 }
    return { ...merged, default_size: legacySizeFromAspectRatio(merged.default_aspect_ratio) }
  }, [masterData?.release, releaseForm])

  const syncedDraftPreview = useMemo<Partial<MasterPromptSettings>>(
    () => syncPreviewTrendTakeOverrides(draftPreview, draftRelease),
    [draftPreview, draftRelease]
  )

  const normalizeProfileForCompare = (profile: ProfileKey, value: Partial<MasterPromptSettings>) => {
    const normalized = {
      ...value,
      default_size: legacySizeFromAspectRatio(value.default_aspect_ratio),
    }
    if (profile === 'release') {
      return { ...normalized, default_candidate_count: 1, updated_at: undefined }
    }
    return { ...normalized, updated_at: undefined }
  }

  const profileDirty = useMemo<Record<ProfileKey, boolean>>(() => {
    if (!masterData?.preview || !masterData?.release) return { preview: false, release: false }
    const baselinePreview = normalizeProfileForCompare(
      'preview',
      syncPreviewTrendTakeOverrides(
        coalesceMasterPromptForState(masterData.preview),
        coalesceMasterPromptForState(masterData.release),
      ),
    )
    const baselineRelease = normalizeProfileForCompare('release', coalesceMasterPromptForState(masterData.release))
    const currentPreview = normalizeProfileForCompare('preview', syncedDraftPreview)
    const currentRelease = normalizeProfileForCompare('release', draftRelease)
    return {
      preview: JSON.stringify(currentPreview) !== JSON.stringify(baselinePreview),
      release: JSON.stringify(currentRelease) !== JSON.stringify(baselineRelease),
    }
  }, [masterData?.preview, masterData?.release, syncedDraftPreview, draftRelease])

  useEffect(() => {
    if (!masterData?.preview || !masterData?.release) return
    let active = true
    const abort = new AbortController()
    const timer = window.setTimeout(async () => {
      const loadProfilePreview = async (profile: ProfileKey) => {
        setPayloadPreview((prev) => ({ ...prev, [profile]: { ...prev[profile], loading: true, error: null } }))
        try {
          const data = await masterPromptService.previewPayload({
            profile,
            preview: syncedDraftPreview,
            release: draftRelease,
          }, abort.signal)
          if (!active) return
          setPayloadPreview((prev) => ({ ...prev, [profile]: { loading: false, data, error: null } }))
        } catch (err) {
          const canceled = (err as { code?: string; name?: string })?.code === 'ERR_CANCELED' || (err as { name?: string })?.name === 'CanceledError'
          if (canceled) return
          if (!active) return
          const msg = (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail ?? (err as Error)?.message ?? 'Не удалось получить preview payload'
          setPayloadPreview((prev) => ({ ...prev, [profile]: { loading: false, data: null, error: msg } }))
        }
      }
      await Promise.all([loadProfilePreview('preview'), loadProfilePreview('release')])
    }, 650)
    return () => {
      active = false
      abort.abort()
      window.clearTimeout(timer)
    }
  }, [syncedDraftPreview, draftRelease, masterData?.preview, masterData?.release])

  const handleProfileSubmit = (profile: ProfileKey, data: Partial<MasterPromptSettings>) => (e: React.FormEvent) => {
    e.preventDefault()
    masterMutation.mutate({ [profile]: data })
  }

  const handleGlobalSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    transferMutation.mutate({ global: { ...transferSettings?.global, ...globalForm } })
  }
  const handleTrendsSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    transferMutation.mutate({ trends: { ...transferSettings?.trends, ...trendsForm } })
  }

  const updateThinkingConfig = (
    profile: ProfileKey,
    current: Partial<MasterPromptSettings>,
    patch: Partial<NonNullable<MasterPromptSettings['default_thinking_config']>>
  ) => {
    const base = current.default_thinking_config || {}
    const next = { ...base, ...patch }
    const cleaned = {
      ...(next.thinking_level ? { thinking_level: next.thinking_level } : {}),
      ...(Number.isFinite(Number(next.thinking_budget)) ? { thinking_budget: Math.max(0, Math.trunc(Number(next.thinking_budget))) } : {}),
      ...(typeof next.include_thoughts === 'boolean' ? { include_thoughts: next.include_thoughts } : {}),
    }
    const value = Object.keys(cleaned).length > 0 ? cleaned : null
    if (profile === 'preview') setPreviewForm((prev) => ({ ...prev, default_thinking_config: value }))
    else setReleaseForm((prev) => ({ ...prev, default_thinking_config: value }))
  }

  const copyPreviewJson = async (profile: ProfileKey) => {
    const data = payloadPreview[profile].data?.sent_request
    if (!data) return
    try {
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2))
      toast.success('JSON скопирован')
    } catch {
      toast.error('Не удалось скопировать JSON')
    }
  }

  const isLoading = masterLoading || transferLoading
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

  const renderDiagnostics = (profile: ProfileKey) => {
    const items = payloadPreview[profile].data?.diagnostics || []
    if (!items.length) return <p className="text-xs text-muted-foreground">Diagnostics: no warnings.</p>
    return (
      <div className="space-y-2">
        {items.map((d, idx) => (
          <div key={`${profile}_diag_${idx}`} className="rounded-md border bg-muted/30 px-3 py-2 text-xs">
            <div className="font-medium">{d.status.toUpperCase()} · {d.field}</div>
            <div className="text-muted-foreground">{d.reason}</div>
          </div>
        ))}
      </div>
    )
  }

  const renderProfileForm = (
    profile: ProfileKey,
    current: Partial<MasterPromptSettings>,
    setForm: React.Dispatch<React.SetStateAction<Partial<MasterPromptSettings>>>,
    title: string,
    description: string,
    isDirty: boolean,
    onReset: () => void
  ) => {
    const submitPayload =
      profile === 'release'
        ? { ...current, default_candidate_count: 1, prompt_task: '' }
        : { ...current, prompt_task: '' }
    const thinkingLevel = current.default_thinking_config?.thinking_level ?? ''
    const thinkingBudget = current.default_thinking_config?.thinking_budget
    const derivedLegacySize = legacySizeFromAspectRatio(current.default_aspect_ratio)

    return (
      <form onSubmit={handleProfileSubmit(profile, submitPayload)}>
        <Card className="h-full">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base">{title}</CardTitle>
                <p className="text-sm text-muted-foreground">{description}</p>
              </div>
              <div className={`rounded-full border px-3 py-1 text-xs ${isDirty ? 'border-orange-300 bg-orange-50 text-orange-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
                {isDirty ? 'Unsaved changes' : 'Saved'}
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-3 rounded-lg border p-4">
              <p className="text-sm font-medium">Мастер-промпт</p>
              <p className="text-xs text-muted-foreground">
                Один текст без разбиения на блоки: к нему в боте добавляется промпт тренда. Production — профиль{' '}
                <span className="font-medium text-foreground">Release</span>.
              </p>
              <div className="grid gap-2">
                <Label htmlFor={`${profile}-master-prompt`}>Текст</Label>
                <Textarea
                  id={`${profile}-master-prompt`}
                  rows={14}
                  className="font-mono text-sm"
                  value={current.prompt_input ?? ''}
                  onChange={(e) => setForm((prev) => ({ ...prev, prompt_input: e.target.value }))}
                  placeholder=""
                />
              </div>
            </div>
            <div className="space-y-3 rounded-lg border p-4">
              <p className="text-sm font-medium">Model & Framing</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-2">
                  <Label>default_model</Label>
                  <select
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={current.default_model ?? 'gemini-2.5-flash-image'}
                    onChange={(e) => setForm((prev) => ({ ...prev, default_model: e.target.value }))}
                  >
                    {MODEL_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </div>
                <div className="grid gap-2">
                  <Label>default_aspect_ratio</Label>
                  <select
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={current.default_aspect_ratio ?? '3:4'}
                    onChange={(e) => setForm((prev) => ({ ...prev, default_aspect_ratio: e.target.value }))}
                  >
                    {ASPECT_RATIO_OPTIONS.map((ratio) => (
                      <option key={`${profile}_ratio_${ratio}`} value={ratio}>{ratio}</option>
                    ))}
                  </select>
                </div>
                <div className="grid gap-2">
                  <Label>default_size (compat)</Label>
                  <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm font-mono">
                    {derivedLegacySize}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Автоматически вычисляется из `default_aspect_ratio` и не управляет Gemini напрямую.
                  </p>
                </div>
                <div className="grid gap-2">
                  <Label>default_format</Label>
                  <select
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={current.default_format ?? 'png'}
                    onChange={(e) => setForm((prev) => ({ ...prev, default_format: e.target.value }))}
                  >
                    <option value="png">png</option>
                    <option value="jpeg">jpeg</option>
                    <option value="webp">webp</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="space-y-3 rounded-lg border p-4">
              <p className="text-sm font-medium">Quality</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-2">
                  <Label>default_temperature (0..2)</Label>
                  <Input
                    type="number"
                    step="0.1"
                    min={0}
                    max={2}
                    value={current.default_temperature ?? 0.7}
                    onChange={(e) => setForm((prev) => ({ ...prev, default_temperature: parseFloat(e.target.value) || 0 }))}
                  />
                </div>
                {profile === 'release' ? (
                  <>
                    <div className="grid gap-2">
                      <Label>temperature A (trend take)</Label>
                      <Input
                        type="number"
                        step="0.1"
                        min={0}
                        max={2}
                        value={current.default_temperature_a ?? ''}
                        onChange={(e) => setForm((prev) => ({ ...prev, default_temperature_a: parseNullableNumber(e.target.value) }))}
                        placeholder="inherit default_temperature"
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label>temperature B (trend take)</Label>
                      <Input
                        type="number"
                        step="0.1"
                        min={0}
                        max={2}
                        value={current.default_temperature_b ?? ''}
                        onChange={(e) => setForm((prev) => ({ ...prev, default_temperature_b: parseNullableNumber(e.target.value) }))}
                        placeholder="inherit default_temperature"
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label>temperature C (trend take)</Label>
                      <Input
                        type="number"
                        step="0.1"
                        min={0}
                        max={2}
                        value={current.default_temperature_c ?? ''}
                        onChange={(e) => setForm((prev) => ({ ...prev, default_temperature_c: parseNullableNumber(e.target.value) }))}
                        placeholder="inherit default_temperature"
                      />
                    </div>
                  </>
                ) : null}
                <div className="grid gap-2">
                  <Label>default_image_size_tier</Label>
                  <select
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={current.default_image_size_tier ?? '1K'}
                    onChange={(e) => setForm((prev) => ({ ...prev, default_image_size_tier: e.target.value }))}
                  >
                    <option value="256">256</option>
                    <option value="512">512</option>
                    <option value="1K">1K</option>
                    <option value="2K">2K</option>
                    <option value="4K">4K</option>
                  </select>
                </div>
              </div>
              {profile === 'preview' ? (
                <p className="text-xs text-muted-foreground">
                  temperature A/B/C для trend take синхронизируются из профиля Release.
                </p>
              ) : null}
            </div>

            <div className="space-y-3 rounded-lg border p-4">
              <p className="text-sm font-medium">Sampling & Reproducibility</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-2">
                  <Label>default_top_p (0..1)</Label>
                  <Input
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={current.default_top_p ?? ''}
                    onChange={(e) => setForm((prev) => ({ ...prev, default_top_p: parseNullableNumber(e.target.value) }))}
                    placeholder="0.1"
                  />
                </div>
                {profile === 'release' ? (
                  <>
                    <div className="grid gap-2">
                      <Label>top_p A (trend take)</Label>
                      <Input
                        type="number"
                        step="0.01"
                        min={0}
                        max={1}
                        value={current.default_top_p_a ?? ''}
                        onChange={(e) => setForm((prev) => ({ ...prev, default_top_p_a: parseNullableNumber(e.target.value) }))}
                        placeholder="inherit default_top_p"
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label>top_p B (trend take)</Label>
                      <Input
                        type="number"
                        step="0.01"
                        min={0}
                        max={1}
                        value={current.default_top_p_b ?? ''}
                        onChange={(e) => setForm((prev) => ({ ...prev, default_top_p_b: parseNullableNumber(e.target.value) }))}
                        placeholder="inherit default_top_p"
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label>top_p C (trend take)</Label>
                      <Input
                        type="number"
                        step="0.01"
                        min={0}
                        max={1}
                        value={current.default_top_p_c ?? ''}
                        onChange={(e) => setForm((prev) => ({ ...prev, default_top_p_c: parseNullableNumber(e.target.value) }))}
                        placeholder="inherit default_top_p"
                      />
                    </div>
                  </>
                ) : null}
                <div className="grid gap-2">
                  <Label>default_seed</Label>
                  <Input
                    type="number"
                    step="1"
                    value={current.default_seed ?? ''}
                    onChange={(e) => {
                      const v = e.target.value.trim()
                      setForm((prev) => ({ ...prev, default_seed: v === '' ? null : parseInt(v, 10) }))
                    }}
                    placeholder="42"
                  />
                </div>
                <div className="grid gap-2 col-span-2">
                  <Label>default_candidate_count</Label>
                  {profile === 'release' ? (
                    <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
                      1 (fixed in production flow)
                    </div>
                  ) : (
                    <select
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      value={current.default_candidate_count ?? 1}
                      onChange={(e) => setForm((prev) => ({ ...prev, default_candidate_count: parseInt(e.target.value, 10) }))}
                    >
                      <option value={1}>1</option>
                      <option value={2}>2</option>
                      <option value={3}>3</option>
                      <option value={4}>4</option>
                    </select>
                  )}
                  <p className="text-xs text-muted-foreground">Даже если значение выше, production-flow отправляет `candidateCount=1`.</p>
                </div>
              </div>
              {profile === 'preview' ? (
                <p className="text-xs text-muted-foreground">
                  top_p A/B/C для trend take синхронизируются из профиля Release.
                </p>
              ) : null}
            </div>

            <div className="space-y-3 rounded-lg border p-4">
              <p className="text-sm font-medium">Gemini Advanced</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-2">
                  <Label>default_media_resolution</Label>
                  <select
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={current.default_media_resolution ?? ''}
                    onChange={(e) => setForm((prev) => ({ ...prev, default_media_resolution: (e.target.value || null) as MasterPromptSettings['default_media_resolution'] }))}
                  >
                    <option value="">(none)</option>
                    <option value="LOW">LOW</option>
                    <option value="MEDIUM">MEDIUM</option>
                    <option value="HIGH">HIGH</option>
                  </select>
                </div>
                <div className="grid gap-2">
                  <Label>thinking_level</Label>
                  <select
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={thinkingLevel}
                    onChange={(e) => {
                      const val = e.target.value as NonNullable<MasterPromptSettings['default_thinking_config']>['thinking_level']
                      if (!val) {
                        updateThinkingConfig(profile, current, { thinking_level: undefined })
                        return
                      }
                      updateThinkingConfig(profile, current, { thinking_level: val, thinking_budget: undefined })
                    }}
                  >
                    <option value="">(none)</option>
                    <option value="MINIMAL">MINIMAL</option>
                    <option value="LOW">LOW</option>
                    <option value="MEDIUM">MEDIUM</option>
                    <option value="HIGH">HIGH</option>
                  </select>
                </div>
                <div className="grid gap-2">
                  <Label>thinking_budget</Label>
                  <Input
                    type="number"
                    min={0}
                    step={1}
                    disabled={Boolean(thinkingLevel)}
                    value={thinkingBudget ?? ''}
                    onChange={(e) => {
                      const val = e.target.value.trim()
                      if (!val) {
                        updateThinkingConfig(profile, current, { thinking_budget: undefined })
                        return
                      }
                      updateThinkingConfig(profile, current, { thinking_budget: Math.max(0, Math.trunc(Number(val))) })
                    }}
                    placeholder="64"
                  />
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-blue-200 bg-blue-50/70 p-4 text-sm text-blue-900">
              Приоритет параметров в production: `trend prompt_*` → `master release defaults` → `provider defaults`.
              Для Release поле `candidateCount` всегда отправляется как `1`.
            </div>

            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" onClick={onReset} disabled={!isDirty || masterMutation.isPending}>
                Сбросить изменения
              </Button>
              <Button type="submit" disabled={masterMutation.isPending || !isDirty}>
                {masterMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Сохранить {title.toLowerCase()}
              </Button>
            </div>
          </CardContent>
        </Card>
      </form>
    )
  }

  const globalCurrent = { ...transferSettings.global, ...globalForm }
  const trendsCurrent = { ...transferSettings.trends, ...trendsForm }
  const activeDraft = activeProfile === 'preview' ? syncedDraftPreview : draftRelease
  const activePreview = payloadPreview[activeProfile]
  const activeMeta = PROFILE_META[activeProfile]
  const resetActiveProfile = () => {
    if (activeProfile === 'preview') setPreviewForm(coalesceMasterPromptForState(masterData.preview))
    else setReleaseForm(coalesceMasterPromptForState(masterData.release))
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <FileText className="h-7 w-7" />
          Мастер промпт
        </h1>
        <p className="text-muted-foreground mt-1">
          Единая точка контроля production Gemini-запроса для{' '}
          <Link to="/trends" className="underline text-primary">трендов</Link>,{' '}
          <Link to="/prompt-playground" className="underline text-primary">Playground</Link> и{' '}
          <Link to="/copy-style" className="underline text-primary">«Сделать такую же»</Link>.
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-lg">Gemini Defaults</CardTitle>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Настройки ниже формируют `generationConfig`, который уходит в Gemini. Для профиля Release `candidateCount` жёстко фиксирован в `1`.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 rounded-lg border p-2">
            <Button
              type="button"
              variant={activeProfile === 'preview' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setActiveProfile('preview')}
            >
              Preview
            </Button>
            <Button
              type="button"
              variant={activeProfile === 'release' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setActiveProfile('release')}
            >
              Release
            </Button>
            <div className="ml-auto text-xs text-muted-foreground">
              Active profile: <span className="font-medium text-foreground">{activeMeta.title}</span>
            </div>
          </div>
          <p className="text-sm text-muted-foreground rounded-md border border-border bg-muted/30 p-4">
            Настройки вотермарка и формата превью остаются в разделе{' '}
            <Link to="/preview-policy" className="font-medium underline text-primary">Политика превью</Link>.
          </p>
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px] items-start">
            {activeProfile === 'preview'
              ? renderProfileForm(
                  'preview',
                  syncedDraftPreview,
                  setPreviewForm,
                  PROFILE_META.preview.title,
                  PROFILE_META.preview.description,
                  profileDirty.preview,
                  resetActiveProfile
                )
              : renderProfileForm(
                  'release',
                  draftRelease,
                  setReleaseForm,
                  PROFILE_META.release.title,
                  PROFILE_META.release.description,
                  profileDirty.release,
                  resetActiveProfile
                )}

            <Card className="xl:sticky xl:top-4">
              <CardHeader>
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-base flex items-center gap-2">
                    <FileJson className="h-4 w-4" />
                    Final Gemini Request
                  </CardTitle>
                  <Button type="button" variant="outline" size="sm" onClick={() => copyPreviewJson(activeProfile)} disabled={!activePreview.data?.sent_request}>
                    <Copy className="h-4 w-4" />
                    Copy JSON
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Инспектор показывает sanitized JSON и диагностику для профиля <span className="font-medium text-foreground">{activeMeta.title}</span>.
                </p>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="rounded-md border bg-muted/30 p-3 text-xs">
                  <div className="font-medium mb-1">Effective Settings Snapshot</div>
                  <div>model: <span className="font-mono">{activeDraft.default_model || 'gemini-2.5-flash-image'}</span></div>
                <div>aspect_ratio: <span className="font-mono">{activeDraft.default_aspect_ratio || '3:4'}</span></div>
                <div>top_p: <span className="font-mono">{activeDraft.default_top_p ?? 'null'}</span></div>
                <div>seed: <span className="font-mono">{activeDraft.default_seed ?? 'null'}</span></div>
                  {activeProfile === 'release' ? (
                    <div className="mt-2 border-t pt-2">
                      <div>trend-take temperature A/B/C: <span className="font-mono">{`${activeDraft.default_temperature_a ?? 'base'} / ${activeDraft.default_temperature_b ?? 'base'} / ${activeDraft.default_temperature_c ?? 'base'}`}</span></div>
                      <div>trend-take top_p A/B/C: <span className="font-mono">{`${activeDraft.default_top_p_a ?? 'base'} / ${activeDraft.default_top_p_b ?? 'base'} / ${activeDraft.default_top_p_c ?? 'base'}`}</span></div>
                    </div>
                  ) : null}
                </div>
                {activePreview.loading ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Обновляю payload preview...
                  </div>
                ) : null}
                {activePreview.error ? (
                  <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                    {activePreview.error}
                  </div>
                ) : null}
                {renderDiagnostics(activeProfile)}
                <pre className="max-h-[520px] overflow-auto rounded-md border bg-muted/30 p-3 text-xs leading-5">
                  {JSON.stringify(activePreview.data?.sent_request ?? {}, null, 2)}
                </pre>
              </CardContent>
            </Card>
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="global" className="w-full">
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="global" className="flex items-center gap-2">
            <UserCog className="h-4 w-4" />
            Перенос (глобально)
          </TabsTrigger>
          <TabsTrigger value="trends" className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Перенос (для трендов)
          </TabsTrigger>
        </TabsList>

        <TabsContent value="global" className="mt-4">
          {renderTransferForm('global', globalCurrent, setGlobalForm, handleGlobalSubmit, transferMutation.isPending)}
        </TabsContent>

        <TabsContent value="trends" className="mt-4">
          {renderTransferForm('trends', trendsCurrent, setTrendsForm, handleTrendsSubmit, transferMutation.isPending)}
        </TabsContent>
      </Tabs>
    </div>
  )
}
