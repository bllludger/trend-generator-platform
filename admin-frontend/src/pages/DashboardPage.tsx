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
    gradient: 'from-success to-green-600',
    bgLight: 'bg-success/10',
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
    gradient: 'from-warning to-orange-600',
    bgLight: 'bg-warning/10',
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
  SUCCEEDED: 'bg-success/10 text-success',
  FAILED: 'bg-destructive/10 text-destructive',
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
  takes_window?: number
  queue_length?: number
  succeeded?: number
  jobs_by_status?: Record<string, number>
  trend_analytics_window?: TrendAnalyticsItem[]
  variants_chosen_by_trend?: Record<string, number>
}

const DASHBOARD_HISTORY_DAYS = 30
const DASHBOARD_STATS_HOURS = 24

export function DashboardPage() {
  const { data, isLoading, isError: mainError, dataUpdatedAt, refetch: refetchMain } = useQuery<DashboardData>({
    queryKey: ['telemetry', DASHBOARD_STATS_HOURS],
    queryFn: () => telemetryService.getDashboard(DASHBOARD_STATS_HOURS) as Promise<DashboardData>,
    refetchInterval: 30000,
  })

  const { data: dataWindow, isError: windowError, isLoading: windowLoading, refetch: refetchWindow } = useQuery<DashboardData>({
    queryKey: ['telemetry', DASHBOARD_HISTORY_DAYS * 24],
    queryFn: () => telemetryService.getDashboard(DASHBOARD_HISTORY_DAYS * 24) as Promise<DashboardData>,
    refetchInterval: 60000,
  })

  const { data: historyData, isError: historyError, isLoading: historyLoading, refetch: refetchHistory } = useQuery({
    queryKey: ['telemetry-history', DASHBOARD_HISTORY_DAYS],
    queryFn: () =>
      telemetryService.getHistory(DASHBOARD_HISTORY_DAYS) as Promise<{
        history?: Array<{
          date: string
          jobs_total?: number
          jobs_succeeded?: number
          jobs_failed?: number
          takes_total?: number
        }>
      }>,
    refetchInterval: 60000,
  })

  const jobsByStatus24h = data?.jobs_by_status ?? {}
  const jobsByStatus30d = dataWindow?.jobs_by_status ?? {}
  const succeededCount24h = jobsByStatus24h.SUCCEEDED ?? 0
  const jobsWindow = (data?.jobs_window as number | undefined) ?? 0
  const takesWindow = (data?.takes_window as number | undefined) ?? 0
  const statsWithValues = STAT_CARDS.map((card) => ({
    ...card,
    value:
      card.key === 'succeeded'
        ? succeededCount24h
        : card.key === 'jobs_window'
          ? jobsWindow + takesWindow
          : (data?.[card.key] as number | undefined) ?? 0,
  }))
  const hasDashboardError = mainError || windowError || historyError
  const chartData =
    historyData?.history?.map(
      (d: {
        date: string
        jobs_total?: number
        jobs_succeeded?: number
        jobs_failed?: number
        takes_total?: number
      }) => {
        const jobs = d.jobs_total ?? 0
        const takes = d.takes_total ?? 0
        return {
          date: d.date,
          dateShort: format(parseISO(d.date), 'd MMM', { locale: ru }),
          jobs: jobs + takes,
          jobsOnly: jobs,
          takesOnly: takes,
          succeeded: d.jobs_succeeded,
          failed: d.jobs_failed,
        }
      }
    ) ?? []

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
      {hasDashboardError && (
        <div className="flex items-center justify-between gap-4 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          <span>Ошибка загрузки данных. Обновите страницу.</span>
          <button
            type="button"
            onClick={() => { refetchMain(); refetchWindow(); refetchHistory() }}
            className="shrink-0 rounded-md border border-red-300 bg-white px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50 dark:border-red-700 dark:bg-red-900/50 dark:text-red-200 dark:hover:bg-red-900/70"
          >
            Обновить
          </button>
        </div>
      )}
      {/* Hero */}
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
            Панель управления
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Статистика: 24 ч — сводка, 30 д — график и тренды
            {dataUpdatedAt && (
              <span className="ml-2 text-muted-foreground/80">
                · обновлено {format(new Date(dataUpdatedAt), 'HH:mm', { locale: ru })}
              </span>
            )}
          </p>
        </div>
        <div className="mt-2 flex items-center gap-2 sm:mt-0">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-success/10 px-3 py-1 text-xs font-medium text-success">
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
              Задачи за 30 дней
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            {historyLoading && !historyData ? (
              <div className="flex h-[200px] items-center justify-center rounded-lg border border-dashed border-muted-foreground/20 text-sm text-muted-foreground">
                Загрузка…
              </div>
            ) : chartData.length > 0 ? (
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
                            <p>Всего: {payload[0].value}</p>
                            {(Number(payload[0].payload.jobsOnly) > 0 || Number(payload[0].payload.takesOnly) > 0) && (
                              <p className="text-muted-foreground text-xs">
                                задач: {payload[0].payload.jobsOnly} · снимков: {payload[0].payload.takesOnly}
                              </p>
                            )}
                            <p className="text-success">Успешно: {payload[0].payload.succeeded ?? 0}</p>
                            {Number(payload[0].payload.failed ?? 0) > 0 && (
                              <p className="text-destructive">Ошибок: {payload[0].payload.failed ?? 0}</p>
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
            ) : historyError ? (
              <div className="flex h-[200px] items-center justify-center rounded-lg border border-dashed border-red-200 bg-red-50/50 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/20 dark:text-red-300">
                Ошибка загрузки графика
              </div>
            ) : (
              <div className="flex h-[200px] items-center justify-center rounded-lg border border-dashed border-muted-foreground/20 text-sm text-muted-foreground">
                Нет данных за период
              </div>
            )}
          </CardContent>
        </Card>

        {/* Status badges — только данные за 30 д */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Статусы задач (30 д)</CardTitle>
          </CardHeader>
          <CardContent>
            {windowError ? (
              <p className="text-sm text-destructive">Ошибка загрузки</p>
            ) : windowLoading && dataWindow == null ? (
              <p className="text-sm text-muted-foreground">Загрузка…</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {Object.entries(jobsByStatus30d).map(([status, count]) => (
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
                {((dataWindow?.takes_window as number) ?? 0) > 0 && (
                  <div className="rounded-lg px-3 py-2 bg-muted/80 text-muted-foreground">
                    <span className="text-xs font-medium">Снимков</span>
                    <span className="ml-2 text-lg font-bold tabular-nums">
                      {formatNumber((dataWindow?.takes_window as number) ?? 0)}
                    </span>
                  </div>
                )}
                {Object.keys(jobsByStatus30d).length === 0 && ((dataWindow?.takes_window as number) ?? 0) === 0 && (
                  <p className="text-sm text-muted-foreground">Нет данных</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <p className="text-center text-sm text-muted-foreground">
        <Link to="/trends-analytics" className="text-primary hover:underline inline-flex items-center gap-1">
          <BarChart3 className="h-4 w-4" />
          Аналитика по трендам
        </Link>
      </p>
    </div>
  )
}
