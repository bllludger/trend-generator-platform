import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Save } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { faceIdService, type FaceIdAsset, type FaceIdSettings } from '@/services/api'

const STATUS_LABELS: Record<string, string> = {
  pending: 'pending',
  ready: 'ready',
  ready_fallback: 'ready_fallback',
  failed_multi_face: 'failed_multi_face',
  failed_error: 'failed_error',
}

export default function FaceIdPage() {
  const qc = useQueryClient()
  const [form, setForm] = useState<Partial<FaceIdSettings>>({})
  const [statusFilter, setStatusFilter] = useState<string>('')

  const { data: settings, isLoading: settingsLoading } = useQuery({
    queryKey: ['face-id-settings'],
    queryFn: () => faceIdService.getSettings(),
  })
  const { data: assets, isLoading: assetsLoading } = useQuery({
    queryKey: ['face-id-assets', statusFilter],
    queryFn: () => faceIdService.listAssets({ limit: 100, status: statusFilter || undefined }),
    refetchInterval: 15_000,
  })

  useEffect(() => {
    if (settings) setForm(settings)
  }, [settings])

  const saveMutation = useMutation({
    mutationFn: (payload: Partial<FaceIdSettings>) => faceIdService.updateSettings(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['face-id-settings'] })
      toast.success('Face ID настройки сохранены')
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail
        ?? (err as Error).message
        ?? 'Ошибка сохранения'
      toast.error(typeof msg === 'string' ? msg : 'Ошибка сохранения')
    },
  })

  const current = { ...settings, ...form } as FaceIdSettings
  const onNumber = (key: keyof FaceIdSettings, value: string) => {
    const normalized = value.replace(',', '.').trim()
    const num = normalized === '' ? NaN : Number(normalized)
    if (Number.isFinite(num)) {
      setForm((prev) => ({ ...prev, [key]: num }))
    }
  }

  const renderRow = (row: FaceIdAsset) => (
    <tr key={row.id} className="border-b border-border">
      <td className="p-2 text-xs">{new Date(row.created_at || '').toLocaleString('ru-RU')}</td>
      <td className="p-2 text-xs">{row.status}</td>
      <td className="p-2 text-xs">{row.faces_detected ?? '—'}</td>
      <td className="p-2 text-xs">{row.reason_code || '—'}</td>
      <td className="p-2 text-xs">{row.latency_ms ?? '—'}</td>
      <td className="p-2 text-xs">{row.flow}</td>
      <td className="p-2 text-xs break-all">{row.id}</td>
    </tr>
  )

  if (settingsLoading || !settings) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Face ID</h1>
        <p className="mt-1 text-muted-foreground">
          Центр предобработки входных фото для трендов и своей идеи.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Настройки</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label>enabled</Label>
              <select
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={current.enabled ? 'true' : 'false'}
                onChange={(e) => setForm((prev) => ({ ...prev, enabled: e.target.value === 'true' }))}
              >
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label>min_detection_confidence</Label>
              <Input value={String(current.min_detection_confidence ?? 0.6)} onChange={(e) => onNumber('min_detection_confidence', e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>model_selection</Label>
              <select
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={String(current.model_selection ?? 1)}
                onChange={(e) => setForm((prev) => ({ ...prev, model_selection: Number(e.target.value) as 0 | 1 }))}
              >
                <option value="0">0 (short range)</option>
                <option value="1">1 (full range)</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label>crop_pad_left</Label>
              <Input value={String(current.crop_pad_left ?? 0.35)} onChange={(e) => onNumber('crop_pad_left', e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>crop_pad_right</Label>
              <Input value={String(current.crop_pad_right ?? 0.35)} onChange={(e) => onNumber('crop_pad_right', e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>crop_pad_top</Label>
              <Input value={String(current.crop_pad_top ?? 0.7)} onChange={(e) => onNumber('crop_pad_top', e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>crop_pad_bottom</Label>
              <Input value={String(current.crop_pad_bottom ?? 0.35)} onChange={(e) => onNumber('crop_pad_bottom', e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>callback_timeout_seconds</Label>
              <Input value={String(current.callback_timeout_seconds ?? 2)} onChange={(e) => onNumber('callback_timeout_seconds', e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>callback_max_retries</Label>
              <Input value={String(current.callback_max_retries ?? 3)} onChange={(e) => onNumber('callback_max_retries', e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>callback_backoff_seconds</Label>
              <Input value={String(current.callback_backoff_seconds ?? 1)} onChange={(e) => onNumber('callback_backoff_seconds', e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>max_faces_allowed</Label>
              <Input value={String(current.max_faces_allowed ?? 1)} onChange={(e) => onNumber('max_faces_allowed', e.target.value)} />
            </div>
          </div>
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              updated_at: {settings.updated_at ? new Date(settings.updated_at).toLocaleString('ru-RU') : '—'}
            </p>
            <Button onClick={() => saveMutation.mutate(form)} disabled={saveMutation.isPending}>
              {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              <span className="ml-2">Сохранить</span>
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Последние face_assets</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-3 text-sm">
            <span>pending takes: {assets?.pending_takes ?? 0}</span>
            <select
              className="h-9 rounded-md border border-input bg-background px-2"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="">all</option>
              {Object.keys(STATUS_LABELS).map((s) => (
                <option key={s} value={s}>{STATUS_LABELS[s]}</option>
              ))}
            </select>
          </div>
          {assetsLoading ? (
            <div className="py-6 text-sm text-muted-foreground">Загрузка...</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-border text-xs text-muted-foreground">
                    <th className="p-2">created_at</th>
                    <th className="p-2">status</th>
                    <th className="p-2">faces</th>
                    <th className="p-2">reason</th>
                    <th className="p-2">latency_ms</th>
                    <th className="p-2">flow</th>
                    <th className="p-2">asset_id</th>
                  </tr>
                </thead>
                <tbody>
                  {(assets?.items || []).map(renderRow)}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
