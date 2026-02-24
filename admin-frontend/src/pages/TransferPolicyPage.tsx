import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { transferPolicyService, type TransferPolicySettings } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Loader2, Save, UserCog } from 'lucide-react'
import { useState, useEffect } from 'react'
import { toast } from 'sonner'

export function TransferPolicyPage() {
  const queryClient = useQueryClient()
  const { data: settings, isLoading } = useQuery({
    queryKey: ['transfer-policy-settings'],
    queryFn: () => transferPolicyService.getSettings(),
  })
  const [form, setForm] = useState<Partial<TransferPolicySettings>>({})

  useEffect(() => {
    if (settings?.global) setForm(settings.global)
  }, [settings])

  const updateMutation = useMutation({
    mutationFn: (payload: { global?: Partial<TransferPolicySettings>; trends?: Partial<TransferPolicySettings> }) =>
      transferPolicyService.updateSettings(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transfer-policy-settings'] })
      toast.success('Политика переноса личности сохранена')
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? err?.message ?? 'Ошибка при сохранении'
      const text = typeof msg === 'string' ? msg : JSON.stringify(msg)
      toast.error(text)
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    updateMutation.mutate({ global: { ...settings?.global, ...form } })
  }

  const handleChange = (key: keyof TransferPolicySettings, value: string) => {
    setForm((prev: Partial<TransferPolicySettings>) => ({ ...prev, [key]: value }))
  }

  if (isLoading || !settings?.global) return <div className="text-center py-8">Загрузка...</div>

  const current = { ...settings.global, ...form }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <UserCog className="h-7 w-7" />
          Перенос личности (Transfer Policy)
        </h1>
        <p className="text-muted-foreground mt-1">
          Глобальная политика переноса личности. Текст попадает в блоки <strong>[IDENTITY TRANSFER]</strong>, <strong>[COMPOSITION]</strong> и <strong>[AVOID]</strong> финального промпта для Gemini. Одна запись на всё приложение.
        </p>
      </div>

      <form onSubmit={handleSubmit}>
        <Card>
          <CardHeader>
            <CardTitle>Настройки</CardTitle>
            <p className="text-sm text-muted-foreground">
              identity_rules_text → [IDENTITY TRANSFER], composition_rules_text → [COMPOSITION], avoid_default_items → [AVOID]. subject_reference_name — имя ссылки на фото в промпте (обычно IMAGE_1).
            </p>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid gap-2">
              <Label htmlFor="subject_reference_name">subject_reference_name</Label>
              <Input
                id="subject_reference_name"
                placeholder="IMAGE_1"
                value={current.subject_reference_name ?? ''}
                onChange={(e) => handleChange('subject_reference_name', e.target.value)}
              />
              <p className="text-xs text-muted-foreground">Имя ссылки на входное фото в промпте (например IMAGE_1).</p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="identity_lock_level">identity_lock_level</Label>
              <Input
                id="identity_lock_level"
                placeholder="strict"
                value={current.identity_lock_level ?? ''}
                onChange={(e) => handleChange('identity_lock_level', e.target.value)}
              />
              <p className="text-xs text-muted-foreground">Уровень блокировки личности (strict и т.д.).</p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="identity_rules_text">identity_rules_text → [IDENTITY TRANSFER]</Label>
              <Textarea
                id="identity_rules_text"
                rows={5}
                className="font-mono text-sm"
                placeholder="Preserve the face and identity from IMAGE_1 in the output. Do not alter facial features, skin tone, or distinguishing characteristics."
                value={current.identity_rules_text ?? ''}
                onChange={(e) => handleChange('identity_rules_text', e.target.value)}
              />
              <p className="text-xs text-muted-foreground">Текст блока [IDENTITY TRANSFER] в финальном промпте. Если пусто — подставится дефолтная фраза.</p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="composition_rules_text">composition_rules_text → [COMPOSITION]</Label>
              <Textarea
                id="composition_rules_text"
                rows={4}
                className="font-mono text-sm"
                placeholder="Place the subject from IMAGE_1 naturally in the scene. Maintain proportions and perspective."
                value={current.composition_rules_text ?? ''}
                onChange={(e) => handleChange('composition_rules_text', e.target.value)}
              />
              <p className="text-xs text-muted-foreground">Дополнение к [COMPOSITION] (после Subject framing / Framing hint из тренда).</p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="avoid_default_items">avoid_default_items → [AVOID]</Label>
              <Textarea
                id="avoid_default_items"
                rows={14}
                className="font-mono text-sm"
                placeholder={'Watermarks.\nLogos.\nText in image.\nChat or UI elements.\nBlurry face.\nIncorrect pose.\nCropped limbs.\n...'}
                value={current.avoid_default_items ?? ''}
                onChange={(e) => handleChange('avoid_default_items', e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Дефолтные пункты блока [AVOID] в промпте. По одному на строку или через точку с запятой. К ним в конце добавляется negative_scene из тренда (если задан). В промпте пункты выводятся через «; ».
              </p>
            </div>

            {current.updated_at && (
              <p className="text-xs text-muted-foreground">
                Обновлено: {new Date(current.updated_at).toLocaleString('ru-RU')}
              </p>
            )}

            <Button type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Сохранить
            </Button>
          </CardContent>
        </Card>
      </form>

      <p className="text-sm text-muted-foreground">
        Связанные разделы: <Link to="/trends" className="underline text-primary">Тренды</Link>
        {' · '}
        <Link to="/prompt-playground" className="underline text-primary">Playground</Link>
      </p>
    </div>
  )
}
