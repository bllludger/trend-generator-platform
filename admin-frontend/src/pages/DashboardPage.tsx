import { useQuery } from '@tanstack/react-query'
import {
  usersService,
  type UsersGrowthAllTimeResponse,
  type UsersAudienceSelectionStatsResponse,
} from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatNumber } from '@/lib/utils'
import { TrendingUp } from 'lucide-react'
import { differenceInCalendarDays, format, parseISO } from 'date-fns'
import { ru } from 'date-fns/locale'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  PieChart,
  Pie,
  Cell,
} from 'recharts'

const AUDIENCE_COLORS: Record<string, string> = {
  women: '#EC4899',
  men: '#3B82F6',
  couples: '#10B981',
  unknown: '#94A3B8',
}

export function DashboardPage() {
  const { data, isLoading, isError, dataUpdatedAt, refetch } = useQuery<UsersGrowthAllTimeResponse>({
    queryKey: ['users-growth-all-time'],
    queryFn: () => usersService.getGrowthAllTime(),
    refetchInterval: 60000,
  })
  const { data: audienceStats } = useQuery<UsersAudienceSelectionStatsResponse>({
    queryKey: ['users-audience-selection-stats'],
    queryFn: () => usersService.getAudienceSelectionStats(),
    refetchInterval: 60000,
  })

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

  const chartData = data?.series ?? []
  const lastPoint = chartData.length > 0 ? chartData[chartData.length - 1] : null
  const totalUsers = data?.total_users ?? lastPoint?.total_users ?? 0
  const startDateLabel = data?.start_date
    ? format(parseISO(data.start_date), 'd MMM yyyy', { locale: ru })
    : '—'
  const endDateLabel = data?.end_date
    ? format(parseISO(data.end_date), 'd MMM yyyy', { locale: ru })
    : '—'
  const totalDays =
    data?.start_date && data?.end_date
      ? differenceInCalendarDays(parseISO(data.end_date), parseISO(data.start_date)) + 1
      : 0
  const audienceItems = audienceStats?.items?.filter((x) => x.clicks > 0) ?? []
  const audienceTotalClicks = audienceStats?.total_clicks ?? 0

  return (
    <div className="space-y-6">
      {isError && (
        <div className="flex items-center justify-between gap-4 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          <span>Ошибка загрузки данных. Обновите страницу.</span>
          <button
            type="button"
            onClick={() => { refetch() }}
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
            Рост пользователей
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Кумулятивный график за все время (от 0 до текущего значения)
            {dataUpdatedAt && (
              <span className="ml-2 text-muted-foreground/80">
                · обновлено {format(new Date(dataUpdatedAt), 'HH:mm', { locale: ru })}
              </span>
            )}
          </p>
        </div>
        <div className="mt-2 flex items-center gap-2 sm:mt-0">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-success/10 px-3 py-1 text-xs font-medium text-success">
            <TrendingUp className="h-3.5 w-3.5" />
            All time
          </span>
        </div>
      </div>

      <Card className="overflow-hidden border-border/80">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Динамика роста пользователей</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 pt-0">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-border/70 bg-muted/20 px-3 py-2">
              <p className="text-xs uppercase tracking-wider text-muted-foreground">Всего пользователей</p>
              <p className="mt-1 text-2xl font-bold tabular-nums text-foreground">{formatNumber(totalUsers)}</p>
            </div>
            <div className="rounded-lg border border-border/70 bg-muted/20 px-3 py-2">
              <p className="text-xs uppercase tracking-wider text-muted-foreground">Период</p>
              <p className="mt-1 text-sm font-medium text-foreground">{startDateLabel} - {endDateLabel}</p>
            </div>
            <div className="rounded-lg border border-border/70 bg-muted/20 px-3 py-2">
              <p className="text-xs uppercase tracking-wider text-muted-foreground">Дней в графике</p>
              <p className="mt-1 text-2xl font-bold tabular-nums text-foreground">{formatNumber(totalDays)}</p>
            </div>
          </div>

          {chartData.length > 0 ? (
            <div className="h-[360px] w-full rounded-xl border border-border/70 bg-gradient-to-b from-primary/[0.04] to-transparent p-2">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 10, right: 12, left: 6, bottom: 0 }}>
                  <defs>
                    <linearGradient id="usersGrowthGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted/50" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={32}
                    tickFormatter={(value) =>
                      format(parseISO(value), 'd MMM', { locale: ru })
                    }
                  />
                  <YAxis
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    width={46}
                    domain={[0, (max: number) => Math.max(max + 10, 10)]}
                    tickFormatter={(value) => formatNumber(Number(value) || 0)}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'hsl(var(--card))',
                      border: '1px solid hsl(var(--border))',
                      borderRadius: '12px',
                      boxShadow: '0 8px 24px rgba(0,0,0,0.15)',
                    }}
                    labelFormatter={(value) => format(parseISO(String(value)), "d MMMM yyyy", { locale: ru })}
                    formatter={(value: unknown, name: string) => [
                      formatNumber(Number(value) || 0),
                      name === 'total_users' ? 'Всего пользователей' : 'Новых за день',
                    ]}
                  />
                  <Area
                    type="monotone"
                    dataKey="total_users"
                    stroke="hsl(var(--primary))"
                    strokeWidth={3}
                    fill="url(#usersGrowthGradient)"
                    dot={false}
                    activeDot={{ r: 5 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="flex h-[220px] items-center justify-center rounded-lg border border-dashed border-muted-foreground/30 text-sm text-muted-foreground">
              Нет данных по регистрации пользователей
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="overflow-hidden border-border/80">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Выбор перед стартом: женщины / мужчины / пары</CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {audienceItems.length > 0 ? (
            <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
              <div className="h-[280px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={audienceItems}
                      dataKey="clicks"
                      nameKey="label"
                      cx="50%"
                      cy="50%"
                      innerRadius={72}
                      outerRadius={110}
                      paddingAngle={2}
                    >
                      {audienceItems.map((entry) => (
                        <Cell key={entry.key} fill={AUDIENCE_COLORS[entry.key] ?? AUDIENCE_COLORS.unknown} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: 'hsl(var(--card))',
                        border: '1px solid hsl(var(--border))',
                        borderRadius: '12px',
                        boxShadow: '0 8px 24px rgba(0,0,0,0.15)',
                      }}
                      formatter={(value: unknown, _: string, payload: { payload?: { pct?: number } }) => [
                        `${formatNumber(Number(value) || 0)} кликов`,
                        `${payload?.payload?.pct ?? 0}%`,
                      ]}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">
                  Всего кликов по кнопкам выбора аудитории: <span className="font-semibold text-foreground">{formatNumber(audienceTotalClicks)}</span>
                </p>
                {audienceItems.map((item) => (
                  <div
                    key={item.key}
                    className="flex items-center justify-between rounded-lg border border-border/70 bg-muted/20 px-3 py-2"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="inline-block h-3 w-3 rounded-full"
                        style={{ backgroundColor: AUDIENCE_COLORS[item.key] ?? AUDIENCE_COLORS.unknown }}
                      />
                      <span className="font-medium text-foreground">{item.label}</span>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-semibold tabular-nums text-foreground">{formatNumber(item.clicks)} ({item.pct}%)</p>
                      <p className="text-xs text-muted-foreground">уникальных: {formatNumber(item.unique_users)}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex h-[200px] items-center justify-center rounded-lg border border-dashed border-muted-foreground/30 text-sm text-muted-foreground">
              Нет данных по кнопкам выбора пола
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
