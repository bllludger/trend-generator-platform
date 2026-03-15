import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { previewPolicyService, type PreviewPolicySettings } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Loader2, Save, ImageIcon } from 'lucide-react'
import { useState, useEffect } from 'react'
import { toast } from 'sonner'

export function PreviewPolicyPage() {
  const queryClient = useQueryClient()
  const { data: settings, isLoading } = useQuery({
    queryKey: ['preview-policy'],
    queryFn: () => previewPolicyService.getSettings(),
  })

  const [form, setForm] = useState<{
    preview_format: 'webp' | 'jpeg'
    preview_quality: number
    take_preview_max_dim: number
    job_preview_max_dim: number
    watermark_text: string
    watermark_opacity: number
    watermark_tile_spacing: number
    watermark_use_contrast: boolean
  }>({
    preview_format: 'webp',
    preview_quality: 85,
    take_preview_max_dim: 800,
    job_preview_max_dim: 800,
    watermark_text: '',
    watermark_opacity: 60,
    watermark_tile_spacing: 200,
    watermark_use_contrast: true,
  })

  useEffect(() => {
    if (settings == null) return
    setForm((prev) => ({
      ...prev,
      preview_format: (settings.preview_format === 'jpeg' ? 'jpeg' : 'webp') as 'webp' | 'jpeg',
      preview_quality: settings.preview_quality ?? 85,
      take_preview_max_dim: settings.take_preview_max_dim ?? 800,
      job_preview_max_dim: settings.job_preview_max_dim ?? 800,
      watermark_text: settings.watermark_text ?? '',
      watermark_opacity: settings.watermark_opacity ?? 60,
      watermark_tile_spacing: settings.watermark_tile_spacing ?? 200,
      watermark_use_contrast: settings.watermark_use_contrast ?? true,
    }))
  }, [settings])

  const mutation = useMutation({
    mutationFn: (payload: Partial<PreviewPolicySettings>) => previewPolicyService.updateSettings(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['preview-policy'] })
      toast.success('Политика превью сохранена')
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail ?? (err as Error).message
      toast.error(typeof msg === 'string' ? msg : 'Ошибка сохранения')
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    mutation.mutate({
      preview_format: form.preview_format,
      preview_quality: form.preview_quality,
      take_preview_max_dim: form.take_preview_max_dim,
      job_preview_max_dim: form.job_preview_max_dim,
      watermark_text: form.watermark_text.trim() || null,
      watermark_opacity: form.watermark_opacity,
      watermark_tile_spacing: form.watermark_tile_spacing,
      watermark_use_contrast: form.watermark_use_contrast,
    })
  }

  if (isLoading || !settings) {
    return (
      <div className="p-6 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-2">
        <ImageIcon className="h-8 w-8" />
        <h1 className="text-2xl font-semibold">Политика превью</h1>
      </div>
      <p className="text-sm text-muted-foreground">
        Original и preview — разные сущности. Original хранится отдельно; пользователь до оплаты видит только preview по правилам ниже.
      </p>

      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Общие правила превью</CardTitle>
            <CardDescription>Формат и качество сжатия для всех превью (Take и Job)</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label htmlFor="preview_format">Формат превью</Label>
                <Select
                  value={form.preview_format}
                  onValueChange={(v: 'webp' | 'jpeg') => setForm((p) => ({ ...p, preview_format: v }))}
                >
                  <SelectTrigger id="preview_format">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="webp">WebP</SelectItem>
                    <SelectItem value="jpeg">JPEG</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="preview_quality">Качество (1–100)</Label>
                <Input
                  id="preview_quality"
                  type="number"
                  min={1}
                  max={100}
                  value={form.preview_quality}
                  onChange={(e) => setForm((p) => ({ ...p, preview_quality: Number(e.target.value) || 85 }))}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Превью Take (3 варианта)</CardTitle>
            <CardDescription>Макс. сторона после даунскейла до оплаты. Больше значение — выше качество превью</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2 max-w-xs">
              <Label htmlFor="take_preview_max_dim">Макс. сторона (px)</Label>
              <Input
                id="take_preview_max_dim"
                type="number"
                min={400}
                max={2048}
                value={form.take_preview_max_dim}
                onChange={(e) => setForm((p) => ({ ...p, take_preview_max_dim: Number(e.target.value) || 800 }))}
              />
              <p className="text-xs text-muted-foreground">800 = меньше размер; 1024+ = выше качество</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Превью Job (paywall)</CardTitle>
            <CardDescription>Превью перегенерации/одного кадра тоже уменьшается; не в full-size</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2 max-w-xs">
              <Label htmlFor="job_preview_max_dim">Макс. сторона (px)</Label>
              <Input
                id="job_preview_max_dim"
                type="number"
                min={400}
                max={2048}
                value={form.job_preview_max_dim}
                onChange={(e) => setForm((p) => ({ ...p, job_preview_max_dim: Number(e.target.value) || 800 }))}
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Вотермарк</CardTitle>
            <CardDescription>Текст и отображение. Пустое поле текста = из .env WATERMARK_TEXT</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="grid gap-2">
                <Label htmlFor="watermark_text">Текст водяного знака</Label>
                <Input
                  id="watermark_text"
                  value={form.watermark_text}
                  onChange={(e) => setForm((p) => ({ ...p, watermark_text: e.target.value }))}
                  placeholder="пусто = из .env"
                />
                {settings.watermark_text_effective != null && (settings.watermark_text == null || settings.watermark_text === '') && (
                  <p className="text-xs text-muted-foreground">Сейчас: {settings.watermark_text_effective}</p>
                )}
              </div>
              <div className="grid gap-2">
                <Label htmlFor="watermark_opacity">Прозрачность (0–255)</Label>
                <Input
                  id="watermark_opacity"
                  type="number"
                  min={0}
                  max={255}
                  value={form.watermark_opacity}
                  onChange={(e) => setForm((p) => ({ ...p, watermark_opacity: Number(e.target.value) || 60 }))}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="watermark_tile_spacing">Шаг сетки (px)</Label>
                <Input
                  id="watermark_tile_spacing"
                  type="number"
                  min={50}
                  max={500}
                  value={form.watermark_tile_spacing}
                  onChange={(e) => setForm((p) => ({ ...p, watermark_tile_spacing: Number(e.target.value) || 200 }))}
                />
              </div>
              <div className="grid gap-2">
                <Label>Двухслойный контрастный вотермарк</Label>
                <Select
                  value={form.watermark_use_contrast ? 'yes' : 'no'}
                  onValueChange={(v) => setForm((p) => ({ ...p, watermark_use_contrast: v === 'yes' }))}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="yes">Да (виден на светлом и тёмном фоне)</SelectItem>
                    <SelectItem value="no">Нет</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>

        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Сохранить политику превью
        </Button>
      </form>
    </div>
  )
}
