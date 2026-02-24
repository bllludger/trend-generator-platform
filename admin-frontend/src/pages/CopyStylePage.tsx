import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { copyStyleService, type CopyStyleSettings } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Copy, ImageIcon, Loader2, Save, Sparkles } from 'lucide-react'
import { useState, useEffect } from 'react'
import { toast } from 'sonner'

export function CopyStylePage() {
  const queryClient = useQueryClient()
  const { data: settings, isLoading } = useQuery({
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
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? err?.message ?? 'Ошибка при сохранении'
      const text = typeof msg === 'string' ? msg : JSON.stringify(msg)
      toast.error(text)
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const payload: Partial<CopyStyleSettings> = {
      model: current.model ?? '',
      system_prompt: current.system_prompt ?? '',
      user_prompt: current.user_prompt ?? '',
      max_tokens: current.max_tokens ?? 1536,
      prompt_suffix: current.prompt_suffix ?? '',
      prompt_instruction_3_images: current.prompt_instruction_3_images ?? '',
      prompt_instruction_2_images: current.prompt_instruction_2_images ?? '',
      generation_system_prompt_prefix: current.generation_system_prompt_prefix ?? '',
      generation_negative_prompt: current.generation_negative_prompt ?? '',
      generation_safety_constraints: current.generation_safety_constraints ?? '',
      generation_image_constraints_template: current.generation_image_constraints_template ?? '',
      generation_default_size: current.generation_default_size ?? '1024x1024',
      generation_default_format: current.generation_default_format ?? 'png',
      generation_default_model: current.generation_default_model ?? '',
    }
    updateMutation.mutate(payload)
  }

  const handleChange = (key: keyof CopyStyleSettings, value: string | number) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  if (isLoading || !settings) return <div className="text-center py-8">Загрузка...</div>

  const current = { ...settings, ...form }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Сделать такую же</h1>
        <p className="text-muted-foreground">
          Единая точка управления флоу «Сделать такую же»: анализ референса (Vision), инструкции для лиц и полный промпт генерации (Gemini). Не смешивается с трендами. Изменения применяются сразу.
        </p>
      </div>

      <form onSubmit={handleSubmit}>
        <Tabs defaultValue="analysis" className="w-full">
          <TabsList className="grid w-full grid-cols-3 max-w-2xl">
            <TabsTrigger value="analysis" className="flex items-center gap-2">
              <Copy className="h-4 w-4" />
              Анализ референса
            </TabsTrigger>
            <TabsTrigger value="generation" className="flex items-center gap-2">
              <ImageIcon className="h-4 w-4" />
              Инструкции (лица)
            </TabsTrigger>
            <TabsTrigger value="prompt" className="flex items-center gap-2">
              <Sparkles className="h-4 w-4" />
              Промпт генерации
            </TabsTrigger>
          </TabsList>

          <TabsContent value="analysis" className="mt-6">
            <Card>
              <CardHeader>
                <CardTitle>Настройки анализа референса</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Модель ChatGPT Vision и промпты задают, как описывается изображение и формируется текст для копирования стиля (акторы, композиция).
                </p>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="model">Модель ChatGPT (Vision)</Label>
                    <Input
                      id="model"
                      placeholder="gpt-4o"
                      value={String(current.model ?? '')}
                      onChange={(e) => handleChange('model', e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">Например: gpt-4o, gpt-4o-mini</p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="max_tokens">max_tokens</Label>
                    <Input
                      id="max_tokens"
                      type="number"
                      min={256}
                      max={4096}
                      value={Number(current.max_tokens ?? 1536)}
                      onChange={(e) => handleChange('max_tokens', parseInt(e.target.value) || 1536)}
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="system_prompt">Системный промпт</Label>
                  <Textarea
                    id="system_prompt"
                    rows={10}
                    className="font-mono text-sm"
                    value={String(current.system_prompt ?? '')}
                    onChange={(e) => handleChange('system_prompt', e.target.value)}
                    placeholder="Инструкция модели: как анализировать изображение и формировать промпт..."
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="user_prompt">Пользовательский промпт (к изображению)</Label>
                  <Textarea
                    id="user_prompt"
                    rows={3}
                    className="font-mono text-sm"
                    value={String(current.user_prompt ?? '')}
                    onChange={(e) => handleChange('user_prompt', e.target.value)}
                    placeholder="Текст запроса к модели по анализу изображения..."
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="prompt_suffix">Суффикс промпта для генератора (Gemini)</Label>
                  <Textarea
                    id="prompt_suffix"
                    rows={3}
                    className="font-mono text-sm"
                    value={String(current.prompt_suffix ?? '')}
                    onChange={(e) => handleChange('prompt_suffix', e.target.value)}
                    placeholder="Добавляется к custom_prompt. Например: Always include the person or people from the input image..."
                  />
                  <p className="text-xs text-muted-foreground">
                    Добавляется к промпту при отправке в генератор (режим «Своя идея» / copy flow).
                  </p>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="generation" className="mt-6">
            <Card>
              <CardHeader>
                <CardTitle>Инструкции для генерации (лица в сцене)</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Текст, который добавляется в запрос к Gemini при флоу «2 фотографии»: порядок изображений и кто за кого (девушка/парень). Пишите на английском для Gemini.
                </p>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="space-y-2">
                  <Label htmlFor="prompt_instruction_3_images">Когда 3 фото: стиль + лицо девушки + лицо парня</Label>
                  <Textarea
                    id="prompt_instruction_3_images"
                    rows={5}
                    className="font-mono text-sm"
                    value={String(current.prompt_instruction_3_images ?? '')}
                    onChange={(e) => handleChange('prompt_instruction_3_images', e.target.value)}
                    placeholder="(1) Style reference. (2) Face for woman. (3) Face for man. Generate scene with these faces."
                  />
                  <p className="text-xs text-muted-foreground">
                    Порядок вложений: 1 — референс стиля, 2 — фото девушки (лицо для женского персонажа), 3 — фото парня (лицо для мужского).
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="prompt_instruction_2_images">Когда 2 фото: лицо девушки + лицо парня (без референса в запросе)</Label>
                  <Textarea
                    id="prompt_instruction_2_images"
                    rows={4}
                    className="font-mono text-sm"
                    value={String(current.prompt_instruction_2_images ?? '')}
                    onChange={(e) => handleChange('prompt_instruction_2_images', e.target.value)}
                    placeholder="(1) Face for woman. (2) Face for man. Generate scene with these faces."
                  />
                  <p className="text-xs text-muted-foreground">
                    Порядок: 1 — фото девушки, 2 — фото парня. Стиль задаётся только текстом (из анализа референса).
                  </p>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="prompt" className="mt-6">
            <Card>
              <CardHeader>
                <CardTitle>Промпт генерации (Gemini)</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Системный префикс, ограничения и дефолты только для флоу «Сделать такую же». Тренды и общий «Промпт генерации» здесь не используются — единая точка управления.
                </p>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="space-y-2">
                  <Label htmlFor="generation_system_prompt_prefix">Системный префикс (Gemini)</Label>
                  <Textarea
                    id="generation_system_prompt_prefix"
                    rows={12}
                    className="font-mono text-sm"
                    value={String(current.generation_system_prompt_prefix ?? '')}
                    onChange={(e) => handleChange('generation_system_prompt_prefix', e.target.value)}
                    placeholder="You are an image generation system... TREND (text) defines style. Attached images define who must appear..."
                  />
                  <p className="text-xs text-muted-foreground">
                    Полный системный блок для Gemini. Ниже в запрос подставится TREND (текст из анализа референса) и инструкции для 2/3 фото.
                  </p>
                </div>
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="space-y-2">
                    <Label htmlFor="generation_default_model">Модель Gemini</Label>
                    <Input
                      id="generation_default_model"
                      placeholder="gemini-2.5-flash-image"
                      value={String(current.generation_default_model ?? '')}
                      onChange={(e) => handleChange('generation_default_model', e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="generation_default_size">Размер по умолчанию</Label>
                    <Input
                      id="generation_default_size"
                      placeholder="1024x1024"
                      value={String(current.generation_default_size ?? '1024x1024')}
                      onChange={(e) => handleChange('generation_default_size', e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="generation_default_format">Формат</Label>
                    <Input
                      id="generation_default_format"
                      placeholder="png"
                      value={String(current.generation_default_format ?? 'png')}
                      onChange={(e) => handleChange('generation_default_format', e.target.value)}
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="generation_negative_prompt">Negative prompt</Label>
                  <Textarea
                    id="generation_negative_prompt"
                    rows={2}
                    className="font-mono text-sm"
                    value={String(current.generation_negative_prompt ?? '')}
                    onChange={(e) => handleChange('generation_negative_prompt', e.target.value)}
                    placeholder="Оставьте пустым или укажите, что исключить из сцены"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="generation_safety_constraints">Ограничения безопасности</Label>
                  <Textarea
                    id="generation_safety_constraints"
                    rows={2}
                    className="font-mono text-sm"
                    value={String(current.generation_safety_constraints ?? '')}
                    onChange={(e) => handleChange('generation_safety_constraints', e.target.value)}
                    placeholder="no text generation, no chat."
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="generation_image_constraints_template">Шаблон ограничений изображения</Label>
                  <Input
                    id="generation_image_constraints_template"
                    className="font-mono"
                    value={String(current.generation_image_constraints_template ?? 'size={size}, format={format}')}
                    onChange={(e) => handleChange('generation_image_constraints_template', e.target.value)}
                    placeholder="size={size}, format={format}"
                  />
                  <p className="text-xs text-muted-foreground">Плейсхолдеры: {'{size}'}, {'{format}'}</p>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        <div className="flex justify-end mt-6">
          <Button type="submit" disabled={updateMutation.isPending}>
            {updateMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            <span className="ml-2">Сохранить все настройки</span>
          </Button>
        </div>
      </form>
    </div>
  )
}
