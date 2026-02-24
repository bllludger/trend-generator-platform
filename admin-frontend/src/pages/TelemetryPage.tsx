import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { telemetryService } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { formatNumber } from '@/lib/utils'
import {
  Users,
  TrendingUp,
  Activity,
  Target,
  Zap,
  Timer,
  UserPlus,
  UserMinus,
  BarChart3,
  RefreshCw,
  AlertCircle,
  CheckCircle,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
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
  Legend,
  PieChart,
  Pie,
  Cell,
} from 'recharts'

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899']

const WINDOW_OPTIONS = [
  { hours: 6, label: '6ч' },
  { hours: 24, label: '24ч' },
  { hours: 72, label: '3д' },
  { hours: 168, label: '7д' },
] as const

type TrendAnalyticsItem = {
  trend_id: string
  name: string
  emoji: string
  jobs_window?: number
  succeeded_window?: number
  failed_window?: number
  selected_window?: number
}

type TelemetryDashboardData = {
  trend_analytics_window?: TrendAnalyticsItem[]
  jobs_total?: number
  jobs_window?: number
  jobs_by_status?: Record<string, number>
  jobs_failed_by_error?: Record<string, number>
  queue_length?: number
  users_total?: number
  users_subscribed?: number
  audit_actions_window?: Record<string, number>
}

interface MetricCardProps {
  title: string
  value: string | number
  subtitle?: string
  trend?: number
  icon: React.ElementType
  color: string
}

function MetricCard({ title, value, subtitle, trend, icon: Icon, color }: MetricCardProps) {
  const trendColor = trend && trend > 0 ? 'text-green-600' : trend && trend < 0 ? 'text-red-600' : 'text-gray-500'
  const TrendIcon = trend && trend > 0 ? ArrowUpRight : trend && trend < 0 ? ArrowDownRight : Minus
  
  return (
    <Card className="hover:shadow-lg transition-shadow">
      <CardContent className="pt-6">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <p className="text-sm font-medium text-muted-foreground">{title}</p>
            <div className="mt-2 flex items-baseline gap-2">
              <p className="text-3xl font-bold tracking-tight">{value}</p>
              {trend !== undefined && (
                <div className={`flex items-center gap-1 text-sm font-medium ${trendColor}`}>
                  <TrendIcon className="h-4 w-4" />
                  <span>{Math.abs(trend)}%</span>
                </div>
              )}
            </div>
            {subtitle && (
              <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
            )}
          </div>
          <div className={`rounded-full p-3 ${color}`}>
            <Icon className="h-5 w-5 text-white" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export function TelemetryPage() {
  const [windowHours, setWindowHours] = useState(24)

  const { data, isLoading, refetch, isFetching } = useQuery<TelemetryDashboardData>({
    queryKey: ['telemetry', windowHours],
    queryFn: () => telemetryService.getDashboard(windowHours) as Promise<TelemetryDashboardData>,
    refetchInterval: 60000,
  })

  const { data: historyData } = useQuery({
    queryKey: ['telemetry-history', 7],
    queryFn: () => telemetryService.getHistory(7),
  })

  const { data: productMetrics } = useQuery({
    queryKey: ['telemetry-product', 30],
    queryFn: () => telemetryService.getProductMetrics(30),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-muted-foreground">Загрузка аналитики...</div>
      </div>
    )
  }

  const statusData = Object.entries(data?.jobs_by_status ?? {}).map(([name, value]) => ({
    name,
    value: value as number,
  }))

  const jobsDistData = productMetrics?.jobs_per_user_distribution
    ? [
        { range: '1 job', users: productMetrics.jobs_per_user_distribution['1'] ?? 0 },
        { range: '2-5', users: productMetrics.jobs_per_user_distribution['2_5'] ?? 0 },
        { range: '6-10', users: productMetrics.jobs_per_user_distribution['6_10'] ?? 0 },
        { range: '11-20', users: productMetrics.jobs_per_user_distribution['11_20'] ?? 0 },
        { range: '21+', users: productMetrics.jobs_per_user_distribution['21_plus'] ?? 0 },
      ]
    : []

  return (
    <div className="space-y-8 pb-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold tracking-tight bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
            Аналитика продукта
          </h1>
          <p className="text-muted-foreground mt-2">
            Комплексная аналитика пользователей, вовлечённости и здоровья продукта
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border bg-background p-1 shadow-sm">
            {WINDOW_OPTIONS.map((opt) => (
              <Button
                key={opt.hours}
                variant={windowHours === opt.hours ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setWindowHours(opt.hours)}
                className="text-xs"
              >
                {opt.label}
              </Button>
            ))}
          </div>
          <Button
            variant="outline"
            size="icon"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      <Tabs defaultValue="overview" className="space-y-6">
        <TabsList className="grid w-full grid-cols-4 lg:w-auto">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="engagement">Engagement</TabsTrigger>
          <TabsTrigger value="trends">Trends</TabsTrigger>
          <TabsTrigger value="health">Health</TabsTrigger>
        </TabsList>

        {/* OVERVIEW */}
        <TabsContent value="overview" className="space-y-6">
          {/* User Metrics */}
          <div>
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Users className="h-5 w-5" />
              Пользовательские метрики
            </h2>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              <MetricCard
                title="DAU"
                value={productMetrics?.dau ?? 0}
                subtitle="Активные за 24ч"
                icon={Users}
                color="bg-blue-500"
              />
              <MetricCard
                title="WAU"
                value={productMetrics?.wau ?? 0}
                subtitle="Активные за неделю"
                icon={Activity}
                color="bg-green-500"
              />
              <MetricCard
                title="MAU"
                value={productMetrics?.mau ?? 0}
                subtitle="Активные за месяц"
                icon={Target}
                color="bg-purple-500"
              />
              <MetricCard
                title="Stickiness"
                value={`${productMetrics?.stickiness_pct ?? 0}%`}
                subtitle="DAU/MAU ratio"
                icon={Zap}
                color="bg-amber-500"
              />
            </div>
          </div>

          {/* Jobs & Performance */}
          <div>
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <BarChart3 className="h-5 w-5" />
              Производительность
            </h2>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
              <MetricCard
                title="Всего задач"
                value={formatNumber(data?.jobs_total ?? 0)}
                subtitle="За всё время"
                icon={BarChart3}
                color="bg-indigo-500"
              />
              <MetricCard
                title={`За ${windowHours}ч`}
                value={formatNumber(data?.jobs_window ?? 0)}
                subtitle="Новых задач"
                icon={Clock}
                color="bg-cyan-500"
              />
              <MetricCard
                title="Успешно"
                value={formatNumber(data?.jobs_by_status?.SUCCEEDED ?? 0)}
                subtitle={`${data?.jobs_window ? Math.round(((data.jobs_by_status?.SUCCEEDED ?? 0) / data.jobs_window) * 100) : 0}% success rate`}
                icon={CheckCircle}
                color="bg-emerald-500"
              />
              <MetricCard
                title="Ошибки"
                value={formatNumber(data?.jobs_by_status?.FAILED ?? 0)}
                subtitle={`${data?.jobs_window ? Math.round(((data.jobs_by_status?.FAILED ?? 0) / data.jobs_window) * 100) : 0}% error rate`}
                icon={AlertCircle}
                color="bg-red-500"
              />
              <MetricCard
                title="В очереди"
                value={data?.queue_length ?? 0}
                subtitle="Celery queue"
                icon={Clock}
                color="bg-orange-500"
              />
            </div>
          </div>

          {/* Charts */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Historical trend */}
            {historyData && historyData.history.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <TrendingUp className="h-5 w-5" />
                    Динамика (7 дней)
                  </CardTitle>
                  <CardDescription>Задачи и активные пользователи</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="h-[280px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={historyData.history}>
                        <defs>
                          <linearGradient id="colorTotal" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.8} />
                            <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.1} />
                          </linearGradient>
                          <linearGradient id="colorSuccess" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#10b981" stopOpacity={0.8} />
                            <stop offset="95%" stopColor="#10b981" stopOpacity={0.1} />
                          </linearGradient>
                          <linearGradient id="colorUsers" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.8} />
                            <stop offset="95%" stopColor="#f59e0b" stopOpacity={0.1} />
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
                        />
                        <Legend wrapperStyle={{ fontSize: '12px' }} />
                        <Area
                          type="monotone"
                          dataKey="jobs_total"
                          stroke="#3b82f6"
                          fill="url(#colorTotal)"
                          name="Задач"
                          strokeWidth={2}
                        />
                        <Area
                          type="monotone"
                          dataKey="jobs_succeeded"
                          stroke="#10b981"
                          fill="url(#colorSuccess)"
                          name="Успешно"
                          strokeWidth={2}
                        />
                        <Area
                          type="monotone"
                          dataKey="active_users"
                          stroke="#f59e0b"
                          fill="url(#colorUsers)"
                          name="Активные пользователи"
                          strokeWidth={2}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Status distribution */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Activity className="h-5 w-5" />
                  Распределение статусов
                </CardTitle>
                <CardDescription>Все задачи по статусам</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-[280px] flex items-center justify-center">
                  {statusData.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={statusData}
                          cx="50%"
                          cy="50%"
                          labelLine={false}
                          label={(entry: { name: string; value: number }) => `${entry.name} (${entry.value})`}
                          outerRadius={90}
                          fill="#8884d8"
                          dataKey="value"
                        >
                          {statusData.map((_entry, index) => (
                            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip />
                      </PieChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="text-muted-foreground">Нет данных</p>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ENGAGEMENT */}
        <TabsContent value="engagement" className="space-y-6">
          <div>
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Target className="h-5 w-5" />
              Retention & Growth
            </h2>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              <MetricCard
                title="Retention D1"
                value={`${productMetrics?.retention_d1_pct ?? 0}%`}
                subtitle={`${productMetrics?.retained_d1 ?? 0} пользователей`}
                icon={Target}
                color="bg-emerald-500"
              />
              <MetricCard
                title="Retention 7д"
                value={`${productMetrics?.retention_weekly_pct ?? 0}%`}
                subtitle={`${productMetrics?.retained_weekly ?? 0} вернулись`}
                icon={TrendingUp}
                color="bg-blue-500"
              />
              <MetricCard
                title="Новые пользователи"
                value={productMetrics?.new_users_7d ?? 0}
                subtitle={`7д · 30д: ${productMetrics?.new_users_30d ?? 0}`}
                icon={UserPlus}
                color="bg-green-500"
              />
              <MetricCard
                title="Отток"
                value={productMetrics?.churned_users ?? 0}
                subtitle="Не вернулись за неделю"
                icon={UserMinus}
                color="bg-red-500"
              />
            </div>
          </div>

          <div>
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Activity className="h-5 w-5" />
              User Behavior
            </h2>
            <div className="grid gap-4 md:grid-cols-3">
              <MetricCard
                title="Время в продукте"
                value={productMetrics?.avg_session_str ?? '0 сек'}
                subtitle="Средняя сессия"
                icon={Timer}
                color="bg-cyan-500"
              />
              <MetricCard
                title="Jobs на активного"
                value={productMetrics?.avg_jobs_per_active ?? 0}
                subtitle="За неделю (WAU)"
                icon={BarChart3}
                color="bg-purple-500"
              />
              <MetricCard
                title="LTV"
                value={`${productMetrics?.ltv_jobs ?? 0} jobs`}
                subtitle="Средний lifetime value"
                icon={TrendingUp}
                color="bg-indigo-500"
              />
            </div>
          </div>

          {/* User distribution */}
          <Card>
            <CardHeader>
              <CardTitle>Распределение активности пользователей</CardTitle>
              <CardDescription>
                Сколько генераций делают пользователи (всего {formatNumber(jobsDistData.reduce((sum: number, d: { users: number }) => sum + d.users, 0))} юзеров)
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="h-[300px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={jobsDistData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                    <XAxis type="number" tick={{ fontSize: 12 }} />
                    <YAxis type="category" dataKey="range" width={60} tick={{ fontSize: 12 }} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: 'hsl(var(--background))',
                        border: '1px solid hsl(var(--border))',
                        borderRadius: '8px',
                      }}
                    />
                    <Bar dataKey="users" fill="#8b5cf6" name="Пользователей" radius={[0, 8, 8, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TRENDS */}
        <TabsContent value="trends" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Популярность трендов ({windowHours}ч)</CardTitle>
              <CardDescription>Активность по каждому тренду</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {(data?.trend_analytics_window ?? []).map((trend: TrendAnalyticsItem) => {
                  const total = trend.jobs_window ?? 0
                  const succeeded = trend.succeeded_window ?? 0
                  const successRate = total > 0 ? ((succeeded / total) * 100).toFixed(1) : '0'
                  return (
                    <div
                      key={trend.trend_id}
                      className="flex items-center justify-between p-4 rounded-lg border bg-card hover:shadow-md transition-shadow"
                    >
                      <div className="flex items-center gap-4">
                        <span className="text-4xl">{trend.emoji}</span>
                        <div>
                          <div className="font-semibold text-lg">{trend.name}</div>
                          <div className="flex items-center gap-3 mt-1">
                            <Badge variant="secondary" className="text-xs">
                              {trend.jobs_window} задач
                            </Badge>
                            <Badge variant="outline" className="text-xs">
                              {trend.selected_window ?? 0} выборов
                            </Badge>
                            <span className="text-xs text-muted-foreground">
                              Success: {successRate}%
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="flex items-center gap-2">
                          <div className="text-2xl font-bold text-green-600">
                            {trend.succeeded_window}
                          </div>
                          <CheckCircle className="h-5 w-5 text-green-600" />
                        </div>
                        {(trend.failed_window ?? 0) > 0 && (
                          <div className="flex items-center gap-2 justify-end mt-1">
                            <div className="text-sm text-red-600">{trend.failed_window ?? 0}</div>
                            <AlertCircle className="h-4 w-4 text-red-600" />
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
                {(data?.trend_analytics_window ?? []).length === 0 && (
                  <p className="text-center text-muted-foreground py-8">
                    Нет данных по трендам за выбранный период
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* HEALTH */}
        <TabsContent value="health" className="space-y-6">
          <div className="grid gap-6 md:grid-cols-2">
            {/* Errors */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <AlertCircle className="h-5 w-5 text-red-600" />
                  Ошибки ({windowHours}ч)
                </CardTitle>
                <CardDescription>
                  Топ ошибок за период
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2 max-h-[300px] overflow-y-auto">
                  {Object.entries(data?.jobs_failed_by_error ?? {})
                    .sort((a, b) => (b[1] as number) - (a[1] as number))
                    .slice(0, 10)
                    .map(([code, count]) => (
                      <div
                        key={code}
                        className="flex items-center justify-between p-3 rounded-lg border bg-card"
                      >
                        <span className="font-mono text-sm text-muted-foreground truncate flex-1">
                          {code}
                        </span>
                        <Badge variant="destructive">{formatNumber(count as number)}</Badge>
                      </div>
                    ))}
                  {Object.keys(data?.jobs_failed_by_error ?? {}).length === 0 && (
                    <p className="text-center text-muted-foreground py-8">
                      Нет ошибок за выбранный период 🎉
                    </p>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* System metrics */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Activity className="h-5 w-5" />
                  Системные метрики
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-3">
                  <div className="flex justify-between items-center p-3 rounded-lg bg-muted/50">
                    <span className="text-sm font-medium">Всего пользователей</span>
                    <span className="text-xl font-bold">{formatNumber(data?.users_total ?? 0)}</span>
                  </div>
                  <div className="flex justify-between items-center p-3 rounded-lg bg-muted/50">
                    <span className="text-sm font-medium">Активные подписки</span>
                    <span className="text-xl font-bold text-green-600">
                      {formatNumber(data?.users_subscribed ?? 0)}
                    </span>
                  </div>
                  <div className="flex justify-between items-center p-3 rounded-lg bg-muted/50">
                    <span className="text-sm font-medium">Очередь Celery</span>
                    <span className="text-xl font-bold">{data?.queue_length ?? 0}</span>
                  </div>
                </div>

                {/* Audit actions */}
                <div className="pt-4 border-t">
                  <h4 className="text-sm font-semibold mb-3">Действия в аудите ({windowHours}ч)</h4>
                  <div className="space-y-2 max-h-[150px] overflow-y-auto">
                    {Object.entries(data?.audit_actions_window ?? {})
                      .sort((a, b) => (b[1] as number) - (a[1] as number))
                      .slice(0, 5)
                      .map(([action, count]) => (
                        <div key={action} className="flex justify-between text-sm">
                          <span className="text-muted-foreground truncate">{action}</span>
                          <span className="font-medium">{formatNumber(count as number)}</span>
                        </div>
                      ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
