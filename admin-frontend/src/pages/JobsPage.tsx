import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { jobsService, trendsService, type JobsAnalytics } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Pagination } from '@/components/Pagination'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate, formatNumber } from '@/lib/utils'
import {
  Search,
  Filter,
  Copy,
  Check,
  Briefcase,
  TrendingUp,
  AlertCircle,
  Clock,
  ListTodo,
  Radio,
  User,
  BarChart3,
} from 'lucide-react'
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { useState } from 'react'

const PERIOD_OPTIONS = [
  { value: 'all', label: 'Все время', hours: null as number | null },
  { value: '24', label: 'За 24 ч', hours: 24 },
  { value: '168', label: 'За 7 д', hours: 168 },
  { value: '720', label: 'За 30 д', hours: 720 },
]

const PAGE_SIZES = [20, 50, 100]
const LIVE_REFETCH_INTERVAL_MS = 15_000

type JobItem = {
  job_id: string
  telegram_id?: string
  user_display_name?: string
  trend_id: string
  trend_name?: string
  trend_emoji?: string
  status: string
  is_preview?: boolean
  reserved_tokens: number
  error_code?: string
  created_at: string
}

function getStatusBadge(status: string) {
  const variants: Record<string, 'info' | 'warning' | 'success' | 'error' | 'default'> = {
    CREATED: 'info',
    RUNNING: 'warning',
    SUCCEEDED: 'success',
    FAILED: 'error',
    ERROR: 'error',
  }
  return variants[status] || 'default'
}

function copyToClipboard(text: string, setCopied: (id: string | null) => void) {
  navigator.clipboard.writeText(text).then(() => {
    setCopied(text)
    setTimeout(() => setCopied(null), 2000)
  })
}

export function JobsPage() {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [period, setPeriod] = useState('all')
  const [trendId, setTrendId] = useState('')
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [errorDetailJob, setErrorDetailJob] = useState<JobItem | null>(null)
  const [liveEnabled, setLiveEnabled] = useState(false)

  const hours = PERIOD_OPTIONS.find((p) => p.value === period)?.hours ?? null

  const { data, isLoading, dataUpdatedAt } = useQuery({
    queryKey: ['jobs', page, pageSize, status, search, trendId, hours],
    queryFn: () =>
      jobsService.list({
        page,
        page_size: pageSize,
        status: status || undefined,
        telegram_id: search || undefined,
        trend_id: trendId || undefined,
        hours: hours ?? undefined,
      }),
    refetchInterval: liveEnabled ? LIVE_REFETCH_INTERVAL_MS : false,
  })

  const { data: stats } = useQuery({
    queryKey: ['jobs-stats', hours],
    queryFn: () => jobsService.stats(hours ?? 24),
    enabled: hours != null,
    refetchInterval: liveEnabled ? LIVE_REFETCH_INTERVAL_MS : false,
  })

  const { data: trendsData } = useQuery({
    queryKey: ['trends-list-for-jobs'],
    queryFn: () => trendsService.list(),
  })

  const analyticsHours = hours ?? 720
  const { data: analytics } = useQuery<JobsAnalytics>({
    queryKey: ['jobs-analytics', analyticsHours, trendId, status],
    queryFn: () =>
      jobsService.getAnalytics({
        hours: analyticsHours,
        trend_id: trendId || undefined,
        status: status || undefined,
      }),
  })

  const jobsByDayChart = (analytics?.jobs_by_day ?? []).map((d) => ({
    date: d.date ? d.date.slice(0, 10) : '',
    count: d.count,
  }))
  const byStatusChart = Object.entries(analytics?.by_status ?? {}).map(([name, count]) => ({
    name,
    count,
  }))

  const handleStatusChange = (value: string) => {
    setStatus(value === 'all' ? '' : value)
    setPage(1)
  }

  const total = data?.total ?? 0
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)
  const items = (data?.items ?? []) as JobItem[]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Задачи</h1>
        <p className="mt-2 text-muted-foreground">
          Мониторинг задач генерации изображений
        </p>
      </div>

      {hours != null && stats && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <span className="text-sm font-medium text-muted-foreground">
                Всего за период
              </span>
              <Briefcase className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatNumber(stats.total)}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <span className="text-sm font-medium text-muted-foreground">
                Успешно
              </span>
              <TrendingUp className="h-4 w-4 text-emerald-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-emerald-600">
                {formatNumber(stats.succeeded)}
              </div>
              <p className="text-xs text-muted-foreground">
                {stats.total > 0
                  ? `${Math.round((stats.succeeded / stats.total) * 100)}% от периода`
                  : '—'}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <span className="text-sm font-medium text-muted-foreground">
                Ошибки
              </span>
              <AlertCircle className="h-4 w-4 text-red-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-red-600">
                {formatNumber(stats.failed)}
              </div>
              <p className="text-xs text-muted-foreground">
                {stats.total > 0
                  ? `${Math.round((stats.failed / stats.total) * 100)}% от периода`
                  : '—'}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <span className="text-sm font-medium text-muted-foreground">
                В очереди
              </span>
              <ListTodo className="h-4 w-4 text-amber-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatNumber(stats.in_queue)}</div>
            </CardContent>
          </Card>
        </div>
      )}

      <Tabs defaultValue="journal" className="space-y-4">
        <TabsList className="grid w-full max-w-[280px] grid-cols-2">
          <TabsTrigger value="journal">Журнал</TabsTrigger>
          <TabsTrigger value="analytics">Аналитика</TabsTrigger>
        </TabsList>

        <TabsContent value="journal" className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <Select value={status || 'all'} onValueChange={handleStatusChange}>
              <SelectTrigger className="w-44">
                <Filter className="mr-2 h-4 w-4" />
                <SelectValue placeholder="Все статусы" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все статусы</SelectItem>
                <SelectItem value="CREATED">Создана</SelectItem>
                <SelectItem value="RUNNING">Выполняется</SelectItem>
                <SelectItem value="SUCCEEDED">Успешно</SelectItem>
                <SelectItem value="FAILED">Ошибка</SelectItem>
                <SelectItem value="ERROR">Ошибка (ERROR)</SelectItem>
              </SelectContent>
            </Select>

            <Select value={period} onValueChange={(v) => { setPeriod(v); setPage(1) }}>
              <SelectTrigger className="w-36">
                <Clock className="mr-2 h-4 w-4" />
                <SelectValue placeholder="Период" />
              </SelectTrigger>
              <SelectContent>
                {PERIOD_OPTIONS.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Button
              type="button"
              variant={liveEnabled ? 'default' : 'outline'}
              size="sm"
              className="gap-1.5"
              onClick={() => setLiveEnabled((v) => !v)}
            >
              <Radio className={`h-4 w-4 ${liveEnabled ? 'animate-pulse' : ''}`} />
              Live
            </Button>

            <Select value={trendId || 'all'} onValueChange={(v) => { setTrendId(v === 'all' ? '' : v); setPage(1) }}>
              <SelectTrigger className="w-48">
                <SelectValue placeholder="Тренд" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все тренды</SelectItem>
                {(Array.isArray(trendsData) ? trendsData : []).map((t: { id: string; name: string; emoji?: string }) => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.emoji ? `${t.emoji} ` : ''}{t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="relative flex-1 min-w-[200px] max-w-sm">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Поиск по Telegram ID..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && setPage(1)}
                className="pl-8"
              />
            </div>

            <Select
              value={String(pageSize)}
              onValueChange={(v) => { setPageSize(Number(v)); setPage(1) }}
            >
              <SelectTrigger className="w-24">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PAGE_SIZES.map((n) => (
                  <SelectItem key={n} value={String(n)}>{n}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : !items.length ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <Briefcase className="h-12 w-12 text-muted-foreground/50" />
              <p className="mt-2 font-medium text-foreground">Нет задач</p>
              <p className="text-sm text-muted-foreground">
                Измените фильтры или период
              </p>
            </div>
          ) : (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span>Показано {formatNumber(from)}–{formatNumber(to)} из {formatNumber(total)}</span>
                <span>Время в вашей таймзоне</span>
                {liveEnabled && dataUpdatedAt > 0 && (
                  <span>Обновлено: {new Date(dataUpdatedAt).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                )}
              </div>
              <div className="overflow-x-auto rounded-lg border border-border">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="w-10"> </TableHead>
                      <TableHead className="font-mono">ID</TableHead>
                      <TableHead>Пользователь</TableHead>
                      <TableHead>Тренд</TableHead>
                      <TableHead>Статус</TableHead>
                      <TableHead>Токены</TableHead>
                      <TableHead>Ошибка</TableHead>
                      <TableHead title="Время в вашей таймзоне">Создана</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((job) => (
                      <TableRow key={job.job_id} className="hover:bg-muted/40">
                        <TableCell className="w-10">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => copyToClipboard(job.job_id, setCopiedId)}
                            title="Копировать ID"
                          >
                            {copiedId === job.job_id ? (
                              <Check className="h-4 w-4 text-emerald-600" />
                            ) : (
                              <Copy className="h-4 w-4" />
                            )}
                          </Button>
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {job.job_id.substring(0, 8)}…
                        </TableCell>
                        <TableCell>
                          {job.user_display_name ? (
                            <div>
                              <span className="font-medium">{job.user_display_name}</span>
                              {job.telegram_id && (
                                <div className="text-xs text-muted-foreground font-mono">{job.telegram_id}</div>
                              )}
                            </div>
                          ) : (
                            <span className="font-mono">{job.telegram_id || '—'}</span>
                          )}
                        </TableCell>
                        <TableCell>
                          <Link
                            to="/trends"
                            className="text-primary hover:underline"
                            title={job.trend_name ?? job.trend_id}
                          >
                            {job.trend_emoji ? `${job.trend_emoji} ` : ''}
                            {job.trend_name || job.trend_id.substring(0, 8)}
                          </Link>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <Badge variant={getStatusBadge(job.status)}>
                              {job.status}
                            </Badge>
                            {job.is_preview && (
                              <Badge variant="secondary" className="font-normal">
                                Превью
                              </Badge>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>{job.reserved_tokens}</TableCell>
                        <TableCell className="text-muted-foreground">
                          {job.error_code ? (
                            <Button
                              variant="link"
                              className="h-auto p-0 text-red-600 hover:text-red-700"
                              onClick={() => setErrorDetailJob(job)}
                            >
                              {job.error_code}
                            </Button>
                          ) : (
                            '—'
                          )}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm">
                          {formatDate(job.created_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              <Pagination
                currentPage={page}
                totalPages={data?.pages ?? 1}
                onPageChange={setPage}
              />
            </>
          )}
        </CardContent>
      </Card>
        </TabsContent>

        <TabsContent value="analytics" className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5" />
                  Задачи по дням
                </CardTitle>
                <CardDescription>Количество задач за период</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-[280px]">
                  {jobsByDayChart.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={jobsByDayChart}>
                        <defs>
                          <linearGradient id="jobsByDayGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.8} />
                            <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.1} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                        <XAxis dataKey="date" tick={{ fontSize: 11 }} className="text-muted-foreground" />
                        <YAxis tick={{ fontSize: 11 }} className="text-muted-foreground" />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: 'hsl(var(--background))',
                            border: '1px solid hsl(var(--border))',
                            borderRadius: '8px',
                          }}
                          formatter={(value: number) => [value, 'Задач']}
                          labelFormatter={(label) => (label ? `Дата: ${label}` : '')}
                        />
                        <Area
                          type="monotone"
                          dataKey="count"
                          stroke="#3b82f6"
                          fill="url(#jobsByDayGrad)"
                          name="Задач"
                          strokeWidth={2}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="flex h-full items-center justify-center text-muted-foreground">Нет данных за период</div>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BarChart3 className="h-5 w-5" />
                  По статусам
                </CardTitle>
                <CardDescription>Разбивка по статусу задачи</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-[280px]">
                  {byStatusChart.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={byStatusChart} margin={{ left: 4, right: 16 }}>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                        <XAxis dataKey="name" tick={{ fontSize: 10 }} className="text-muted-foreground" />
                        <YAxis tick={{ fontSize: 11 }} className="text-muted-foreground" />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: 'hsl(var(--background))',
                            border: '1px solid hsl(var(--border))',
                            borderRadius: '8px',
                          }}
                          formatter={(value: number) => [value, 'Задач']}
                        />
                        <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} name="Задач" />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="flex h-full items-center justify-center text-muted-foreground">Нет данных за период</div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <TrendingUp className="h-5 w-5" />
                Топ трендов по задачам
              </CardTitle>
              <CardDescription>До 20 трендов с наибольшим числом задач</CardDescription>
            </CardHeader>
            <CardContent>
              {(analytics?.by_trend?.length ?? 0) > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12">#</TableHead>
                      <TableHead>Тренд</TableHead>
                      <TableHead className="text-right w-24">Задач</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {analytics!.by_trend.map((t, i) => (
                      <TableRow key={t.trend_id}>
                        <TableCell className="text-muted-foreground text-sm">{i + 1}</TableCell>
                        <TableCell>
                          {t.trend_emoji ? `${t.trend_emoji} ` : ''}{t.trend_name || t.trend_id}
                        </TableCell>
                        <TableCell className="text-right">{t.count}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <p className="py-8 text-center text-muted-foreground">Нет данных за период</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <User className="h-5 w-5" />
                Топ пользователей по задачам
              </CardTitle>
              <CardDescription>До 20 пользователей с наибольшим числом задач за период</CardDescription>
            </CardHeader>
            <CardContent>
              {(analytics?.top_users?.length ?? 0) > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12">#</TableHead>
                      <TableHead>Пользователь</TableHead>
                      <TableHead className="font-mono text-xs w-24">Telegram ID</TableHead>
                      <TableHead className="text-right w-24">Задач</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {analytics!.top_users.map((u, i) => (
                      <TableRow key={u.user_id}>
                        <TableCell className="text-muted-foreground text-sm">{i + 1}</TableCell>
                        <TableCell className="font-medium">{u.user_display_name || u.telegram_id || u.user_id}</TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">{u.telegram_id ?? '—'}</TableCell>
                        <TableCell className="text-right">{u.count}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <p className="py-8 text-center text-muted-foreground">Нет данных за период</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={!!errorDetailJob} onOpenChange={() => setErrorDetailJob(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Детали ошибки</DialogTitle>
          </DialogHeader>
          {errorDetailJob && (
            <div className="space-y-2 text-sm">
              <p><span className="font-medium">Job ID:</span>{' '}
                <code className="rounded bg-muted px-1">{errorDetailJob.job_id}</code>
              </p>
              <p><span className="font-medium">Код:</span> {errorDetailJob.error_code}</p>
              <p><span className="font-medium">Создана:</span> {formatDate(errorDetailJob.created_at)}</p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => copyToClipboard(errorDetailJob.job_id, () => {})}
              >
                <Copy className="mr-2 h-4 w-4" />
                Копировать ID
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
