import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  trendPosterService,
  trendsService,
  type UnpublishedTrend,
  type TrendPostItem,
  type PosterSettingsRes,
} from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Send,
  Loader2,
  ImagePlus,
  Trash2,
  Settings,
  Eye,
  AlertTriangle,
  CheckCircle2,
  SendHorizontal,
} from 'lucide-react'
import { useState, useEffect, useRef } from 'react'
import { toast } from 'sonner'

const CAPTION_MAX_LENGTH = 1024

/** Формат даты для отображения (актуален для 2026): «4 мар 2026, 20:45» или «сегодня в 20:45» / «вчера в 15:30». */
function formatPosterDate(isoString: string | null | undefined): string {
  if (!isoString) return '—'
  const d = new Date(isoString)
  if (Number.isNaN(d.getTime())) return '—'
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  const dateOnly = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const time = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  if (dateOnly.getTime() === today.getTime()) return `Сегодня в ${time}`
  if (dateOnly.getTime() === yesterday.getTime()) return `Вчера в ${time}`
  return d.toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Относительное время для подсказки: «2 ч назад», «вчера», «3 мар 2026». */
function formatPosterDateRelative(isoString: string | null | undefined): string {
  if (!isoString) return ''
  const d = new Date(isoString)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60_000)
  const diffHours = Math.floor(diffMs / 3600_000)
  const diffDays = Math.floor(diffMs / 86400_000)
  if (diffMin < 1) return 'только что'
  if (diffMin < 60) return `${diffMin} мин назад`
  if (diffHours < 24) return `${diffHours} ч назад`
  if (diffDays === 1) return 'вчера'
  if (diffDays < 7) return `${diffDays} дн назад`
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })
}

function ExampleThumb({ trendId, hasExample }: { trendId: string; hasExample: boolean }) {
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
  }, [trendId, hasExample])
  if (!hasExample || !blobUrl) {
    return (
      <div className="w-24 h-24 rounded-lg bg-muted flex items-center justify-center shrink-0">
        <ImagePlus className="h-8 w-8 text-muted-foreground" />
      </div>
    )
  }
  return (
    <img
      src={blobUrl}
      alt="Пример"
      className="w-24 h-24 rounded-lg object-cover shrink-0 border border-border"
    />
  )
}

export function TrendPosterPage() {
  const queryClient = useQueryClient()
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewCaption, setPreviewCaption] = useState('')
  const [previewTrend, setPreviewTrend] = useState<UnpublishedTrend | null>(null)
  const [publishConfirmOpen, setPublishConfirmOpen] = useState(false)
  const [publishTrend, setPublishTrend] = useState<UnpublishedTrend | null>(null)
  const [publishCaption, setPublishCaption] = useState('')
  const [applyTemplateKey, setApplyTemplateKey] = useState(0)
  const [publishAllConfirmOpen, setPublishAllConfirmOpen] = useState(false)
  const [publishAllInProgress, setPublishAllInProgress] = useState(false)

  const { data: settings, isLoading: settingsLoading } = useQuery({
    queryKey: ['trend-poster-settings'],
    queryFn: () => trendPosterService.getSettings(),
  })

  const { data: unpublishedData, isLoading: unpublishedLoading } = useQuery({
    queryKey: ['trend-poster-unpublished'],
    queryFn: () => trendPosterService.getUnpublished(),
    refetchInterval: 60_000,
  })

  const { data: postsData, isLoading: postsLoading } = useQuery({
    queryKey: ['trend-poster-posts'],
    queryFn: () => trendPosterService.getPosts(),
    refetchInterval: 60_000,
  })

  const publishMutation = useMutation({
    mutationFn: ({ trendId, caption }: { trendId: string; caption: string }) =>
      trendPosterService.publish(trendId, caption),
    onSuccess: () => {
      setPublishConfirmOpen(false)
      setPublishTrend(null)
      setPublishCaption('')
      queryClient.invalidateQueries({ queryKey: ['trend-poster-posts'] })
      queryClient.invalidateQueries({ queryKey: ['trend-poster-unpublished'] })
      toast.success('Пост опубликован в канал')
    },
    onError: (err: { response?: { data?: { detail?: string | { message?: string } } }; message?: string }) => {
      const raw = err.response?.data?.detail
      const detail = typeof raw === 'string' ? raw : (raw && typeof raw === 'object' && 'message' in raw ? (raw as { message?: string }).message : null)
      const msg = detail || err.message || 'Ошибка публикации'
      const isChannelError = typeof msg === 'string' && (msg.includes('POSTER_CHANNEL') || msg.includes('канал') || msg.includes('канала'))
      toast.error(typeof msg === 'string' ? msg : 'Ошибка публикации', {
        description: isChannelError
          ? 'В .env на сервере добавьте POSTER_CHANNEL_ID=@nanobanana_al и перезапустите контейнер api (docker compose restart api).'
          : typeof msg === 'string' && msg.includes('картинки-примера')
            ? 'В админке: Тренды → выберите тренд → загрузите пример изображения, затем снова нажмите «Опубликовать».'
            : undefined,
      })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (postId: string) => trendPosterService.deletePost(postId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trend-poster-posts'] })
      queryClient.invalidateQueries({ queryKey: ['trend-poster-unpublished'] })
      toast.success('Пост удалён из канала')
    },
    onError: (err: { response?: { data?: { detail?: string } }; message?: string }) => {
      const msg = err.response?.data?.detail || err.message || 'Ошибка удаления'
      toast.error(typeof msg === 'string' ? msg : 'Ошибка')
    },
  })

  const updateSettingsMutation = useMutation({
    mutationFn: (payload: { poster_default_template?: string }) =>
      trendPosterService.updateSettings(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trend-poster-settings'] })
      toast.success('Настройки сохранены')
    },
    onError: (err: { response?: { data?: { detail?: string } }; message?: string }) => {
      const msg = err.response?.data?.detail || err.message || 'Ошибка сохранения'
      toast.error(typeof msg === 'string' ? msg : 'Ошибка')
    },
  })

  const handlePreview = (trend: UnpublishedTrend, caption: string) => {
    setPreviewTrend(trend)
    setPreviewCaption(caption)
    setPreviewOpen(true)
  }

  const handlePublishClick = (trend: UnpublishedTrend, caption: string) => {
    setPublishTrend(trend)
    setPublishCaption(caption)
    setPublishConfirmOpen(true)
  }

  const handlePublishConfirm = () => {
    if (!publishTrend) return
    publishMutation.mutate({ trendId: publishTrend.id, caption: publishCaption })
  }

  const handleApplyTemplate = () => {
    queryClient.invalidateQueries({ queryKey: ['trend-poster-settings'] })
    setApplyTemplateKey((k) => k + 1)
    toast.success('Шаблон применён ко всем карточкам')
  }

  const handlePreviewFirst = () => {
    const first = unpublished[0]
    if (!first || !settings?.poster_default_template) return
    const caption = (settings.poster_default_template ?? '')
      .replace(/\{name\}/g, first.name ?? '')
      .replace(/\{emoji\}/g, first.emoji ?? '')
      .replace(/\{description\}/g, first.description ?? '')
      .trim()
    setPreviewTrend(first)
    setPreviewCaption(caption)
    setPreviewOpen(true)
  }

  const handlePublishAllConfirm = async () => {
    const list = unpublished.filter((t) => t.has_example)
    if (list.length === 0) {
      toast.error('Нет трендов с примером для публикации')
      setPublishAllConfirmOpen(false)
      return
    }
    setPublishAllInProgress(true)
    let done = 0
    for (const trend of list) {
      try {
        const preview = await trendPosterService.preview(trend.id)
        await trendPosterService.publish(trend.id, preview.caption)
        done += 1
        toast.success(`Опубликовано ${done}/${list.length}: ${trend.name ?? trend.id}`)
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail
          ?? (err as Error)?.message ?? 'Ошибка'
        toast.error(`${trend.name ?? trend.id}: ${typeof msg === 'string' ? msg : 'Ошибка'}`)
      }
    }
    setPublishAllInProgress(false)
    setPublishAllConfirmOpen(false)
    queryClient.invalidateQueries({ queryKey: ['trend-poster-posts'] })
    queryClient.invalidateQueries({ queryKey: ['trend-poster-unpublished'] })
    if (done > 0) toast.success(`Готово: опубликовано ${done} из ${list.length} трендов`)
  }

  const unpublished = unpublishedData?.items ?? []
  const unpublishedWithExample = unpublished.filter((t) => t.has_example)
  const groupedByBlock = (() => {
    const byKey = new Map<string, UnpublishedTrend[]>()
    for (const t of unpublished) {
      const key = t.theme_id ?? '__no_theme__'
      if (!byKey.has(key)) byKey.set(key, [])
      byKey.get(key)!.push(t)
    }
    const blocks: { key: string; themeName: string; themeEmoji: string; order: number; items: UnpublishedTrend[] }[] = []
    byKey.forEach((items, key) => {
      const first = items[0]
      blocks.push({
        key,
        themeName: first?.theme_name ?? 'Без тематики',
        themeEmoji: first?.theme_emoji ?? '',
        order: first?.theme_order_index ?? 9999,
        items,
      })
    })
    blocks.sort((a, b) => a.order - b.order)
    return blocks
  })()
  const [publishBlockConfirm, setPublishBlockConfirm] = useState<{ block: typeof groupedByBlock[0] } | null>(null)
  const [publishBlockInProgress, setPublishBlockInProgress] = useState(false)
  const handlePublishBlockConfirm = async () => {
    if (!publishBlockConfirm) return
    const list = publishBlockConfirm.block.items.filter((t) => t.has_example)
    if (list.length === 0) {
      toast.error('В блоке нет трендов с примером')
      setPublishBlockConfirm(null)
      return
    }
    setPublishBlockInProgress(true)
    let done = 0
    for (const trend of list) {
      try {
        const preview = await trendPosterService.preview(trend.id)
        await trendPosterService.publish(trend.id, preview.caption)
        done += 1
        toast.success(`Опубликовано ${done}/${list.length}: ${trend.name ?? trend.id}`)
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail
          ?? (err as Error)?.message ?? 'Ошибка'
        toast.error(`${trend.name ?? trend.id}: ${typeof msg === 'string' ? msg : 'Ошибка'}`)
      }
    }
    const blockName = publishBlockConfirm.block.themeName
    setPublishBlockInProgress(false)
    setPublishBlockConfirm(null)
    queryClient.invalidateQueries({ queryKey: ['trend-poster-posts'] })
    queryClient.invalidateQueries({ queryKey: ['trend-poster-unpublished'] })
    if (done > 0) toast.success(`Блок «${blockName}»: опубликовано ${done} из ${list.length}`)
  }
  const postsRaw = postsData?.items ?? []
  const posts = [...postsRaw].sort((a, b) => {
    const ta = a.sent_at ? new Date(a.sent_at).getTime() : 0
    const tb = b.sent_at ? new Date(b.sent_at).getTime() : 0
    return tb - ta
  })
  const sentPosts = posts.filter((p) => p.status === 'sent')
  const lastSentAt = sentPosts.length > 0
    ? sentPosts.reduce((max, p) => {
        const t = p.sent_at ? new Date(p.sent_at).getTime() : 0
        return t > max ? t : max
      }, 0)
    : null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-violet-600 to-fuchsia-600 bg-clip-text text-transparent">
          Автопостер трендов
        </h1>
        <p className="text-muted-foreground mt-2">
          Публикация трендов в Telegram-канал с картинкой, подписью и кнопкой «Попробовать». К каждому тренду привязан свой диплинк — кнопка ведёт именно на этот тренд.
        </p>
        {/* Сводка для отслеживания (актуально на 2026) */}
        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-1 rounded-lg border bg-muted/40 px-4 py-3 text-sm">
          <span className="font-medium text-foreground">
            Новых: <span className="text-emerald-600 dark:text-emerald-400">{unpublishedWithExample.length}</span>
          </span>
          <span className="font-medium text-foreground">
            В канале: <span className="text-amber-600 dark:text-amber-400">{sentPosts.length}</span>
          </span>
          <span className="text-muted-foreground">
            Последняя отправка:{' '}
            {lastSentAt ? formatPosterDate(new Date(lastSentAt).toISOString()) : '—'}
          </span>
        </div>
      </div>

      <Tabs defaultValue="unpublished" className="space-y-4">
        <TabsList className="grid w-full max-w-lg grid-cols-3">
          <TabsTrigger value="unpublished" className="gap-1.5">
            Неопубликованные
            <Badge variant="secondary" className="ml-0.5 h-5 min-w-5 px-1 text-xs">
              {unpublished.length}
            </Badge>
          </TabsTrigger>
          <TabsTrigger value="published" className="gap-1.5">
            Опубликованные
            <Badge variant="secondary" className="ml-0.5 h-5 min-w-5 px-1 text-xs">
              {sentPosts.length}
            </Badge>
          </TabsTrigger>
          <TabsTrigger value="settings">Настройки</TabsTrigger>
        </TabsList>

        <TabsContent value="unpublished" className="space-y-4">
          {unpublishedLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground py-8">
              <Loader2 className="h-4 w-4 animate-spin" />
              Загрузка...
            </div>
          ) : unpublished.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-muted-foreground">
                Нет трендов для публикации (все уже опубликованы или нет включённых трендов с примером).
              </CardContent>
            </Card>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleApplyTemplate}
                  disabled={!settings?.poster_default_template}
                >
                  <CheckCircle2 className="h-4 w-4 mr-1" />
                  Применение
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handlePreviewFirst}
                  disabled={unpublished.length === 0 || !unpublished[0]?.has_example}
                >
                  <Eye className="h-4 w-4 mr-1" />
                  Предпросмотр поста
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="bg-violet-600 hover:bg-violet-700"
                  onClick={() => setPublishAllConfirmOpen(true)}
                  disabled={unpublishedWithExample.length === 0 || publishMutation.isPending}
                >
                  <SendHorizontal className="h-4 w-4 mr-1" />
                  Отправка всех трендов
                </Button>
                <span className="text-sm text-muted-foreground ml-2">
                  {unpublishedWithExample.length} с примером
                </span>
              </div>
              <div className="space-y-8">
                {groupedByBlock.map((block) => {
                  const withExample = block.items.filter((t) => t.has_example).length
                  return (
                    <Card key={block.key}>
                      <CardHeader className="pb-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <CardTitle className="text-lg flex items-center gap-2">
                            <span>{block.themeEmoji}</span>
                            <span>{block.themeName}</span>
                            <Badge variant="secondary" className="font-normal">
                              {block.items.length} трендов
                              {withExample < block.items.length ? `, ${withExample} с примером` : ''}
                            </Badge>
                          </CardTitle>
                          <Button
                            size="sm"
                            className="bg-violet-600 hover:bg-violet-700"
                            disabled={withExample === 0 || publishMutation.isPending || publishBlockInProgress}
                            onClick={() => setPublishBlockConfirm({ block })}
                          >
                            <SendHorizontal className="h-4 w-4 mr-1" />
                            Опубликовать блок
                          </Button>
                        </div>
                      </CardHeader>
                      <CardContent>
                        <div className="grid gap-4 md:grid-cols-2">
                          {block.items.map((trend) => (
                            <UnpublishedCard
                              key={`${trend.id}-${applyTemplateKey}`}
                              trend={trend}
                              defaultTemplate={settings?.poster_default_template ?? ''}
                              onPreview={handlePreview}
                              onPublish={handlePublishClick}
                              isPublishing={publishMutation.isPending}
                            />
                          ))}
                        </div>
                      </CardContent>
                    </Card>
                  )
                })}
              </div>
            </>
          )}
        </TabsContent>

        <TabsContent value="published" className="space-y-4">
          {postsLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground py-8">
              <Loader2 className="h-4 w-4 animate-spin" />
              Загрузка...
            </div>
          ) : sentPosts.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-muted-foreground">
                Пока нет постов в канале. Опубликуйте тренды во вкладке «Неопубликованные».
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                Список по дате отправки (сначала новые). Всего в канале: {sentPosts.length}
              </p>
              {sentPosts.map((post) => (
                <PublishedRow
                  key={post.id}
                  post={post}
                  onDelete={() => deleteMutation.mutate(post.id)}
                  isDeleting={deleteMutation.isPending}
                />
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="settings" className="space-y-4">
          <SettingsTab
            settings={settings}
            settingsLoading={settingsLoading}
            onSave={(payload) => updateSettingsMutation.mutate(payload)}
            isSaving={updateSettingsMutation.isPending}
          />
        </TabsContent>
      </Tabs>

      {/* Превью */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Превью поста</DialogTitle>
            <DialogDescription>
              Так будет выглядеть подпись к посту в канале. Под постом автоматически появится инлайн-кнопка со ссылкой на диплинк тренда (текст кнопки задаётся в настройках).
            </DialogDescription>
          </DialogHeader>
          {previewTrend && (
            <div className="space-y-3">
              <ExampleThumb trendId={previewTrend.id} hasExample={previewTrend.has_example} />
              <pre className="whitespace-pre-wrap text-sm rounded-lg bg-muted p-3 max-h-48 overflow-y-auto">
                {previewCaption || '(пусто)'}
              </pre>
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-muted-foreground">Инлайн-кнопка под постом:</p>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center justify-center rounded-md border border-input bg-muted px-3 py-1.5 text-sm font-medium">
                    {settings?.poster_button_text || 'Попробовать'}
                  </span>
                  {previewTrend.deeplink ? (
                    <a
                      href={previewTrend.deeplink}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-violet-600 hover:underline truncate max-w-[220px]"
                      title={previewTrend.deeplink}
                    >
                      {previewTrend.deeplink}
                    </a>
                  ) : (
                    <span className="text-xs text-muted-foreground">диплинк (нужен telegram_bot_username)</span>
                  )}
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setPreviewOpen(false)}>
              Закрыть
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Подтверждение публикации */}
      <Dialog open={publishConfirmOpen} onOpenChange={setPublishConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-violet-600">
              <AlertTriangle className="h-5 w-5" />
              Опубликовать в канал?
            </DialogTitle>
            <DialogDescription>
              Пост будет отправлен в настроенный канал. Убедитесь, что у тренда загружен пример.
            </DialogDescription>
          </DialogHeader>
          {publishTrend && (
            <div className="rounded-lg bg-muted p-3 text-sm space-y-2">
              <p>
                <strong>{publishTrend.emoji ?? ''} {publishTrend.name ?? ''}</strong>
              </p>
              <pre className="whitespace-pre-wrap max-h-32 overflow-y-auto">{publishCaption.slice(0, 300)}{publishCaption.length > 300 ? '…' : ''}</pre>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setPublishConfirmOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={handlePublishConfirm}
              disabled={publishMutation.isPending}
              className="bg-violet-600 hover:bg-violet-700"
            >
              {publishMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <Send className="h-4 w-4 mr-2" />
              )}
              Опубликовать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Подтверждение «Опубликовать все» */}
      <Dialog open={publishAllConfirmOpen} onOpenChange={setPublishAllConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-violet-600">
              <SendHorizontal className="h-5 w-5" />
              Опубликовать все тренды?
            </DialogTitle>
            <DialogDescription>
              В канал будут отправлены все неопубликованные тренды с примером ({unpublishedWithExample.length} шт.) по шаблону из настроек. Отправка по одному посту.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPublishAllConfirmOpen(false)} disabled={publishAllInProgress}>
              Отмена
            </Button>
            <Button
              onClick={handlePublishAllConfirm}
              disabled={publishAllInProgress}
              className="bg-violet-600 hover:bg-violet-700"
            >
              {publishAllInProgress ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <SendHorizontal className="h-4 w-4 mr-2" />
              )}
              Опубликовать все
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Подтверждение «Опубликовать блок» */}
      <Dialog open={!!publishBlockConfirm} onOpenChange={(open) => !open && setPublishBlockConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-violet-600">
              <SendHorizontal className="h-5 w-5" />
              Опубликовать блок?
            </DialogTitle>
            <DialogDescription>
              {publishBlockConfirm && (
                <>
                  В канал будут отправлены тренды блока «{publishBlockConfirm.block.themeEmoji} {publishBlockConfirm.block.themeName}»
                  ({publishBlockConfirm.block.items.filter((t) => t.has_example).length} с примером) по шаблону из настроек.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPublishBlockConfirm(null)} disabled={publishBlockInProgress}>
              Отмена
            </Button>
            <Button
              onClick={handlePublishBlockConfirm}
              disabled={publishBlockInProgress}
              className="bg-violet-600 hover:bg-violet-700"
            >
              {publishBlockInProgress ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <SendHorizontal className="h-4 w-4 mr-2" />
              )}
              Опубликовать блок
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function SettingsTab({
  settings,
  settingsLoading,
  onSave,
  isSaving,
}: {
  settings: PosterSettingsRes | undefined
  settingsLoading: boolean
  onSave: (payload: { poster_default_template?: string; poster_button_text?: string; poster_channel_id?: string; poster_bot_username?: string }) => void
  isSaving: boolean
}) {
  const [template, setTemplate] = useState(settings?.poster_default_template ?? '')
  const [buttonText, setButtonText] = useState(settings?.poster_button_text ?? 'Попробовать')
  const [channelId, setChannelId] = useState(settings?.poster_channel_id ?? '')
  const [botUsername, setBotUsername] = useState(settings?.poster_bot_username ?? '')
  useEffect(() => {
    setTemplate(settings?.poster_default_template ?? '')
    setButtonText(settings?.poster_button_text ?? 'Попробовать')
    setChannelId(settings?.poster_channel_id ?? '')
    setBotUsername(settings?.poster_bot_username ?? '')
  }, [settings?.poster_default_template, settings?.poster_button_text, settings?.poster_channel_id, settings?.poster_bot_username])

  const handleSave = () => {
    onSave({
      poster_channel_id: channelId.trim(),
      poster_bot_username: botUsername.trim().replace(/^@/, ''),
      poster_default_template: template,
      poster_button_text: (buttonText || 'Попробовать').trim() || 'Попробовать',
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <Settings className="h-5 w-5" />
          Настройки автопостера
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Укажите канал ниже (@username или числовой ID, например @nanobanana_al или -1003808081075). Сохраните — после этого кнопка «Опубликовать» будет отправлять посты в этот канал. К каждому посту добавляется инлайн-кнопка с диплинком тренда.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {settingsLoading ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Загрузка...
          </div>
        ) : (
          <>
            {!channelId.trim() && (
              <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
                <strong>Публикация в канал не сработает, пока канал не задан.</strong> Введите @username или ID канала в поле ниже и нажмите «Сохранить настройки».
              </div>
            )}
            {channelId.trim() && !botUsername.trim() && (
              <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
                <strong>Диплинка и кнопки «Попробовать» не будет</strong>, пока не указан username бота. Введите его в поле «Username бота» ниже и сохраните — тогда под каждым постом появится ссылка на тренд в боте.
              </div>
            )}
            <div className="space-y-2">
              <label className="text-sm font-medium">Канал Telegram</label>
              <input
                type="text"
                value={channelId}
                onChange={(e) => setChannelId(e.target.value)}
                placeholder="@nanobanana_al или -1003808081075"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
              <p className="text-xs text-muted-foreground">
                @username канала или числовой ID. Можно задать здесь (сохраняется в БД) или в переменной окружения POSTER_CHANNEL_ID на сервере.
              </p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Username бота (для диплинка)</label>
              <input
                type="text"
                value={botUsername}
                onChange={(e) => setBotUsername(e.target.value)}
                placeholder="NanoBananaBot или @NanoBananaBot"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Без @. Нужен для диплинка и кнопки «Попробовать» под каждым постом (ссылка вида t.me/BOT?start=trend_ID). Задайте здесь или TELEGRAM_BOT_USERNAME в .env.
              </p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Шаблон подписи по умолчанию</label>
              <Textarea
                placeholder="{emoji} {name}\n\n{description}\n\nПопробовать тут:"
                value={template}
                onChange={(e) => setTemplate(e.target.value)}
                rows={6}
                className="font-mono text-sm resize-none"
              />
              <p className="text-xs text-muted-foreground">
                Переменные: <code className="rounded bg-muted px-1">&#123;name&#125;</code>, <code className="rounded bg-muted px-1">&#123;emoji&#125;</code>, <code className="rounded bg-muted px-1">&#123;description&#125;</code>, <code className="rounded bg-muted px-1">&#123;theme&#125;</code> (тематика), <code className="rounded bg-muted px-1">&#123;theme_emoji&#125;</code>.
              </p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Текст инлайн-кнопки</label>
              <input
                type="text"
                value={buttonText}
                onChange={(e) => setButtonText(e.target.value)}
                placeholder="Попробовать"
                maxLength={64}
                className="w-full max-w-xs rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Кнопка под постом ведёт на диплинк тренда (старт бота с этим трендом). Telegram: макс. 64 символа.
              </p>
            </div>
            <Button onClick={handleSave} disabled={isSaving}>
              {isSaving ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              Сохранить настройки
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function UnpublishedCard({
  trend,
  defaultTemplate,
  onPreview,
  onPublish,
  isPublishing,
}: {
  trend: UnpublishedTrend
  defaultTemplate: string
  onPreview: (trend: UnpublishedTrend, caption: string) => void
  onPublish: (trend: UnpublishedTrend, caption: string) => void
  isPublishing: boolean
}) {
  const [caption, setCaption] = useState(() => {
    return defaultTemplate
      .replace(/\{name\}/g, trend.name ?? '')
      .replace(/\{emoji\}/g, trend.emoji ?? '')
      .replace(/\{description\}/g, trend.description ?? '')
      .trim()
  })

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-start justify-between gap-2 mb-2">
          <Badge variant="secondary" className="shrink-0 bg-emerald-600/20 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400">
            Новое
          </Badge>
          {trend.deeplink ? (
            <a
              href={trend.deeplink}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-violet-600 hover:underline truncate max-w-[180px]"
              title={trend.deeplink}
            >
              Диплинк →
            </a>
          ) : (
            <span className="text-xs text-muted-foreground">Диплинк (задайте telegram_bot_username)</span>
          )}
        </div>
        <div className="flex gap-4">
          <ExampleThumb trendId={trend.id} hasExample={trend.has_example} />
          <div className="flex-1 min-w-0 space-y-2">
            <p className="font-medium truncate">
              {trend.emoji ?? ''} {trend.name ?? ''}
            </p>
            <Textarea
              placeholder="Текст подписи..."
              value={caption}
              onChange={(e) => setCaption(e.target.value.slice(0, CAPTION_MAX_LENGTH))}
              rows={3}
              className="text-sm resize-none"
            />
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => onPreview(trend, caption)}
                disabled={!trend.has_example}
              >
                <Eye className="h-4 w-4 mr-1" />
                Превью
              </Button>
              <Button
                size="sm"
                onClick={() => onPublish(trend, caption)}
                disabled={!trend.has_example || isPublishing}
                className="bg-violet-600 hover:bg-violet-700"
              >
                {isPublishing ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-1" />
                ) : (
                  <Send className="h-4 w-4 mr-1" />
                )}
                Опубликовать
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function PublishedRow({
  post,
  onDelete,
  isDeleting,
}: {
  post: TrendPostItem
  onDelete: () => void
  isDeleting: boolean
}) {
  const sentAtFormatted = formatPosterDate(post.sent_at)
  const sentAtRelative = formatPosterDateRelative(post.sent_at)

  return (
    <Card>
      <CardContent className="py-4 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="font-medium truncate">
              {post.trend_emoji ?? ''} {post.trend_name ?? ''}
            </p>
            <Badge variant="outline" className="shrink-0 text-amber-600 border-amber-300 dark:text-amber-400 dark:border-amber-600">
              В канале
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground" title={sentAtRelative || undefined}>
            {sentAtFormatted}
            {sentAtRelative && (
              <span className="ml-1.5 text-xs opacity-80">· {sentAtRelative}</span>
            )}
          </p>
          {post.deeplink && (
            <a
              href={post.deeplink}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-violet-600 hover:underline truncate block max-w-full"
              title={post.deeplink}
            >
              Диплинк (кнопка «Попробовать» ведёт на этот тренд) →
            </a>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {post.status === 'sent' && (
            <Button
              variant="outline"
              size="sm"
              onClick={onDelete}
              disabled={isDeleting}
            >
              {isDeleting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
