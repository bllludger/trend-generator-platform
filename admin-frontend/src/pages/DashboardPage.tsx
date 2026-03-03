import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { telemetryService } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatNumber } from '@/lib/utils'
import {
  Users,
  UserCheck,
  Briefcase,
  Clock,
  ListTodo,
  TrendingUp,
  ArrowRight,
  Activity,
  BarChart3,
  Sparkles,
} from 'lucide-react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { format, parseISO } from 'date-fns'
import { ru } from 'date-fns/locale'

const STAT_CARDS = [
  {
    name: 'Пользователей',
    key: 'users_total' as const,
    icon: Users,
    href: '/users',
    gradient: 'from-sky-500 to-blue-600',
    bgLight: 'bg-sky-500/10',
  },
  {
    name: 'С подпиской',
    key: 'users_subscribed' as const,
    icon: UserCheck,
    href: '/users',
    gradient: 'from-emerald-500 to-green-600',
    bgLight: 'bg-emerald-500/10',
  },
  {
    name: 'Всего задач',
    key: 'jobs_total' as const,
    icon: Briefcase,
    href: '/jobs',
    gradient: 'from-violet-500 to-purple-600',
    bgLight: 'bg-violet-500/10',
  },
  {
    name: 'За 24 ч',
    key: 'jobs_window' as const,
    icon: Clock,
    href: '/jobs',
    gradient: 'from-amber-500 to-orange-600',
    bgLight: 'bg-amber-500/10',
  },
  {
    name: 'В очереди',
    key: 'queue_length' as const,
    icon: ListTodo,
    href: '/jobs',
    gradient: 'from-rose-500 to-pink-600',
    bgLight: 'bg-rose-500/10',
  },
  {
    name: 'Успешных',
    key: 'succeeded' as const,
    icon: TrendingUp,
    href: '/jobs',
    gradient: 'from-teal-500 to-cyan-600',
    bgLight: 'bg-teal-500/10',
  },
] as const

const STATUS_LABELS: Record<string, string> = {
  CREATED: 'Создано',
  RUNNING: 'В работе',
  SUCCEEDED: 'Успешно',
  FAILED: 'Ошибка',
  ERROR: 'Ошибка',
}
const STATUS_COLORS: Record<string, string> = {
  CREATED: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  RUNNING: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  SUCCEEDED: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  FAILED: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
}

type TrendAnalyticsItem = {
  trend_id: string
  name: string
  emoji: string
  jobs_window?: number
  succeeded_window?: number
  failed_window?: number
  takes_window?: number
  takes_succeeded_window?: number
  takes_failed_window?: number
  chosen_window?: number
}

type DashboardData = {
  users_total?: number
  users_subscribed?: number
  jobs_total?: number
  jobs_window?: number
  queue_length?: number
  succeeded?: number
  jobs_by_status?: Record<string, number>
  trend_analytics_window?: TrendAnalyticsItem[]
  variants_chosen_by_trend?: Record<string, number>
}

const DASHBOARD_HISTORY_DAYS = 14
const DASHBOARD_STATS_HOURS = 24

export function DashboardPage() {
  const { data, isLoading, dataUpdatedAt } = useQuery<DashboardData>({
    queryKey: ['telemetry', DASHBOARD_STATS_HOURS],
    queryFn: () => telemetryService.getDashboard(DASHBOARD_STATS_HOURS) as Promise<DashboardData>,
    refetchInterval: 30000,
  })

  const { data: data14d } = useQuery<DashboardData>({
    queryKey: ['telemetry', DASHBOARD_HISTORY_DAYS * 24],
    queryFn: () => telemetryService.getDashboard(DASHBOARD_HISTORY_DAYS * 24) as Promise<DashboardData>,
    refetchInterval: 60000,
  })

  const { data: historyData } = useQuery({
    queryKey: ['telemetry-history', DASHBOARD_HISTORY_DAYS],
    queryFn: () => telemetryService.getHistory(DASHBOARD_HISTORY_DAYS) as Promise<{ history?: Array<{ date: string; jobs_total?: number; jobs_succeeded?: number; jobs_failed?: number }> }>,
    refetchInterval: 60000,
  })

  const jobsByStatus = data14d?.jobs_by_status ?? data?.jobs_by_status ?? {}
  const succeededCount = jobsByStatus.SUCCEEDED ?? 0
  const statsWithValues = STAT_CARDS.map((card) => ({
    ...card,
    value:
      card.key === 'succeeded'
        ? succeededCount
        : (data?.[card.key] as number | undefined) ?? 0,
  }))
  const trendList = (data14d?.trend_analytics_window ?? data?.trend_analytics_window ?? [])
    .filter(
      (t) =>
        (t.jobs_window ?? 0) > 0 ||
        (t.takes_window ?? 0) > 0 ||
        (t.chosen_window ?? 0) > 0
    )
    .slice(0, 10)
  const chartData =
    historyData?.history?.map((d: { date: string; jobs_total?: number; jobs_succeeded?: number; jobs_failed?: number }) => ({
      date: d.date,
      dateShort: format(parseISO(d.date), 'd MMM', { locale: ru }),
      jobs: d.jobs_total,
      succeeded: d.jobs_succeeded,
      failed: d.jobs_failed,
    })) ?? []

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">Загрузка панели...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Hero */}
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
            Панель управления
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Статистика: 24 ч — сводка, 14 д — график и тренды
            {dataUpdatedAt && (
              <span className="ml-2 text-muted-foreground/80">
                · обновлено {format(new Date(dataUpdatedAt), 'HH:mm', { locale: ru })}
              </span>
            )}
          </p>
        </div>
        <div className="mt-2 flex items-center gap-2 sm:mt-0">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-400">
            <Activity className="h-3.5 w-3.5" />
            Live
          </span>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {statsWithValues.map((stat) => (
          <Link key={stat.name} to={stat.href} className="group block">
            <Card className="h-full overflow-hidden border-border/80 transition-colors hover:border-primary/30 hover:shadow-md">
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {stat.name}
                    </p>
                    <p className="mt-1 text-2xl font-bold tabular-nums tracking-tight text-foreground">
                      {formatNumber(stat.value)}
                    </p>
                  </div>
                  <div
                    className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${stat.bgLight}`}
                  >
                    <stat.icon className="h-5 w-5 text-foreground/70" />
                  </div>
                </div>
                <div className="mt-3 flex items-center text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                  <span>Перейти</span>
                  <ArrowRight className="ml-1 h-3.5 w-3.5" />
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {/* Chart + Two columns */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Mini chart */}
        <Card className="lg:col-span-2 overflow-hidden">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <BarChart3 className="h-4 w-4 text-muted-foreground" />
              Задачи за 14 дней
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            {chartData.length > 0 ? (
              <div className="h-[200px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id="jobsGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.3} />
                        <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-muted/50" vertical={false} />
                    <XAxis
                      dataKey="dateShort"
                      tick={{ fontSize: 11 }}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={28} />
                    <Tooltip
                      content={({ active, payload }) =>
                        active && payload?.[0] ? (
                          <div className="rounded-lg border bg-card px-3 py-2 text-sm shadow-sm">
                            <p className="font-medium">{payload[0].payload.date}</p>
                            <p>Задач: {payload[0].value}</p>
                            <p className="text-emerald-600">Успешно: {payload[0].payload.succeeded}</p>
                            {Number(payload[0].payload.failed) > 0 && (
                              <p className="text-red-600">Ошибок: {payload[0].payload.failed}</p>
                            )}
                          </div>
                        ) : null
                      }
                    />
                    <Area
                      type="monotone"
                      dataKey="jobs"
                      stroke="hsl(var(--primary))"
                      strokeWidth={2}
                      fill="url(#jobsGradient)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="flex h-[200px] items-center justify-center rounded-lg border border-dashed border-muted-foreground/20 text-sm text-muted-foreground">
                Нет данных за период
              </div>
            )}
          </CardContent>
        </Card>

        {/* Status badges */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Статусы задач (14 д)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {Object.entries(jobsByStatus).map(([status, count]) => (
                <div
                  key={status}
                  className={`rounded-lg px-3 py-2 ${STATUS_COLORS[status] ?? 'bg-muted text-muted-foreground'}`}
                >
                  <span className="text-xs font-medium">
                    {STATUS_LABELS[status] ?? status}
                  </span>
                  <span className="ml-2 text-lg font-bold tabular-nums">
                    {formatNumber(Number(count))}
                  </span>
                </div>
              ))}
              {Object.keys(jobsByStatus).length === 0 && (
                <p className="text-sm text-muted-foreground">Нет данных</p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Top trends */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4 text-muted-foreground" />
            Топ трендов за 14 д
          </CardTitle>
        </CardHeader>
        <CardContent>
          {trendList.length > 0 ? (
            <ul className="space-y-3">
              {trendList.map((trend: TrendAnalyticsItem) => {
                const jobs = trend.jobs_window ?? 0
                const takes = trend.takes_window ?? 0
                const total = jobs + takes
                const succeeded =
                  (trend.succeeded_window ?? 0) + (trend.takes_succeeded_window ?? 0)
                const failed = (trend.failed_window ?? 0) + (trend.takes_failed_window ?? 0)
                const successRate = total > 0 ? Math.round((succeeded / total) * 100) : 0
                const parts: string[] = []
                if (jobs > 0) parts.push(`${jobs} задач`)
                if (takes > 0) parts.push(`${takes} снимков`)
                if ((trend.chosen_window ?? 0) > 0)
                  parts.push(`${trend.chosen_window} выбрано картинок`)
                const subtitle = parts.length > 0 ? parts.join(' · ') : '—'
                return (
                  <li
                    key={trend.trend_id}
                    className="flex items-center justify-between gap-4 rounded-lg border border-border/60 bg-muted/30 px-3 py-2.5 transition-colors hover:bg-muted/50"
                  >
                    <div className="flex min-w-0 flex-1 items-center gap-3">
                      <span className="text-xl leading-none">{trend.emoji}</span>
                      <div className="min-w-0">
                        <p className="truncate font-medium text-foreground">{trend.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {subtitle}
                          {' · '}
                          {successRate}% успешность
                        </p>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <div className="h-2 w-16 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-emerald-500"
                          style={{ width: `${successRate}%` }}
                        />
                      </div>
                      <div
                        className="text-right"
                        title="Успешных / с ошибками за период"
                      >
                        <span className="text-sm font-semibold text-emerald-600 dark:text-emerald-400">
                          +{succeeded}
                        </span>
                        {failed > 0 && (
                          <span className="ml-1 text-xs text-red-600 dark:text-red-400">
                            −{failed}
                          </span>
                        )}
                      </div>
                    </div>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Пока нет активности по трендам
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
