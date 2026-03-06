import { useState, useMemo, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { trafficService, type TrafficSourceItem } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { format, subDays } from 'date-fns'
import { ru } from 'date-fns/locale'
import {
  MousePointer,
  Users,
  CreditCard,
  TrendingUp,
  Copy,
  Plus,
  ArrowLeft,
  Check,
  Pencil,
  Trash2,
} from 'lucide-react'
import { formatNumber } from '@/lib/utils'
import { toast } from 'sonner'

function fallbackCopyText(text: string): boolean {
  try {
    const el = document.createElement('textarea')
    el.value = text
    el.setAttribute('readonly', '')
    el.style.position = 'fixed'
    el.style.left = '-9999px'
    el.style.top = '0'
    document.body.appendChild(el)
    el.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(el)
    return ok
  } catch {
    return false
  }
}

const PLATFORMS = [
  { value: 'telegram', label: 'Telegram' },
  { value: 'vk', label: 'VK' },
  { value: 'instagram', label: 'Instagram' },
  { value: 'youtube', label: 'YouTube' },
  { value: 'other', label: 'Другое' },
]

function defaultDateRange() {
  const end = new Date()
  const start = subDays(end, 30)
  return {
    date_from: format(start, 'yyyy-MM-dd'),
    date_to: format(end, 'yyyy-MM-dd'),
  }
}

export default function TrafficPage() {
  const queryClient = useQueryClient()
  const [dateFrom, setDateFrom] = useState(defaultDateRange().date_from)
  const [dateTo, setDateTo] = useState(defaultDateRange().date_to)
  const [activeTab, setActiveTab] = useState('overview')
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [sourceDialogOpen, setSourceDialogOpen] = useState(false)
  const [campaignDialogOpen, setCampaignDialogOpen] = useState(false)
  const [newSource, setNewSource] = useState({ slug: '', name: '', url: '', platform: 'other' })
  const [newCampaign, setNewCampaign] = useState({
    source_id: '',
    name: '',
    budget_rub: 0,
    date_from: defaultDateRange().date_from,
    date_to: defaultDateRange().date_to,
    notes: '',
  })
  const [copySuccess, setCopySuccess] = useState<string | null>(null)
  const [editingSource, setEditingSource] = useState<TrafficSourceItem | null>(null)
  const [sourceToDelete, setSourceToDelete] = useState<TrafficSourceItem | null>(null)
  const [editSourceForm, setEditSourceForm] = useState({ name: '', url: '', is_active: true })

  useEffect(() => {
    if (editingSource) {
      setEditSourceForm({
        name: editingSource.name,
        url: editingSource.url ?? '',
        is_active: editingSource.is_active,
      })
    }
  }, [editingSource])

  const dateParams = useMemo(() => ({ date_from: dateFrom, date_to: dateTo }), [dateFrom, dateTo])

  const { data: botInfo } = useQuery({
    queryKey: ['bot-info'],
    queryFn: () => trafficService.getBotInfo(),
  })
  const botUsername = botInfo?.username ?? ''

  const { data: overview } = useQuery({
    queryKey: ['traffic-overview', dateFrom, dateTo],
    queryFn: () => trafficService.getOverview(dateParams),
  })

  const { data: statsData } = useQuery({
    queryKey: ['traffic-stats', dateFrom, dateTo],
    queryFn: () => trafficService.getStats(dateParams),
  })
  const sourcesStats = statsData?.sources ?? []

  const { data: sourcesList } = useQuery({
    queryKey: ['traffic-sources-list'],
    queryFn: () => trafficService.listSources({ active_only: false }),
  })

  const { data: campaignsList } = useQuery({
    queryKey: ['ad-campaigns'],
    queryFn: () => trafficService.listCampaigns(),
  })
  const campaigns = campaignsList ?? []

  const campaignIdsKey = useMemo(() => campaigns.map((c) => c.id).sort().join(','), [campaigns])
  const rois = useQuery({
    queryKey: ['ad-campaigns-roi', campaignIdsKey],
    queryFn: async () => {
      const ids = campaigns.map((c) => c.id)
      const results = await Promise.all(
        ids.map((id) => trafficService.getCampaignRoi(id).catch(() => null))
      )
      return Object.fromEntries(
        ids.map((id, i) => [id, results[i]])
      ) as Record<string, Awaited<ReturnType<typeof trafficService.getCampaignRoi>> | null>
    },
    enabled: campaigns.length > 0,
  })
  const roiMap = rois.data ?? {}

  const { data: funnelData } = useQuery({
    queryKey: ['traffic-funnel', selectedSlug, dateFrom, dateTo],
    queryFn: () =>
      selectedSlug ? trafficService.getFunnel(selectedSlug, dateParams) : Promise.resolve(null),
    enabled: !!selectedSlug,
  })

  const { data: sourceUsersData } = useQuery({
    queryKey: ['traffic-source-users', selectedSlug],
    queryFn: () =>
      selectedSlug ? trafficService.getSourceUsers(selectedSlug, { limit: 50, offset: 0 }) : Promise.resolve(null),
    enabled: !!selectedSlug,
  })

  const createSourceMutation = useMutation({
    mutationFn: (body: { slug: string; name: string; url?: string; platform?: string }) =>
      trafficService.createSource(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['traffic-sources-list'] })
      queryClient.invalidateQueries({ queryKey: ['traffic-stats'] })
      setSourceDialogOpen(false)
      setNewSource({ slug: '', name: '', url: '', platform: 'other' })
    },
  })

  const updateSourceMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { name?: string; url?: string; is_active?: boolean } }) =>
      trafficService.updateSource(id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['traffic-sources-list'] })
      queryClient.invalidateQueries({ queryKey: ['traffic-stats'] })
      setEditingSource(null)
      toast.success('Источник обновлён')
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(err?.response?.data?.detail ?? 'Ошибка при сохранении')
    },
  })

  const deleteSourceMutation = useMutation({
    mutationFn: (id: string) => trafficService.deleteSource(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['traffic-sources-list'] })
      queryClient.invalidateQueries({ queryKey: ['traffic-stats'] })
      setSourceToDelete(null)
      toast.success('Источник удалён')
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(err?.response?.data?.detail ?? 'Ошибка при удалении')
    },
  })

  const createCampaignMutation = useMutation({
    mutationFn: (body: {
      source_id: string
      name: string
      budget_rub: number
      date_from: string
      date_to: string
      notes?: string
    }) => trafficService.createCampaign(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ad-campaigns'] })
      setCampaignDialogOpen(false)
      setNewCampaign({
        source_id: '',
        name: '',
        budget_rub: 0,
        date_from: dateFrom,
        date_to: dateTo,
        notes: '',
      })
    },
  })

  const getLinkUrl = (slug: string, campaign?: string) => {
    const param = campaign ? `src_${slug}_c_${campaign.replace(/[^a-zA-Z0-9_-]/g, '')}`.slice(0, 64) : `src_${slug}`
    return botUsername ? `https://t.me/${botUsername}?start=${param}` : ''
  }

  const copyLink = (slug: string, campaign?: string) => {
    const url = getLinkUrl(slug, campaign)
    if (!url) {
      toast.error('Укажите username бота в настройках (telegram_bot_username), чтобы получить ссылку.')
      return
    }
    const doCopy = () => {
      setCopySuccess(slug)
      setTimeout(() => setCopySuccess(null), 2000)
      toast.success('Ссылка скопирована')
    }
    // Сначала пробуем fallback (работает без HTTPS), затем clipboard API
    if (fallbackCopyText(url)) {
      doCopy()
      return
    }
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(url).then(doCopy).catch(() => {
        toast.error('Не удалось скопировать. Выделите ссылку ниже и скопируйте вручную (Ctrl+C).')
      })
    } else {
      toast.error('Выделите ссылку ниже и скопируйте вручную (Ctrl+C).')
    }
  }

  const chartData = useMemo(() => {
    const byDate: Record<string, { date: string; clicks: number; payments: number; stars: number }> = {}
    overview?.daily_clicks?.forEach((d) => {
      byDate[d.date] = { date: d.date, clicks: d.clicks, payments: 0, stars: 0 }
    })
    overview?.daily_purchases?.forEach((d) => {
      if (!byDate[d.date]) byDate[d.date] = { date: d.date, clicks: 0, payments: 0, stars: 0 }
      byDate[d.date].payments = d.payments
      byDate[d.date].stars = d.stars
    })
    return Object.values(byDate).sort(
      (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
    )
  }, [overview])

  if (selectedSlug) {
    const sourceName = sourcesList?.find((s) => s.slug === selectedSlug)?.name ?? selectedSlug
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => setSelectedSlug(null)}>
            <ArrowLeft className="h-4 w-4 mr-1" />
            Назад
          </Button>
          <h1 className="text-2xl font-bold">Источник: {sourceName}</h1>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Воронка</CardTitle>
          </CardHeader>
          <CardContent>
            {funnelData?.steps?.length ? (
              <div className="flex flex-wrap gap-4 items-end">
                {funnelData.steps.map((step, i) => (
                  <div key={step.name} className="flex flex-col items-center gap-1">
                    <div className="text-xs text-muted-foreground whitespace-nowrap">{step.label}</div>
                    <div
                      className="bg-primary/20 rounded-t px-3 py-2 min-w-[80px] text-center"
                      style={{ height: `${Math.max(24, 120 - i * 18)}px`, minHeight: 40 }}
                    >
                      <span className="font-semibold">{formatNumber(step.count)}</span>
                      <span className="text-muted-foreground text-xs ml-1">({step.pct}%)</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-muted-foreground">Нет данных за период.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Последние пользователи</CardTitle>
          </CardHeader>
          <CardContent>
            {sourceUsersData?.items?.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Telegram ID</TableHead>
                    <TableHead>Username / Имя</TableHead>
                    <TableHead>Дата</TableHead>
                    <TableHead>Покупка</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sourceUsersData.items.map((u) => (
                    <TableRow key={u.id}>
                      <TableCell className="font-mono">{u.telegram_id}</TableCell>
                      <TableCell>{u.username || u.first_name || '—'}</TableCell>
                      <TableCell>{u.created_at ? format(u.created_at, 'd MMM yyyy', { locale: ru }) : '—'}</TableCell>
                      <TableCell>{u.has_purchased ? <Check className="h-4 w-4 text-green-600" /> : '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="text-muted-foreground">Нет пользователей.</p>
            )}
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold">Реклама и трафик</h1>
        <div className="flex items-center gap-2">
          <Label className="text-sm text-muted-foreground">С</Label>
          <Input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="w-40"
          />
          <Label className="text-sm text-muted-foreground">По</Label>
          <Input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="w-40"
          />
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="overview">Обзор</TabsTrigger>
          <TabsTrigger value="sources">Источники</TabsTrigger>
          <TabsTrigger value="campaigns">Кампании</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium">Переходы</CardTitle>
                <MousePointer className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{formatNumber(overview?.total_clicks ?? 0)}</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium">Новых пользователей</CardTitle>
                <Users className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{formatNumber(overview?.new_users ?? 0)}</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium">Конверсия в покупку</CardTitle>
                <TrendingUp className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{overview?.conversion_rate_pct ?? 0}%</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium">Выручка (руб.)</CardTitle>
                <CreditCard className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{formatNumber(overview?.revenue_rub ?? 0)}</div>
              </CardContent>
            </Card>
          </div>

          {chartData.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Переходы и покупки по дням</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                      <XAxis
                        dataKey="date"
                        tickFormatter={(v) => format(new Date(v), 'd MMM', { locale: ru })}
                        className="text-xs"
                      />
                      <YAxis className="text-xs" />
                      <Tooltip
                        labelFormatter={(v) => format(new Date(v), 'd MMM yyyy', { locale: ru })}
                        formatter={(value: number) => [formatNumber(value), '']}
                      />
                      <Area type="monotone" dataKey="clicks" stroke="hsl(var(--primary))" fill="hsl(var(--primary) / 0.2)" name="Переходы" />
                      <Area type="monotone" dataKey="payments" stroke="hsl(var(--chart-2))" fill="hsl(var(--chart-2) / 0.2)" name="Покупок" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="sources" className="space-y-4">
          <div className="flex justify-end">
            <Button onClick={() => setSourceDialogOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Добавить источник
            </Button>
          </div>
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Название</TableHead>
                  <TableHead>Slug (ID диплинка)</TableHead>
                  <TableHead>Платформа</TableHead>
                  <TableHead>Переходы</TableHead>
                  <TableHead>Новых</TableHead>
                  <TableHead>Купили</TableHead>
                  <TableHead>Выручка (₽)</TableHead>
                  <TableHead>CR%</TableHead>
                  <TableHead>Диплинк</TableHead>
                  <TableHead className="w-[180px]">Действия</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sourcesStats.length === 0 && sourcesList?.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={10} className="text-center text-muted-foreground">
                      Нет источников. Добавьте источник и размещайте ссылку t.me/{botUsername || 'BOT'}?start=src_&lt;slug&gt;
                    </TableCell>
                  </TableRow>
                ) : (
                  (sourcesList ?? []).map((s) => {
                    const stat = sourcesStats.find((st) => st.slug === s.slug)
                    return (
                      <TableRow key={s.id}>
                        <TableCell>{s.name}</TableCell>
                        <TableCell className="font-mono">
                          <span title="Этот slug — ID в диплинке: start=src_...">{s.slug}</span>
                        </TableCell>
                        <TableCell>{PLATFORMS.find((p) => p.value === s.platform)?.label ?? s.platform}</TableCell>
                        <TableCell>{formatNumber(stat?.clicks ?? 0)}</TableCell>
                        <TableCell>{formatNumber(stat?.new_users ?? 0)}</TableCell>
                        <TableCell>{formatNumber(stat?.buyers ?? 0)}</TableCell>
                        <TableCell>{formatNumber(stat?.revenue_rub ?? 0)}</TableCell>
                        <TableCell>{stat?.conversion_rate_pct ?? 0}%</TableCell>
                        <TableCell className="max-w-[300px]">
                          <div className="flex flex-col gap-1.5">
                            <div className="text-xs text-muted-foreground">
                              Параметр: <code className="font-mono bg-muted px-1 rounded">src_{s.slug}</code>
                            </div>
                            {getLinkUrl(s.slug) ? (
                              <>
                                <span className="text-xs font-mono break-all select-text cursor-text border rounded px-1.5 py-0.5 bg-muted/50" title="Выделите и Ctrl+C">
                                  {getLinkUrl(s.slug)}
                                </span>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => copyLink(s.slug)}
                                  className="gap-1 w-fit"
                                >
                                  {copySuccess === s.slug ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                                  {copySuccess === s.slug ? 'Скопировано' : 'Копировать ссылку'}
                                </Button>
                              </>
                            ) : (
                              <span className="text-xs text-muted-foreground">
                                t.me/&lt;bot&gt;?start=src_{s.slug} — задайте telegram_bot_username в настройках
                              </span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1">
                            <Button variant="ghost" size="sm" onClick={() => setSelectedSlug(s.slug)}>
                              Детали
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setEditingSource(s)}
                              title="Редактировать"
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setSourceToDelete(s)}
                              title="Удалить"
                              className="text-destructive hover:text-destructive"
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })
                )}
              </TableBody>
            </Table>
          </Card>
        </TabsContent>

        <TabsContent value="campaigns" className="space-y-4">
          <div className="flex justify-end">
            <Button onClick={() => setCampaignDialogOpen(true)} disabled={!sourcesList?.length}>
              <Plus className="h-4 w-4 mr-2" />
              Новая кампания
            </Button>
          </div>
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Название</TableHead>
                  <TableHead>Источник</TableHead>
                  <TableHead>Бюджет (₽)</TableHead>
                  <TableHead>Период</TableHead>
                  <TableHead>Новых</TableHead>
                  <TableHead>CPA (₽)</TableHead>
                  <TableHead>Покупок</TableHead>
                  <TableHead>CPP (₽)</TableHead>
                  <TableHead>ROAS</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {campaigns.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={9} className="text-center text-muted-foreground">
                      Нет кампаний. Создайте кампанию и укажите бюджет для расчёта CPA/ROAS.
                    </TableCell>
                  </TableRow>
                ) : (
                  campaigns.map((c) => {
                    const roi = roiMap[c.id]
                    const roasVal = roi?.roas ?? null
                    return (
                      <TableRow key={c.id}>
                        <TableCell>{c.name}</TableCell>
                        <TableCell>{c.source?.name ?? c.source_id}</TableCell>
                        <TableCell>{formatNumber(c.budget_rub)}</TableCell>
                        <TableCell>
                          {c.date_from && c.date_to
                            ? `${format(new Date(c.date_from), 'd.MM.yy', { locale: ru })} – ${format(new Date(c.date_to), 'd.MM.yy', { locale: ru })}`
                            : '—'}
                        </TableCell>
                        <TableCell>{roi ? formatNumber(roi.new_users) : '—'}</TableCell>
                        <TableCell>{roi?.cpa_rub != null ? formatNumber(roi.cpa_rub) : '—'}</TableCell>
                        <TableCell>{roi ? formatNumber(roi.buyers) : '—'}</TableCell>
                        <TableCell>{roi?.cpp_rub != null ? formatNumber(roi.cpp_rub) : '—'}</TableCell>
                        <TableCell>
                          {roasVal != null ? (
                            <span
                              className={
                                roasVal >= 1
                                  ? 'text-green-600 dark:text-green-400 font-medium'
                                  : 'text-red-600 dark:text-red-400 font-medium'
                              }
                            >
                              {roasVal.toFixed(2)}x
                            </span>
                          ) : (
                            '—'
                          )}
                        </TableCell>
                      </TableRow>
                    )
                  })
                )}
              </TableBody>
            </Table>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={sourceDialogOpen} onOpenChange={setSourceDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Добавить источник трафика</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label>Название</Label>
              <Input
                value={newSource.name}
                onChange={(e) => setNewSource((p) => ({ ...p, name: e.target.value }))}
                placeholder="Паблик Красота ВК"
              />
            </div>
            <div className="grid gap-2">
              <Label>Slug (латиница, _, -)</Label>
              <Input
                value={newSource.slug}
                onChange={(e) => setNewSource((p) => ({ ...p, slug: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '') }))}
                placeholder="vk_beauty"
              />
            </div>
            <div className="grid gap-2">
              <Label>Платформа</Label>
              <Select
                value={newSource.platform}
                onValueChange={(v) => setNewSource((p) => ({ ...p, platform: v }))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PLATFORMS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label>URL канала/паблика (необязательно)</Label>
              <Input
                value={newSource.url}
                onChange={(e) => setNewSource((p) => ({ ...p, url: e.target.value }))}
                placeholder="https://..."
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setSourceDialogOpen(false)}
            >
              Отмена
            </Button>
            <Button
              onClick={() =>
                createSourceMutation.mutate({
                  slug: newSource.slug,
                  name: newSource.name || newSource.slug,
                  url: newSource.url || undefined,
                  platform: newSource.platform,
                })
              }
              disabled={!newSource.slug}
            >
              Создать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!editingSource} onOpenChange={(open) => !open && setEditingSource(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Редактировать источник</DialogTitle>
          </DialogHeader>
          {editingSource && (
            <div className="grid gap-4 py-4">
              <div className="grid gap-2">
                <Label>Slug (не изменяется)</Label>
                <Input value={editingSource.slug} readOnly disabled className="font-mono bg-muted" />
              </div>
              <div className="grid gap-2">
                <Label>Название</Label>
                <Input
                  value={editSourceForm.name}
                  onChange={(e) => setEditSourceForm((p) => ({ ...p, name: e.target.value }))}
                  placeholder="Название источника"
                />
              </div>
              <div className="grid gap-2">
                <Label>URL канала/паблика (необязательно)</Label>
                <Input
                  value={editSourceForm.url}
                  onChange={(e) => setEditSourceForm((p) => ({ ...p, url: e.target.value }))}
                  placeholder="https://..."
                />
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="edit-source-active"
                  checked={editSourceForm.is_active}
                  onChange={(e) => setEditSourceForm((p) => ({ ...p, is_active: e.target.checked }))}
                  className="rounded border-input"
                />
                <Label htmlFor="edit-source-active">Источник активен</Label>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingSource(null)}>
              Отмена
            </Button>
            <Button
              disabled={!editingSource}
              onClick={() => {
                if (!editingSource) return
                updateSourceMutation.mutate({
                  id: editingSource.id,
                  body: {
                    name: editSourceForm.name || editingSource.slug,
                    url: editSourceForm.url || undefined,
                    is_active: editSourceForm.is_active,
                  },
                })
              }}
            >
              Сохранить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!sourceToDelete} onOpenChange={(open) => !open && setSourceToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Удалить источник?</DialogTitle>
          </DialogHeader>
          {sourceToDelete && (
            <p className="text-sm text-muted-foreground">
              Источник «{sourceToDelete.name}» (slug: <code className="font-mono">{sourceToDelete.slug}</code>) будет удалён.
              Пользователи, пришедшие по этой ссылке, останутся в системе; статистика по ним сохранится в отчётах за прошлые периоды.
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setSourceToDelete(null)}>
              Отмена
            </Button>
            <Button
              variant="destructive"
              disabled={!sourceToDelete || deleteSourceMutation.isPending}
              onClick={() => sourceToDelete && deleteSourceMutation.mutate(sourceToDelete.id)}
            >
              Удалить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={campaignDialogOpen} onOpenChange={setCampaignDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Новая кампания</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label>Название</Label>
              <Input
                value={newCampaign.name}
                onChange={(e) => setNewCampaign((p) => ({ ...p, name: e.target.value }))}
                placeholder="Март Красота"
              />
            </div>
            <div className="grid gap-2">
              <Label>Источник</Label>
              <Select
                value={newCampaign.source_id}
                onValueChange={(v) => setNewCampaign((p) => ({ ...p, source_id: v }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Выберите источник" />
                </SelectTrigger>
                <SelectContent>
                  {(sourcesList ?? []).map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name} ({s.slug})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label>Бюджет (руб.)</Label>
              <Input
                type="number"
                min={0}
                value={newCampaign.budget_rub || ''}
                onChange={(e) =>
                  setNewCampaign((p) => ({ ...p, budget_rub: parseFloat(e.target.value) || 0 }))
                }
                placeholder="10000"
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="grid gap-2">
                <Label>Дата начала</Label>
                <Input
                  type="date"
                  value={newCampaign.date_from}
                  onChange={(e) => setNewCampaign((p) => ({ ...p, date_from: e.target.value }))}
                />
              </div>
              <div className="grid gap-2">
                <Label>Дата окончания</Label>
                <Input
                  type="date"
                  value={newCampaign.date_to}
                  onChange={(e) => setNewCampaign((p) => ({ ...p, date_to: e.target.value }))}
                />
              </div>
            </div>
            <div className="grid gap-2">
              <Label>Заметки (необязательно)</Label>
              <Input
                value={newCampaign.notes}
                onChange={(e) => setNewCampaign((p) => ({ ...p, notes: e.target.value }))}
                placeholder="..."
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCampaignDialogOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={() =>
                createCampaignMutation.mutate({
                  source_id: newCampaign.source_id,
                  name: newCampaign.name || 'Кампания',
                  budget_rub: newCampaign.budget_rub,
                  date_from: newCampaign.date_from,
                  date_to: newCampaign.date_to,
                  notes: newCampaign.notes || undefined,
                })
              }
              disabled={!newCampaign.source_id}
            >
              Создать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
