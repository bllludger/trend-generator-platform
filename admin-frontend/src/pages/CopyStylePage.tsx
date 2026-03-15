import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { copyStyleService, type CopyStyleSettings } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Loader2, Save } from 'lucide-react'
import { useState, useEffect } from 'react'
import { toast } from 'sonner'

export function CopyStylePage() {
  const queryClient = useQueryClient()
  const { data: settings, isLoading, isError, error } = useQuery({
    queryKey: ['copy-style-settings'],
    queryFn: () => copyStyleService.getSettings(),
  })
  const [form, setForm] = useState<Partial<CopyStyleSettings>>({})

  useEffect(() => {
    if (settings) setForm(settings)
  }, [settings])

  const updateMutation = useMutation({
    mutationFn: (payload: Partial<CopyStyleSettings>) => copyStyleService.updateSettings(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['copy-style-settings'] })
      toast.success('Настройки «Сделать такую же» сохранены')
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string }; message?: string } })?.response?.data?.detail
        ?? (err as Error)?.message ?? 'Ошибка при сохранении'
      toast.error(typeof msg === 'string' ? msg : JSON.stringify(msg))
    },
  })

  const maxTokensUnlimited = (Number(form.max_tokens) ?? Number(settings?.max_tokens) ?? 3000) >= 128_000

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const rawMax = maxTokensUnlimited ? 128_000 : (Number(form.max_tokens) ?? Number(settings?.max_tokens) ?? 3000)
    const payload: Partial<CopyStyleSettings> = {
      ...settings,
      model: (form.model ?? settings?.model ?? '').trim() || 'gpt-5.2',
      system_prompt: form.system_prompt ?? settings?.system_prompt ?? '',
      max_tokens: Math.max(256, rawMax),
    }
    updateMutation.mutate(payload)
  }

  const handleChange = (key: keyof CopyStyleSettings, value: string | number) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  if (isError) {
    const errMsg = (error as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail
      ?? (error as Error)?.message ?? 'Не удалось загрузить настройки'
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
        <p className="font-medium text-destructive">Ошибка загрузки</p>
        <p className="mt-2 text-sm text-muted-foreground">{typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg)}</p>
      </div>
    )
  }

  if (isLoading || !settings) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  const current = { ...settings, ...form }
  const systemPrompt = String(current.system_prompt ?? '')

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Сделать такую же</h1>
        <p className="text-muted-foreground mt-1">
          Один системный промпт Vision (например NeoBanana Prompt Builder). Референс + своё лицо → Vision возвращает один промпт в code block → он используется 1:1 в Gemini с фото пользователя → 3 варианта (A/B/C), выбор, оплата 4K.
        </p>
      </div>

      <form onSubmit={handleSubmit}>
        <Card>
          <CardHeader>
            <CardTitle>Vision: системный промпт и настройки</CardTitle>
            <p className="text-sm text-muted-foreground">
              Только system_prompt, model и max_tokens. User-сообщение фиксировано в коде.
            </p>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="model">model (OpenAI Vision)</Label>
                <Input
                  id="model"
                  placeholder="gpt-5.2"
                  value={String(current.model ?? '')}
                  onChange={(e) => handleChange('model', e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="max_tokens">max_tokens</Label>
                <div className="flex items-center gap-4">
                  <Input
                    id="max_tokens"
                    type="number"
                    min={256}
                    value={maxTokensUnlimited ? 128000 : (Number(current.max_tokens) ?? 3000)}
                    onChange={(e) => handleChange('max_tokens', parseInt(e.target.value, 10) || 256)}
                    disabled={maxTokensUnlimited}
                    className="w-32"
                  />
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={maxTokensUnlimited}
                      onChange={(e) => handleChange('max_tokens', e.target.checked ? 128000 : 3000)}
                    />
                    <span className="text-sm">Без лимита (max)</span>
                  </label>
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="system_prompt">system_prompt</Label>
              <Textarea
                id="system_prompt"
                rows={14}
                className="font-mono text-sm resize-y"
                value={systemPrompt}
                onChange={(e) => handleChange('system_prompt', e.target.value)}
                placeholder="Системное сообщение в запросе к ChatGPT (формат SCENE / STYLE / META)..."
                required
              />
            </div>

            <div className="flex justify-end pt-2">
              <Button type="submit" disabled={updateMutation.isPending || !systemPrompt.trim()}>
                {updateMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                <span className="ml-2">Сохранить</span>
              </Button>
            </div>
          </CardContent>
        </Card>
      </form>
    </div>
  )
}
