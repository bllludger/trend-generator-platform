import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { usersService, packsService } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Pagination } from '@/components/Pagination'
import { formatDateShort, formatNumber } from '@/lib/utils'
import {
  Search,
  Download,
  Users,
  Crown,
  BarChart3,
  Activity,
  Zap,
  Clock,
  Shield,
  UserCircle,
} from 'lucide-react'
import { useState, useEffect } from 'react'
import {
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'

const PAGE_SIZE = 20
const SEARCH_DEBOUNCE_MS = 400

/** Debounced value for search input */
function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

function MetricCard({
  title,
  value,
  icon: Icon,
  subtitle,
  variant = 'default',
}: {
  title: string
  value: string | number
  icon: React.ComponentType<{ className?: string }>
  subtitle?: string
  variant?: 'default' | 'success' | 'warning' | 'info'
}) {
  const styles = {
    default: 'bg-sky-500/10',
    success: 'bg-success/10',
    warning: 'bg-warning/10',
    info: 'bg-violet-500/10',
  }
  return (
    <Card className="overflow-hidden border-border/80 transition-shadow hover:shadow-md">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              {title}
            </p>
            <p className="mt-1 text-2xl font-bold tabular-nums tracking-tight text-foreground">
              {typeof value === 'number' ? formatNumber(value) : value}
            </p>
            {subtitle && (
              <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
            )}
          </div>
          <div
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${styles[variant]}`}
          >
            <Icon className="h-5 w-5 text-foreground/70" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function TableRowSkeleton({ cols = 10 }: { cols?: number }) {
  return (
    <TableRow className="animate-pulse">
      {Array.from({ length: cols }).map((_, i) => (
        <TableCell key={i} className="py-4">
          <div className="h-4 rounded bg-muted" />
        </TableCell>
      ))}
    </TableRow>
  )
}

/** Export current page users to CSV */
function exportUsersToCsv(items: any[]) {
  const headers = [
    'telegram_id',
    'username',
    'first_name',
    'last_name',
    'token_balance',
    'jobs_count',
    'jobs_succeeded',
    'jobs_failed',
    'created_at',
  ]
  const rows = items.map((u) =>
    [
      u.telegram_id,
      u.telegram_username ?? '',
      u.telegram_first_name ?? '',
      u.telegram_last_name ?? '',
      u.token_balance ?? 0,
      u.jobs_count ?? 0,
      u.succeeded ?? 0,
      u.failed ?? 0,
      u.created_at,
    ].join(',')
  )
  const csv = [headers.join(','), ...rows].join('\n')
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `users_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

const SORT_OPTIONS = [
  { value: 'created_at', label: 'По дате создания' },
  { value: 'token_balance', label: 'По токенам' },
  { value: 'telegram_id', label: 'По Telegram ID' },
  { value: 'payments_count', label: 'По кол-ву платежей' },
  { value: 'jobs_count', label: 'По кол-ву задач' },
] as const

export function UsersPage() {
  const [page, setPage] = useState(1)
  const [searchInput, setSearchInput] = useState('')
  const [trialFilter, setTrialFilter] = useState<'all' | 'yes' | 'no'>('all')
  const [packIdFilter, setPackIdFilter] = useState('')
  const [paymentsCountMin, setPaymentsCountMin] = useState('')
  const [sortBy, setSortBy] = useState<string>('created_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [timeWindow, setTimeWindow] = useState<number>(30)

  const search = useDebounced(searchInput.trim(), SEARCH_DEBOUNCE_MS)

  useEffect(() => {
    setPage(1)
  }, [search, trialFilter, packIdFilter, paymentsCountMin, sortBy, sortOrder])

  const listParams = {
    page,
    page_size: PAGE_SIZE,
    telegram_id: search || undefined,
    trial_purchased:
      trialFilter === 'all' ? undefined : trialFilter === 'yes',
    pack_id: packIdFilter.trim() || undefined,
    payments_count_min: (() => {
      const n = parseInt(paymentsCountMin.trim(), 10)
      return paymentsCountMin.trim() === '' || isNaN(n) ? undefined : n
    })(),
    sort_by: sortBy,
    sort_order: sortOrder,
  }

  const { data, isLoading } = useQuery({
    queryKey: ['users', listParams],
    queryFn: () => usersService.list(listParams),
  })

  const { data: packsList = [] } = useQuery({
    queryKey: ['packs'],
    queryFn: () => packsService.list(),
  })

  const { data: analytics, isError: analyticsError } = useQuery({
    queryKey: ['users-analytics', timeWindow],
    queryFn: () => usersService.getAnalytics(String(timeWindow)),
  })

  const handleExport = () => {
    if (data?.items?.length) exportUsersToCsv(data.items)
  }

  const CHART_COLORS = [
    'hsl(var(--primary))',
    '#10b981',
    '#f59e0b',
    '#ef4444',
    '#8b5cf6',
    '#ec4899',
  ]
  const activitySegmentsRaw = analytics?.activity_segments || []
  const totalUsersForPct = analytics?.overview?.total_users ?? 0
  const activityData = activitySegmentsRaw.map((s: any) => ({
    name: s.segment,
    users: s.users,
    pct: totalUsersForPct ? Math.round((s.users / totalUsersForPct) * 100) : 0,
  }))
  const tokenDistData =
    analytics?.token_distribution?.map((t: any) => ({
      name: t.range,
      count: t.count,
      pct: totalUsersForPct ? Math.round((t.count / totalUsersForPct) * 100) : 0,
    })) || []
  const growthData = analytics?.growth ?? []
  const cohortData = analytics?.cohorts || []

  const total = data?.total ?? 0
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = Math.min(page * PAGE_SIZE, total)

  return (
    <div className="space-y-8">
      {/* Hero */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
            Пользователи
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Управление пользователями, аналитика и сегменты
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Период:</span>
          <select
            value={timeWindow}
            onChange={(e) => setTimeWindow(Number(e.target.value))}
            className="h-9 rounded-lg border border-input bg-background px-3 py-1 text-sm font-medium shadow-sm transition-colors hover:bg-muted/50"
          >
            <option value={7}>7 дней</option>
            <option value={30}>30 дней</option>
            <option value={90}>90 дней</option>
          </select>
          <Button variant="outline" size="sm" asChild>
            <Link to="/security">
              <Shield className="mr-2 h-4 w-4" />
              Security
            </Link>
          </Button>
        </div>
      </div>

      <Tabs defaultValue="overview" className="space-y-6">
        <TabsList className="inline-flex h-10 rounded-lg border border-border bg-muted/50 p-1">
          <TabsTrigger
            value="overview"
            className="rounded-md px-4 data-[state=active]:bg-background data-[state=active]:shadow-sm"
          >
            Обзор
          </TabsTrigger>
          <TabsTrigger
            value="segments"
            className="rounded-md px-4 data-[state=active]:bg-background data-[state=active]:shadow-sm"
          >
            Сегменты
          </TabsTrigger>
          <TabsTrigger
            value="list"
            className="rounded-md px-4 data-[state=active]:bg-background data-[state=active]:shadow-sm"
          >
            Список
          </TabsTrigger>
        </TabsList>

        {/* Overview */}
        <TabsContent value="overview" className="space-y-6">
          <p className="text-sm text-muted-foreground">
            Сводка за последние <strong>{timeWindow}</strong> дней. Данные обновляются по запросу.
          </p>
          {analyticsError && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              Ошибка загрузки аналитики. Обновите страницу.
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              title="Всего пользователей"
              value={analytics?.overview?.total_users ?? 0}
              icon={Users}
              subtitle="В системе"
              variant="default"
            />
            <MetricCard
              title="Активные подписки"
              value={analytics?.overview?.active_subscribers ?? 0}
              icon={Crown}
              subtitle={`Конверсия: ${analytics?.overview?.conversion_rate ?? 0}%`}
              variant="success"
            />
            <MetricCard
              title="С активностью"
              value={analytics?.overview?.users_with_jobs ?? 0}
              icon={Activity}
              subtitle={`за ${timeWindow} д. (задачи/снимки)`}
              variant="info"
            />
            <MetricCard
              title="Среднее задач/юзер"
              value={analytics?.overview?.avg_jobs_per_user ?? 0}
              icon={BarChart3}
              subtitle="Среди активных"
              variant="warning"
            />
          </div>

          <Card className="overflow-hidden border-border/80 shadow-sm">
            <CardHeader>
              <CardTitle className="text-base">Рост пользователей</CardTitle>
              <p className="text-sm text-muted-foreground">
                Новые регистрации по дням за {timeWindow} д.
              </p>
            </CardHeader>
            <CardContent>
              {growthData.length > 0 ? (
                <div className="h-[280px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={growthData}>
                      <defs>
                        <linearGradient id="colorGrowth" x1="0" y1="0" x2="0" y2="1">
                          <stop
                            offset="5%"
                            stopColor="hsl(var(--primary))"
                            stopOpacity={0.3}
                          />
                          <stop
                            offset="95%"
                            stopColor="hsl(var(--primary))"
                            stopOpacity={0}
                          />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-muted/50" vertical={false} />
                      <XAxis
                        dataKey="date"
                        tick={{ fontSize: 11 }}
                        tickFormatter={(val) =>
                          new Date(val).toLocaleDateString('ru-RU', {
                            month: 'short',
                            day: 'numeric',
                          })
                        }
                      />
                      <YAxis tick={{ fontSize: 11 }} width={32} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: 'hsl(var(--card))',
                          border: '1px solid hsl(var(--border))',
                          borderRadius: 'var(--radius)',
                          boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
                        }}
                        labelFormatter={(v) => new Date(v).toLocaleDateString('ru-RU', { dateStyle: 'medium' })}
                        formatter={(value: unknown) => [formatNumber(Number(value) || 0), 'Новые']}
                      />
                      <Area
                        type="monotone"
                        dataKey="new_users"
                        stroke="hsl(var(--primary))"
                        strokeWidth={2}
                        fill="url(#colorGrowth)"
                        name="Новые"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="flex h-[200px] items-center justify-center text-sm text-muted-foreground">
                  Нет данных
                </div>
              )}
            </CardContent>
          </Card>

          {cohortData.length > 0 && (
            <Card className="overflow-hidden border-border/80 shadow-sm">
              <CardHeader>
                <CardTitle className="text-base">Когорты по месяцам</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Новые регистрации по месяцам (последние 12 мес.)
                </p>
              </CardHeader>
              <CardContent>
                <div className="h-[240px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={cohortData}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-muted/50" vertical={false} />
                      <XAxis
                        dataKey="month"
                        tick={{ fontSize: 11 }}
                        tickFormatter={(val) =>
                          new Date(val).toLocaleDateString('ru-RU', {
                            month: 'short',
                            year: '2-digit',
                          })
                        }
                      />
                      <YAxis tick={{ fontSize: 11 }} width={32} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: 'hsl(var(--card))',
                          border: '1px solid hsl(var(--border))',
                          borderRadius: 'var(--radius)',
                        }}
                      />
                      <Bar
                        dataKey="count"
                        fill="hsl(var(--primary))"
                        radius={[4, 4, 0, 0]}
                        name="Регистраций"
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Zap className="h-4 w-4 text-warning" />
                Топ пользователей за {timeWindow} д.
              </CardTitle>
            </CardHeader>
            <CardContent>
              {analytics?.top_users?.length ? (
                <ul className="space-y-2">
                  {analytics.top_users.slice(0, 5).map((user: any, idx: number) => (
                    <li
                      key={user.telegram_id ?? idx}
                      className="flex items-center justify-between rounded-lg border border-border-muted bg-muted/30 px-3 py-3 transition-colors hover:bg-muted/50"
                    >
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">
                          {idx + 1}
                        </div>
                        <div className="min-w-0">
                          <p className="truncate font-medium text-foreground">
                            {user.user_display_name ?? user.telegram_id ?? '—'}
                          </p>
                          {user.telegram_id && (user.user_display_name !== user.telegram_id) && (
                            <p className="font-mono text-xs text-muted-foreground">{user.telegram_id}</p>
                          )}
                          <p className="text-xs text-muted-foreground">
                            {user.jobs_count} задач · {user.succeeded} успешно
                            {(user.failed ?? 0) > 0 && (
                              <span className="text-destructive"> · {user.failed} ошибок</span>
                            )}
                          </p>
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <Badge variant="outline" className="text-xs">
                          {user.token_balance ?? 0} токенов
                        </Badge>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  Нет данных за период
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Segments */}
        <TabsContent value="segments" className="space-y-6">
          <p className="text-sm text-muted-foreground">
            Сегментация за <strong>{timeWindow}</strong> дней. Активность — по числу задач/снимков в периоде; токены — текущий баланс.
          </p>
          {analyticsError && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              Ошибка загрузки аналитики. Обновите страницу.
            </div>
          )}
          <div className="grid gap-6 md:grid-cols-2">
            <Card className="overflow-hidden border-border/80 shadow-sm">
              <CardHeader>
                <CardTitle className="text-base">Сегменты по активности</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Распределение по количеству задач за {timeWindow} д.
                </p>
              </CardHeader>
              <CardContent>
                {activityData.length > 0 ? (
                  <>
                    <div className="h-[260px] w-full">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={activityData}
                            cx="50%"
                            cy="50%"
                            labelLine={false}
                            label={({ name, pct }: any) =>
                              pct > 0 ? `${name} (${pct}%)` : ''
                            }
                            outerRadius={90}
                            dataKey="users"
                          >
                            {activityData.map((_: any, index: number) => (
                              <Cell
                                key={`cell-${index}`}
                                fill={CHART_COLORS[index % CHART_COLORS.length]}
                              />
                            ))}
                          </Pie>
                          <Tooltip
                            contentStyle={{
                              backgroundColor: 'hsl(var(--card))',
                              border: '1px solid hsl(var(--border))',
                              borderRadius: 'var(--radius)',
                              boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
                            }}
                            formatter={(value: unknown, _: unknown, props: any) => [
                              `${formatNumber(Number(value) || 0)} чел. (${props.payload?.pct ?? 0}%)`,
                              props.payload?.name ?? '',
                            ]}
                          />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="mt-4 space-y-2 rounded-lg bg-muted/30 p-3">
                      {activityData.map((segment: any, idx: number) => (
                        <div
                          key={segment.name}
                          className="flex items-center justify-between text-sm"
                        >
                          <div className="flex items-center gap-2">
                            <div
                              className="h-3 w-3 shrink-0 rounded-full"
                              style={{
                                backgroundColor: CHART_COLORS[idx % CHART_COLORS.length],
                              }}
                            />
                            <span>{segment.name}</span>
                          </div>
                          <span className="font-medium tabular-nums">
                            {formatNumber(Number(segment.users) || 0)} чел. · {segment.pct}%
                          </span>
                        </div>
                      ))}
                      <div className="border-t border-border/60 pt-2 mt-2 text-xs text-muted-foreground">
                        Итого: {formatNumber(activityData.reduce((s: number, x: any) => s + (Number(x.users) || 0), 0))} пользователей
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="flex h-[260px] items-center justify-center text-sm text-muted-foreground">
                    Нет данных
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="overflow-hidden border-border/80 shadow-sm">
              <CardHeader>
                <CardTitle className="text-base">Распределение токенов</CardTitle>
                <p className="text-sm text-muted-foreground">
                  По текущему балансу токенов на момент запроса
                </p>
              </CardHeader>
              <CardContent>
                {tokenDistData.length > 0 ? (
                  <div className="h-[260px] w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={tokenDistData}
                        layout="vertical"
                        margin={{ left: 8, right: 16 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" className="stroke-muted/50" vertical={false} />
                        <XAxis type="number" tick={{ fontSize: 11 }} />
                        <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={64} />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: 'hsl(var(--card))',
                            border: '1px solid hsl(var(--border))',
                            borderRadius: 'var(--radius)',
                            boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
                          }}
                          formatter={(value: unknown, _: unknown, props: any) => [
                            `${formatNumber(Number(value) || 0)} чел. (${props.payload?.pct ?? 0}%)`,
                            'Пользователей',
                          ]}
                        />
                        <Bar
                          dataKey="count"
                          fill="hsl(var(--primary))"
                          radius={[0, 4, 4, 0]}
                          name="Пользователей"
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div className="flex h-[260px] items-center justify-center text-sm text-muted-foreground">
                    Нет данных
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* List */}
        <TabsContent value="list" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="relative w-full min-w-[200px] max-w-xs">
                    <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      placeholder="Поиск по Telegram ID..."
                      value={searchInput}
                      onChange={(e) => setSearchInput(e.target.value)}
                      className="pl-9"
                    />
                  </div>
                  <select
                    value={trialFilter}
                    onChange={(e) => setTrialFilter(e.target.value as 'all' | 'yes' | 'no')}
                    className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm"
                  >
                    <option value="all">Пробный: все</option>
                    <option value="yes">Пробный куплен</option>
                    <option value="no">Без пробного</option>
                  </select>
                  <select
                    value={packIdFilter}
                    onChange={(e) => setPackIdFilter(e.target.value)}
                    className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm min-w-[140px]"
                  >
                    <option value="">Пакет: все</option>
                    {(packsList as { id: string; name?: string }[]).map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name ?? p.id}
                      </option>
                    ))}
                  </select>
                  <Input
                    type="number"
                    min={0}
                    placeholder="Платежей ≥"
                    value={paymentsCountMin}
                    onChange={(e) => setPaymentsCountMin(e.target.value)}
                    className="h-9 w-24"
                  />
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value)}
                    className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm"
                  >
                    {SORT_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                  <select
                    value={sortOrder}
                    onChange={(e) => setSortOrder(e.target.value as 'asc' | 'desc')}
                    className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm"
                  >
                    <option value="desc">↓ Сначала новые / больше</option>
                    <option value="asc">↑ Сначала старые / меньше</option>
                  </select>
                </div>
                <Button variant="outline" size="sm" onClick={handleExport} disabled={!data?.items?.length}>
                  <Download className="mr-2 h-4 w-4" />
                  Экспорт CSV
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>ID</TableHead>
                      <TableHead>Ник / Имя</TableHead>
                      <TableHead>Баланс</TableHead>
                      <TableHead>Задач</TableHead>
                      <TableHead>Активность</TableHead>
                      <TableHead>Создан</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {Array.from({ length: 8 }).map((_, i) => (
                      <TableRowSkeleton key={i} cols={14} />
                    ))}
                  </TableBody>
                </Table>
              ) : !data?.items?.length ? (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <UserCircle className="h-12 w-12 text-muted-foreground/50" />
                  <p className="mt-2 font-medium text-foreground">Нет пользователей</p>
                  <p className="text-sm text-muted-foreground">
                    Измените фильтры или поиск
                  </p>
                </div>
              ) : (
                <>
                  <p className="mb-3 text-xs text-muted-foreground">
                    Показано {from}–{to} из {formatNumber(total)}
                  </p>
                  <div className="overflow-x-auto rounded-lg border border-border">
                    <Table>
                      <TableHeader>
                        <TableRow className="hover:bg-transparent">
                          <TableHead className="whitespace-nowrap">Telegram ID</TableHead>
                          <TableHead className="whitespace-nowrap">Ник / Имя</TableHead>
                          <TableHead className="whitespace-nowrap">Текущий пакет</TableHead>
                          <TableHead className="whitespace-nowrap">Осталось фото</TableHead>
                          <TableHead className="whitespace-nowrap">Пробный</TableHead>
                          <TableHead className="whitespace-nowrap">Беспл. фото</TableHead>
                          <TableHead className="whitespace-nowrap">Платежей</TableHead>
                          <TableHead className="whitespace-nowrap">Токены</TableHead>
                          <TableHead className="whitespace-nowrap">Беспл.</TableHead>
                          <TableHead className="whitespace-nowrap">Копия</TableHead>
                          <TableHead className="whitespace-nowrap">Задач</TableHead>
                          <TableHead className="whitespace-nowrap">Успех / Ошибок</TableHead>
                          <TableHead className="whitespace-nowrap">Последняя активность</TableHead>
                          <TableHead className="whitespace-nowrap">Создан</TableHead>
                          <TableHead className="whitespace-nowrap text-right">Действия</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {data.items.map((user: any) => {
                          const daysSinceActive = user.last_active
                            ? Math.floor(
                                (Date.now() - new Date(user.last_active).getTime()) /
                                  (1000 * 60 * 60 * 24)
                              )
                            : null
                          return (
                            <TableRow
                              key={user.id}
                              className="transition-colors hover:bg-muted/40"
                            >
                              <TableCell className="font-mono text-sm">
                                {user.telegram_id}
                              </TableCell>
                              <TableCell>
                                {user.telegram_username ? (
                                  <span className="font-medium">@{user.telegram_username}</span>
                                ) : [user.telegram_first_name, user.telegram_last_name].filter(Boolean).length > 0 ? (
                                  <span className="text-muted-foreground">
                                    {[user.telegram_first_name, user.telegram_last_name]
                                      .filter(Boolean)
                                      .join(' ')}
                                  </span>
                                ) : (
                                  <span className="text-muted-foreground">—</span>
                                )}
                              </TableCell>
                              <TableCell className="text-xs">
                                {user.active_session?.pack_id === 'free_preview' ? 'Бесплатный' : (user.active_session?.pack_name ?? '—')}
                              </TableCell>
                              <TableCell className="tabular-nums text-xs">
                                {user.active_session?.takes_remaining != null
                                  ? String(user.active_session.takes_remaining)
                                  : '—'}
                              </TableCell>
                              <TableCell className="text-xs">
                                {user.trial_purchased ? 'Да' : 'Нет'}
                              </TableCell>
                              <TableCell className="text-xs">
                                {typeof user.free_takes_used === 'number'
                                  ? user.free_takes_used >= 1
                                    ? 'исчерпано'
                                    : `${user.free_takes_used}/1`
                                  : '—'}
                              </TableCell>
                              <TableCell className="tabular-nums text-xs">
                                {user.payments_count ?? 0}
                              </TableCell>
                              <TableCell>
                                <Badge variant="outline" className="font-mono text-xs">
                                  {user.token_balance ?? 0}
                                </Badge>
                              </TableCell>
                              <TableCell className="text-xs text-muted-foreground">
                                {user.free_generations_limit != null
                                  ? `${user.free_generations_used ?? 0} / ${user.free_generations_limit}`
                                  : '—'}
                              </TableCell>
                              <TableCell className="text-xs text-muted-foreground">
                                {user.copy_generations_limit != null
                                  ? `${user.copy_generations_used ?? 0} / ${user.copy_generations_limit}`
                                  : '—'}
                              </TableCell>
                              <TableCell className="font-medium tabular-nums">
                                {user.jobs_count ?? 0}
                              </TableCell>
                              <TableCell className="tabular-nums">
                                <span className="text-success">
                                  {user.succeeded ?? 0}
                                </span>
                                <span className="text-muted-foreground"> / </span>
                                <span className="text-destructive">
                                  {user.failed ?? 0}
                                </span>
                              </TableCell>
                              <TableCell className="text-xs text-muted-foreground">
                                {user.last_active ? (
                                  <span className="flex items-center gap-1">
                                    <Clock className="h-3 w-3" />
                                    {daysSinceActive === 0
                                      ? 'Сегодня'
                                      : `${daysSinceActive} д. назад`}
                                  </span>
                                ) : (
                                  '—'
                                )}
                              </TableCell>
                              <TableCell className="text-xs text-muted-foreground">
                                {formatDateShort(user.created_at)}
                              </TableCell>
                              <TableCell className="text-right">
                                <Button variant="ghost" size="sm" asChild>
                                  <Link to={`/users/${user.id}`}>Открыть</Link>
                                </Button>
                              </TableCell>
                            </TableRow>
                          )
                        })}
                      </TableBody>
                    </Table>
                  </div>
                  {data.pages > 1 && (
                    <Pagination
                      currentPage={page}
                      totalPages={data.pages}
                      onPageChange={setPage}
                    />
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
