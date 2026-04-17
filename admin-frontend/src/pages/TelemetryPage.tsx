import { useQuery } from '@tanstack/react-query'
import { telemetryService } from '@/services/api'
import { TelemetryOverviewV3 } from '@/components/telemetry/TelemetryOverviewV3'
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
  BarChart3,
  RefreshCw,
  AlertCircle,
  CheckCircle,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  ListOrdered,
  GitBranch,
} from 'lucide-react'
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  LineChart,
  Line,
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
  selected_window?: number
}

type TelemetryDashboardData = {
  trend_analytics_window?: TrendAnalyticsItem[]
  jobs_total?: number
  jobs_window?: number
  takes_window?: number
  takes_succeeded?: number
  takes_failed?: number
  take_avg_generation_sec?: number | null
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
  const trendColor = trend && trend > 0 ? 'text-success' : trend && trend < 0 ? 'text-destructive' : 'text-muted-foreground'
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

const FUNNEL_LABELS: Record<string, string> = {
  bot_started: 'Старт',
  photo_uploaded: 'Фото загружено',
  take_preview_ready: 'Варианты готовы',
  favorite_selected: 'Выбор варианта',
  paywall_viewed: 'Просмотр оплаты',
  pack_selected: 'Выбор тарифа',
  pay_initiated: 'Нажата оплата',
  pay_success: 'Оплата успешна',
  hd_delivered: '4K доставлен',
}

const FUNNEL_ORDER: string[] = [
  'bot_started',
  'photo_uploaded',
  'take_preview_ready',
  'favorite_selected',
  'paywall_viewed',
  'pack_selected',
  'pay_initiated',
  'pay_success',
  'hd_delivered',
]

const FUNNEL_HISTORY_SERIES: string[] = [
  'bot_started',
  'photo_uploaded',
  'take_preview_ready',
  'favorite_selected',
  'pay_success',
  'hd_delivered',
]

const BUTTON_CLICK_LABELS: Record<string, string> = {
  pay_yoomoney: 'Оплатить через ЮMoney',
  pay_yoomoney_link: 'Оплатить по ссылке (ЮMoney)',
  pay_stars: 'Купить через Stars',
  pay_other: 'Другие способы оплаты',
  bank_transfer: 'Перевод на карту',
  bank_transfer_cancel: 'Отмена перевода на карту',
  bank_receipt_uploaded: 'Загрузка чека перевода',
  nav_menu: 'В меню',
  nav_themes: 'Навигация: темы',
  nav_trends: 'Навигация: тренды',
  nav_profile: 'Навигация: профиль',
  pack_trial: 'Пакет: Пробный',
  pack_neo_start: 'Пакет: Neo Start',
  pack_neo_pro: 'Пакет: Neo Pro',
  pack_neo_unlimited: 'Пакет: Neo Unlimited',
  shop_open_tariff_better: 'Открыть тариф Better',
  shop_how_buy_stars: 'Как купить Stars',
  unlock_check: 'Проверка разблокировки',
  pack_check: 'Проверка пакета',
  session_status: 'Статус сессии',
  variant_a: 'Вариант A',
  variant_b: 'Вариант B',
  variant_c: 'Вариант C',
  take_more: 'Все 3 не подходят / Ещё фото',
  open_favorites: 'Избранное',
  favorites_clear_all: 'Избранное: очистить всё',
  remove_fav: 'Избранное: удалить вариант',
  select_hd: 'Избранное: выбрать 4K',
  deselect_hd: 'Избранное: снять 4K',
  hd_problem: 'Проблема с 4K',
  unlock_resend: 'Повтор отправки unlock',
  menu_shop: 'Меню: магазин',
  menu_create_photo: 'Меню: создать фото',
  menu_copy_style: 'Меню: копировать стиль',
  menu_merge_photos: 'Меню: merge фото',
  menu_profile: 'Меню: профиль',
  profile_payment: 'Профиль: оплата',
  profile_support: 'Профиль: поддержка',
  referral_status: 'Рефералы: статус',
  referral_back_profile: 'Рефералы: назад в профиль',
  theme_selected: 'Выбор темы',
  custom_prompt_submitted: 'Своя идея: отправлен промпт',
  format_selected: 'Выбор формата',
  rescue_photo_uploaded: 'Rescue: фото загружено',
  regenerate: 'Перегенерация',
  help: 'Помощь',
  trends: 'Тренды',
  cancel: 'Отмена',
  deletemydata: 'Удалить мои данные',
  paysupport: 'Поддержка оплаты',
  terms: 'Условия',
}

const TELEMETRY_OVERVIEW_V3_ENABLED = ['1', 'true', 'yes'].includes(
  String(import.meta.env.VITE_TELEMETRY_OVERVIEW_V3 ?? '')
    .trim()
    .toLowerCase()
)
const PRODUCT_ALL_TIME = true

export function TelemetryPage() {
  const windowHours = 24
  const productWindowDays = undefined

  const { data, isLoading, refetch, isFetching } = useQuery<TelemetryDashboardData>({
    queryKey: ['telemetry', windowHours],
    queryFn: () => telemetryService.getDashboard(windowHours) as Promise<TelemetryDashboardData>,
    refetchInterval: 60000,
  })

  const historyDays = 30
  const { data: historyData, isError: historyError } = useQuery({
    queryKey: ['telemetry-history', historyDays],
    queryFn: () => telemetryService.getHistory(historyDays),
  })

  const { data: productMetrics } = useQuery({
    queryKey: ['telemetry-product', 30],
    queryFn: () => telemetryService.getProductMetrics(30),
  })

  const { data: productFunnel } = useQuery({
    queryKey: ['telemetry-product-funnel', 'all-time'],
    queryFn: () => telemetryService.getProductFunnel(productWindowDays, PRODUCT_ALL_TIME),
  })

  const {
    data: funnelHistoryData,
    isError: funnelHistoryError,
    isLoading: funnelHistoryLoading,
  } = useQuery({
    queryKey: ['telemetry-product-funnel-history', 'all-time'],
    queryFn: () => telemetryService.getProductFunnelHistory(productWindowDays, PRODUCT_ALL_TIME),
  })

  const { data: buttonClicksData, isError: buttonClicksError } = useQuery({
    queryKey: ['telemetry-button-clicks', 'all-time'],
    queryFn: () => telemetryService.getButtonClicks(productWindowDays, PRODUCT_ALL_TIME),
  })

  const { data: productMetricsV2 } = useQuery({
    queryKey: ['telemetry-product-metrics-v2', 'all-time'],
    queryFn: () => telemetryService.getProductMetricsV2(productWindowDays, PRODUCT_ALL_TIME),
  })

  const { data: revenueData } = useQuery({
    queryKey: ['telemetry-revenue', 'all-time'],
    queryFn: () => telemetryService.getRevenue(productWindowDays, PRODUCT_ALL_TIME),
  })

  const errorsWindowDays = 30
  const { data: errorsData } = useQuery({
    queryKey: ['telemetry-errors', errorsWindowDays],
    queryFn: () => telemetryService.getErrors(errorsWindowDays),
    refetchInterval: 60000,
  })

  const {
    data: pathData,
    isLoading: pathLoading,
    isError: pathError,
  } = useQuery({
    queryKey: ['telemetry-path', 'all-time', 20],
    queryFn: () => telemetryService.getPath(productWindowDays, 20, PRODUCT_ALL_TIME),
  })
  const pathTransitionsData = pathData
    ? {
        window_days: pathData.window_days,
        transitions: pathData.transitions,
        drop_off: pathData.drop_off,
        data_quality: pathData.data_quality,
        shadow: pathData.shadow,
      }
    : undefined
  const pathSequencesData = pathData
    ? {
        window_days: pathData.window_days,
        paths: pathData.paths,
        shadow: pathData.shadow,
      }
    : undefined

  if (isLoading && !TELEMETRY_OVERVIEW_V3_ENABLED) {
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

  const unknownButtonIds = new Set(
    Object.keys(buttonClicksData?.unknown_by_button_id ?? {})
  )
  const knownButtonEntries = Object.entries(buttonClicksData?.by_button_id ?? {}).filter(
    ([buttonId]) => !unknownButtonIds.has(buttonId)
  )
  const hasUnknownButtons = unknownButtonIds.size > 0
  const knownButtonRows = knownButtonEntries
    .map(([buttonId, count]) => ({
      buttonId,
      label: BUTTON_CLICK_LABELS[buttonId] ?? buttonId,
      clicks: Number(count ?? 0),
      users: Number(buttonClicksData?.by_button_id_users?.[buttonId] ?? 0),
    }))
    .sort((a, b) => b.clicks - a.clicks)
  const buttonTopRows = knownButtonRows.slice(0, 16)
  const buttonTopChartRows = knownButtonRows.slice(0, 10).map((row) => ({
    label: row.label.length > 28 ? `${row.label.slice(0, 28)}…` : row.label,
    clicks: row.clicks,
  }))
  const totalKnownClicks = knownButtonRows.reduce((acc, row) => acc + row.clicks, 0)
  const totalKnownUsersByButtons = knownButtonRows.reduce((acc, row) => acc + row.users, 0)
  const unknownClicks = Object.values(buttonClicksData?.unknown_by_button_id ?? {}).reduce(
    (acc, value) => acc + Number(value ?? 0),
    0
  )

  const funnelCounts = productFunnel?.funnel_counts ?? {}
  const funnelStepRows = FUNNEL_ORDER.map((stepKey, index) => {
    const count = Number(funnelCounts[stepKey] ?? 0)
    const prev = index > 0 ? Number(funnelCounts[FUNNEL_ORDER[index - 1]] ?? 0) : count
    const conversion = index === 0 ? 100 : prev > 0 ? Math.round((count / prev) * 100) : 0
    return {
      stepKey,
      label: FUNNEL_LABELS[stepKey] ?? stepKey,
      count,
      conversion,
    }
  })
  const funnelStartUsers = funnelStepRows[0]?.count ?? 0
  const funnelPhotoUsers = funnelStepRows.find((r) => r.stepKey === 'photo_uploaded')?.count ?? 0
  const funnelPayClicked = funnelStepRows.find((r) => r.stepKey === 'pay_initiated')?.count ?? 0
  const funnelNoPhotoUsers = Math.max(0, funnelStartUsers - funnelPhotoUsers)
  const funnelNoPhotoPct = funnelStartUsers > 0 ? Math.round((funnelNoPhotoUsers / funnelStartUsers) * 100) : 0

  return (
    <div className="space-y-8 pb-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold tracking-tight bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
            Аналитика продукта
          </h1>
          <p className="text-muted-foreground mt-2">
            Ключевые метрики и воронка за всё время
          </p>
        </div>
        {!TELEMETRY_OVERVIEW_V3_ENABLED && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              onClick={() => refetch()}
              disabled={isFetching}
            >
              <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        )}
      </div>

      <Tabs defaultValue="overview" className="space-y-6">
        <TabsList className="grid w-full grid-cols-4 lg:grid-cols-8 lg:w-auto lg:flex-wrap">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="funnel">Funnel</TabsTrigger>
          <TabsTrigger value="path">Путь</TabsTrigger>
          <TabsTrigger value="buttons">Кнопки</TabsTrigger>
          <TabsTrigger value="engagement">Engagement</TabsTrigger>
          <TabsTrigger value="trends">Trends</TabsTrigger>
          <TabsTrigger value="revenue">Revenue</TabsTrigger>
          <TabsTrigger value="health">Health</TabsTrigger>
        </TabsList>

        {/* OVERVIEW */}
        <TabsContent value="overview" className="space-y-6">
          {TELEMETRY_OVERVIEW_V3_ENABLED ? (
            <TelemetryOverviewV3 />
          ) : (
            <>
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
                color="bg-warning"
              />
              {productMetricsV2 != null && (
                <>
                  <MetricCard
                    title="Preview → Pay"
                    value={`${productMetricsV2.preview_to_pay_pct ?? 0}%`}
                    subtitle="Все время"
                    icon={Target}
                    color="bg-cyan-500"
                  />
                  <MetricCard
                    title="Paying users"
                    value={productMetricsV2.paying_users ?? 0}
                    subtitle={`Выручка: ${formatNumber(productMetricsV2.total_stars ?? 0)} ⭐`}
                    icon={Users}
                    color="bg-success"
                  />
                  <MetricCard
                    title="Среднее время до результата"
                    value={
                      (() => {
                        const sec = productMetricsV2.avg_time_start_to_result_sec
                        if (sec == null) return '—'
                        if (sec >= 86400) return `${(sec / 86400).toFixed(1)} дн.`
                        if (sec >= 3600) return `${(sec / 3600).toFixed(1)} ч`
                        if (sec >= 60) return `${(sec / 60).toFixed(1)} мин`
                        return `${Math.round(sec)} сек`
                      })()
                    }
                    subtitle="От /start до выбора варианта"
                    icon={Clock}
                    color="bg-sky-500"
                  />
                  <MetricCard
                    title="Среднее шагов до результата"
                    value={
                      productMetricsV2.avg_steps_start_to_result != null
                        ? Number(productMetricsV2.avg_steps_start_to_result) % 1 === 0
                          ? String(Math.round(productMetricsV2.avg_steps_start_to_result))
                          : productMetricsV2.avg_steps_start_to_result.toFixed(1)
                        : '—'
                    }
                    subtitle="Событий от старта до избранного"
                    icon={ListOrdered}
                    color="bg-indigo-500"
                  />
                </>
              )}
            </div>
          </div>

          {/* Charts */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Historical trend: Jobs + Takes + active users (DAU from Job и Take) */}
            {historyError ? (
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <TrendingUp className="h-5 w-5" />
                    Динамика
                  </CardTitle>
                  <CardDescription>Не удалось загрузить данные</CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-destructive">Ошибка загрузки. Обновите страницу или попробуйте позже.</p>
                </CardContent>
              </Card>
            ) : historyData?.history?.length ? (
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <TrendingUp className="h-5 w-5" />
                    Динамика ({historyData.window_days ?? 30} д.)
                  </CardTitle>
                  <CardDescription>
                    Все метрики за период: задачи (Job), снимки (Take), успешно, ошибки, активные пользователи, сред. время 3 снимков (правая ось)
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="h-[320px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={historyData.history} margin={{ top: 5, right: 50, left: 0, bottom: 5 }}>
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
                          <linearGradient id="colorTakes" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.8} />
                            <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0.1} />
                          </linearGradient>
                          <linearGradient id="colorFailed" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#ef4444" stopOpacity={0.8} />
                            <stop offset="95%" stopColor="#ef4444" stopOpacity={0.1} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                        <XAxis dataKey="date" tick={{ fontSize: 11 }} className="text-muted-foreground" />
                        <YAxis yAxisId="left" tick={{ fontSize: 11 }} className="text-muted-foreground" />
                        <YAxis
                          yAxisId="right"
                          orientation="right"
                          tick={{ fontSize: 11 }}
                          className="text-muted-foreground"
                          tickFormatter={(v) => (v >= 60 ? `${(v / 60).toFixed(0)} мин` : `${v} сек`)}
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: 'hsl(var(--background))',
                            border: '1px solid hsl(var(--border))',
                            borderRadius: '8px',
                          }}
                          formatter={(value, name) => {
                            if (name === 'Сред. время 3 снимков' && typeof value === 'number') {
                              return [value >= 60 ? `${(value / 60).toFixed(1)} мин` : `${Math.round(value)} сек`, name]
                            }
                            return [value, name]
                          }}
                        />
                        <Legend wrapperStyle={{ fontSize: '12px' }} />
                        <Area
                          yAxisId="left"
                          type="monotone"
                          dataKey="jobs_total"
                          stroke="#3b82f6"
                          fill="url(#colorTotal)"
                          name="Задач (Job)"
                          strokeWidth={2}
                        />
                        <Area
                          yAxisId="left"
                          type="monotone"
                          dataKey="takes_total"
                          stroke="#8b5cf6"
                          fill="url(#colorTakes)"
                          name="Снимков (Take)"
                          strokeWidth={2}
                        />
                        <Area
                          yAxisId="left"
                          type="monotone"
                          dataKey="jobs_succeeded"
                          stroke="#10b981"
                          fill="url(#colorSuccess)"
                          name="Успешно"
                          strokeWidth={2}
                        />
                        <Area
                          yAxisId="left"
                          type="monotone"
                          dataKey="jobs_failed"
                          stroke="#ef4444"
                          fill="url(#colorFailed)"
                          name="Ошибки"
                          strokeWidth={2}
                        />
                        <Area
                          yAxisId="left"
                          type="monotone"
                          dataKey="active_users"
                          stroke="#f59e0b"
                          fill="url(#colorUsers)"
                          name="Активные пользователи"
                          strokeWidth={2}
                        />
                        <Line
                          yAxisId="right"
                          type="monotone"
                          dataKey="take_avg_generation_sec"
                          name="Сред. время 3 снимков"
                          stroke="#eab308"
                          strokeWidth={2}
                          dot={{ r: 3 }}
                          connectNulls
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <TrendingUp className="h-5 w-5" />
                    Динамика ({historyDays} д.)
                  </CardTitle>
                  <CardDescription>Нет данных за период</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="h-[280px] flex items-center justify-center text-muted-foreground">
                    Нет данных за период
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Сред. время 3 снимков по дням — каждый день считается отдельно */}
            {historyData?.history?.length ? (
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Clock className="h-5 w-5" />
                    Сред. время 3 снимков по дням
                  </CardTitle>
                  <CardDescription>
                    Среднее время от создания снимка до готовности 3 вариантов, рассчитанное отдельно по каждому дню за {historyData.window_days ?? 30} д.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="h-[240px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={historyData.history.map((d: { date: string; take_avg_generation_sec?: number | null }) => ({
                          date: d.date,
                          dateShort: d.date.slice(5),
                          sec: d.take_avg_generation_sec ?? null,
                          min: d.take_avg_generation_sec != null ? Number((d.take_avg_generation_sec / 60).toFixed(1)) : null,
                        }))}
                        margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                        <XAxis dataKey="dateShort" tick={{ fontSize: 11 }} />
                        <YAxis
                          tick={{ fontSize: 11 }}
                          tickFormatter={(v) => (v >= 60 ? `${(v / 60).toFixed(0)} мин` : `${v} сек`)}
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: 'hsl(var(--background))',
                            border: '1px solid hsl(var(--border))',
                            borderRadius: '8px',
                          }}
                          formatter={(value: number) => [
                            value != null && value >= 60
                              ? `${(value / 60).toFixed(1)} мин`
                              : value != null
                                ? `${Math.round(value)} сек`
                                : '—',
                            'Среднее за день',
                          ]}
                          labelFormatter={(label) => `День: ${label}`}
                        />
                        <Line
                          type="monotone"
                          dataKey="sec"
                          name="Сред. время 3 снимков"
                          stroke="#eab308"
                          strokeWidth={2}
                          dot={{ r: 3 }}
                          connectNulls
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </CardContent>
              </Card>
            ) : null}

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
            </>
          )}
        </TabsContent>

        {/* FUNNEL */}
        <TabsContent value="funnel" className="space-y-6">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              title="Стартовали"
              value={formatNumber(funnelStartUsers)}
              subtitle="Уникальные пользователи"
              icon={Users}
              color="bg-blue-500"
            />
            <MetricCard
              title="Нажали оплату"
              value={formatNumber(funnelPayClicked)}
              subtitle="Шаг pay_initiated"
              icon={Target}
              color="bg-cyan-500"
            />
            <MetricCard
              title="Не дошли до фото"
              value={formatNumber(funnelNoPhotoUsers)}
              subtitle={`${funnelNoPhotoPct}% от старта`}
              icon={AlertCircle}
              color="bg-orange-500"
            />
            <MetricCard
              title="4K доставлен"
              value={formatNumber(funnelStepRows.find((r) => r.stepKey === 'hd_delivered')?.count ?? 0)}
              subtitle="Завершённые сессии"
              icon={CheckCircle}
              color="bg-green-500"
            />
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Воронка продукта</CardTitle>
              <CardDescription>За всё время, без разбиений по окнам. Ключевые шаги и конверсия между шагами.</CardDescription>
            </CardHeader>
            <CardContent>
              {productFunnel?.funnel_counts ? (
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {funnelStepRows.map((row, idx) => (
                    <div key={row.stepKey} className="rounded-xl border bg-background/60 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="text-sm font-medium">{row.label}</div>
                        <Badge variant={idx === 0 ? 'secondary' : row.conversion >= 40 ? 'secondary' : 'outline'}>
                          {row.conversion}%
                        </Badge>
                      </div>
                      <div className="mt-3 text-2xl font-semibold">{formatNumber(row.count)}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {idx === 0 ? 'Базовый шаг' : `Конверсия от «${funnelStepRows[idx - 1]?.label ?? 'пред. шага'}»`}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground">Нет данных.</p>
              )}
            </CardContent>
          </Card>
          {productMetricsV2 != null && (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              <MetricCard title="Preview → Pay" value={`${productMetricsV2.preview_to_pay_pct ?? 0}%`} subtitle="Конверсия" icon={Target} color="bg-cyan-500" />
              <MetricCard title="Hit Rate" value={`${productMetricsV2.hit_rate_pct ?? 0}%`} subtitle="Сессии с выбором / с превью" icon={CheckCircle} color="bg-green-500" />
              <MetricCard title="AOV (Stars)" value={productMetricsV2.aov_stars ?? 0} subtitle="Средний чек" icon={TrendingUp} color="bg-warning" />
              <MetricCard title="Repeat Purchase" value={`${productMetricsV2.repeat_purchase_rate_pct ?? 0}%`} subtitle="2+ покупок" icon={Users} color="bg-purple-500" />
            </div>
          )}

          {/* Исторические данные: динамика воронки по дням (product_events) */}
          <Card>
            <CardHeader>
              <CardTitle>Динамика воронки (всё время)</CardTitle>
              <CardDescription>История ключевых шагов: старт, фото, превью, выбор, оплата, 4K.</CardDescription>
            </CardHeader>
            <CardContent>
              {funnelHistoryError ? (
                <p className="text-destructive">Ошибка загрузки истории. Обновите страницу и повторите запрос.</p>
              ) : funnelHistoryLoading ? (
                <div className="h-[340px] flex items-center justify-center text-muted-foreground">
                  Загрузка истории…
                </div>
              ) : funnelHistoryData?.history?.length ? (
                <div className="h-[340px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                      data={funnelHistoryData.history}
                      margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
                    >
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
                      <Legend wrapperStyle={{ fontSize: '11px' }} />
                      {FUNNEL_HISTORY_SERIES.map((dataKey, idx) => (
                        <Line
                          key={dataKey}
                          type="monotone"
                          dataKey={dataKey}
                          name={FUNNEL_LABELS[dataKey] ?? dataKey}
                          stroke={COLORS[idx % COLORS.length]}
                          strokeWidth={2}
                          dot={{ r: 2 }}
                          connectNulls
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="text-muted-foreground py-8 text-center">
                  Нет исторических данных.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* PATH — переходы и типичные пути */}
        <TabsContent value="path" className="space-y-6">
          <div className="text-sm text-muted-foreground">Сбор за всё время</div>

          {pathData?.truncated && (
            <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-2 text-sm text-amber-800 dark:text-amber-200">
              Данные обрезаны лимитом строк. Показана частичная выборка, но тренд остаётся репрезентативным.
            </div>
          )}
          {(Number(pathTransitionsData?.data_quality?.excluded_without_session_events ?? 0) > 0) && (
            <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-2 text-sm text-amber-800 dark:text-amber-200">
              Для shadow-расчёта исключено событий без session_id: {Number(pathTransitionsData?.data_quality?.excluded_without_session_events ?? 0)}.
            </div>
          )}

          {/* Блок 1: Поток по шагам — таблица переходов */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <GitBranch className="h-5 w-5" />
                Переходы между шагами
              </CardTitle>
              <CardDescription>
                Переходы между шагами воронки за всё время. Сессий на переход, медиана и среднее времени в минутах от предыдущего шага.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {pathLoading ? (
                <div className="py-8 text-center text-muted-foreground">Загрузка…</div>
              ) : pathError ? (
                <p className="py-8 text-center text-destructive">Ошибка загрузки. Обновите страницу и повторите запрос.</p>
              ) : (pathTransitionsData?.transitions?.length ?? 0) > 0 ? (
                <div className="rounded-md border">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-muted/50">
                        <th className="text-left p-3 font-medium">От</th>
                        <th className="text-left p-3 font-medium">К</th>
                        <th className="text-right p-3 font-medium">Сессий</th>
                        <th className="text-right p-3 font-medium">Медиана, мин</th>
                        <th className="text-right p-3 font-medium">Среднее, мин</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pathTransitionsData!.transitions.map((t) => (
                        <tr key={`${t.from}\t${t.to ?? 'null'}`} className="border-b last:border-0">
                          <td className="p-3">{FUNNEL_LABELS[t.from] ?? t.from}</td>
                          <td className="p-3">{t.to != null ? (FUNNEL_LABELS[t.to] ?? t.to) : '—'}</td>
                          <td className="p-3 text-right font-medium">{formatNumber(t.sessions)}</td>
                          <td className="p-3 text-right">{t.median_minutes != null ? t.median_minutes : '—'}</td>
                          <td className="p-3 text-right">{t.avg_minutes != null ? t.avg_minutes : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-muted-foreground">Нет данных.</p>
              )}
            </CardContent>
          </Card>

          {/* Отвал: последний шаг без оплаты/доставки */}
          {pathTransitionsData?.drop_off?.length ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Отвал по последнему шагу</CardTitle>
                <CardDescription>
                  Сессии, которые не дошли до «Оплата успешна» или «4K доставлен». Последний зафиксированный шаг.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="rounded-md border">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-muted/50">
                        <th className="text-left p-3 font-medium">Последний шаг</th>
                        <th className="text-right p-3 font-medium">Сессий</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pathTransitionsData.drop_off.map((d) => (
                        <tr key={d.from} className="border-b last:border-0">
                          <td className="p-3">{FUNNEL_LABELS[d.from] ?? d.from}</td>
                          <td className="p-3 text-right font-medium">{formatNumber(d.sessions)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          ) : null}

          {/* Блок 2: Типичные пути */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ListOrdered className="h-5 w-5" />
                Типичные пути
              </CardTitle>
              <CardDescription>
                Топ-20 последовательностей шагов за всё время. Медиана времени до оплаты и до последнего шага (мин), доля дошедших до оплаты.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {pathLoading ? (
                <div className="py-8 text-center text-muted-foreground">Загрузка…</div>
              ) : pathError ? (
                <p className="py-8 text-center text-destructive">Ошибка загрузки. Обновите страницу и повторите запрос.</p>
              ) : (pathSequencesData?.paths?.length ?? 0) > 0 ? (
                <div className="rounded-md border overflow-x-auto">
                  <table className="w-full text-sm min-w-[640px]">
                    <thead>
                      <tr className="border-b bg-muted/50">
                        <th className="text-left p-3 font-medium">Путь</th>
                        <th className="text-right p-3 font-medium">Сессий</th>
                        <th className="text-right p-3 font-medium">Медиана до оплаты, мин</th>
                        <th className="text-right p-3 font-medium">Медиана до конца, мин</th>
                        <th className="text-right p-3 font-medium">% до оплаты</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pathSequencesData!.paths.map((p) => (
                        <tr key={p.steps.join('|')} className="border-b last:border-0">
                          <td className="p-3">
                            <span className="text-muted-foreground whitespace-nowrap">
                              {p.steps.map((s) => FUNNEL_LABELS[s] ?? s).join(' → ')}
                            </span>
                          </td>
                          <td className="p-3 text-right font-medium">{formatNumber(p.sessions)}</td>
                          <td className="p-3 text-right">{p.median_minutes_to_pay != null ? p.median_minutes_to_pay : '—'}</td>
                          <td className="p-3 text-right">{p.median_minutes_to_last != null ? p.median_minutes_to_last : '—'}</td>
                          <td className="p-3 text-right">{p.pct_reached_pay}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-muted-foreground">Нет данных.</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* BUTTON CLICKS */}
        <TabsContent value="buttons" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Клики по кнопкам</CardTitle>
              <CardDescription>Все события button_click за всё время: какие кнопки нажимают и сколько людей их используют.</CardDescription>
            </CardHeader>
            <CardContent>
              {buttonClicksError ? (
                <p className="text-destructive">Ошибка загрузки. Обновите страницу и повторите запрос.</p>
              ) : knownButtonRows.length > 0 || hasUnknownButtons ? (
                <div className="space-y-6">
                  <div className="grid gap-4 md:grid-cols-3">
                    <MetricCard
                      title="Клики по известным кнопкам"
                      value={formatNumber(totalKnownClicks)}
                      subtitle="Реальные клики"
                      icon={Activity}
                      color="bg-blue-500"
                    />
                    <MetricCard
                      title="Суммарный user-touch"
                      value={formatNumber(totalKnownUsersByButtons)}
                      subtitle="Сумма уникальных по кнопкам"
                      icon={Users}
                      color="bg-cyan-500"
                    />
                    <MetricCard
                      title="Неклассифицировано"
                      value={formatNumber(unknownClicks)}
                      subtitle="unknown button_id"
                      icon={AlertCircle}
                      color="bg-orange-500"
                    />
                  </div>

                  {buttonTopChartRows.length > 0 && (
                    <Card className="border-dashed">
                      <CardHeader>
                        <CardTitle className="text-base">Топ-10 кнопок</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="h-[300px]">
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={buttonTopChartRows} layout="vertical" margin={{ top: 0, right: 16, left: 16, bottom: 0 }}>
                              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                              <XAxis type="number" tick={{ fontSize: 11 }} />
                              <YAxis type="category" dataKey="label" width={180} tick={{ fontSize: 11 }} />
                              <Tooltip />
                              <Bar dataKey="clicks" name="Кликов" fill="#2563eb" radius={[0, 8, 8, 0]} />
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      </CardContent>
                    </Card>
                  )}

                  {buttonTopRows.length > 0 && (
                    <div className="rounded-md border">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b bg-muted/50">
                            <th className="text-left p-3 font-medium">Кнопка</th>
                            <th className="text-right p-3 font-medium">Кликов</th>
                            <th className="text-right p-3 font-medium">Уник. пользователей</th>
                          </tr>
                        </thead>
                        <tbody>
                          {buttonTopRows.map((row) => (
                            <tr key={row.buttonId} className="border-b last:border-0">
                              <td className="p-3">{row.label}</td>
                              <td className="p-3 text-right font-medium">{formatNumber(row.clicks)}</td>
                              <td className="p-3 text-right">{formatNumber(row.users)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {hasUnknownButtons && buttonClicksData?.unknown_by_button_id && (
                    <div className="rounded-md border border-amber-500/50">
                      <div className="border-b bg-amber-500/10 px-3 py-2 text-sm font-medium">
                        Не классифицировано (unknown button_id)
                      </div>
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b bg-muted/30">
                            <th className="text-left p-3 font-medium">button_id</th>
                            <th className="text-right p-3 font-medium">Кликов</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(buttonClicksData.unknown_by_button_id)
                            .sort(([, a], [, b]) => (b as number) - (a as number))
                            .map(([buttonId, count]) => (
                              <tr key={buttonId} className="border-b last:border-0">
                                <td className="p-3 font-mono text-xs">{buttonId}</td>
                                <td className="p-3 text-right font-medium">{formatNumber(count as number)}</td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-muted-foreground">Нет данных.</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ENGAGEMENT */}
        <TabsContent value="engagement" className="space-y-6">
          <Card className="border-dashed bg-muted/30">
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">
                Метрики Retention, Churn, New users, Avg session и LTV пока не считаются бэкендом (GET /telemetry/product-metrics). Ниже — распределение активности по пользователям (Jobs за период).
              </p>
            </CardContent>
          </Card>

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
                  const jobs = trend.jobs_window ?? 0
                  const takes = trend.takes_window ?? 0
                  const total = jobs + takes
                  const succeeded =
                    (trend.succeeded_window ?? 0) + (trend.takes_succeeded_window ?? 0)
                  const failed = (trend.failed_window ?? 0) + (trend.takes_failed_window ?? 0)
                  const successRate = total > 0 ? ((succeeded / total) * 100).toFixed(1) : '0'
                  const chosen = trend.chosen_window ?? trend.selected_window ?? 0
                  return (
                    <div
                      key={trend.trend_id}
                      className="flex items-center justify-between p-4 rounded-lg border bg-card hover:shadow-md transition-shadow"
                    >
                      <div className="flex items-center gap-4">
                        <span className="text-4xl">{trend.emoji}</span>
                        <div>
                          <div className="font-semibold text-lg">{trend.name}</div>
                          <div className="flex items-center gap-3 mt-1 flex-wrap">
                            {jobs > 0 && (
                              <Badge variant="secondary" className="text-xs">
                                {jobs} задач
                              </Badge>
                            )}
                            {takes > 0 && (
                              <Badge variant="secondary" className="text-xs">
                                {takes} снимков
                              </Badge>
                            )}
                            {chosen > 0 && (
                              <Badge variant="outline" className="text-xs">
                                {chosen} выборов
                              </Badge>
                            )}
                            <span className="text-xs text-muted-foreground">
                              Success: {successRate}%
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="flex items-center gap-2">
                          <div className="text-2xl font-bold text-success">{succeeded}</div>
                          <CheckCircle className="h-5 w-5 text-success" />
                        </div>
                        {failed > 0 && (
                          <div className="flex items-center gap-2 justify-end mt-1">
                            <div className="text-sm text-destructive">{failed}</div>
                            <AlertCircle className="h-4 w-4 text-destructive" />
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

        {/* REVENUE */}
        <TabsContent value="revenue" className="space-y-6">
          <div className="text-sm text-muted-foreground">Сбор за всё время</div>
          {revenueData != null ? (
            <>
              <div className="grid gap-4 md:grid-cols-3">
                <MetricCard title="Выручка (Stars)" value={formatNumber(revenueData.total_stars ?? 0)} subtitle="Всё время" icon={TrendingUp} color="bg-green-500" />
                <MetricCard title="Выручка (₽)" value={formatNumber(revenueData.revenue_rub_approx ?? 0)} subtitle="приблизительно" icon={Activity} color="bg-success" />
                <MetricCard title="Оплаченных событий" value={formatNumber(Number(revenueData.data_quality?.pay_success_events ?? 0))} subtitle="pay_success" icon={CheckCircle} color="bg-blue-500" />
              </div>
              <Card>
                <CardHeader>
                  <CardTitle>По пакетам (Stars)</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {Object.entries(revenueData.by_pack ?? {}).map(([packId, stars]) => (
                      <div key={packId} className="flex justify-between items-center py-1 border-b last:border-0">
                        <span className="font-medium">{packId}</span>
                        <span>{formatNumber(Number(stars))} ⭐</span>
                      </div>
                    ))}
                    {Object.keys(revenueData.by_pack ?? {}).length === 0 && (
                      <p className="text-muted-foreground">Нет данных</p>
                    )}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>По источникам (Stars)</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {Object.entries(revenueData.by_source ?? {}).map(([source, stars]) => (
                      <div key={source} className="flex justify-between items-center py-1 border-b last:border-0">
                        <span className="font-medium">{source}</span>
                        <span>{formatNumber(Number(stars))} ⭐</span>
                      </div>
                    ))}
                    {Object.keys(revenueData.by_source ?? {}).length === 0 && (
                      <p className="text-muted-foreground">Нет данных</p>
                    )}
                  </div>
                </CardContent>
              </Card>
            </>
          ) : (
            <p className="text-muted-foreground">Загрузка...</p>
          )}
        </TabsContent>

        {/* HEALTH */}
        <TabsContent value="health" className="space-y-6">
          {/* Производительность */}
          <div>
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <BarChart3 className="h-5 w-5" />
              Производительность
            </h2>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              <MetricCard
                title="Всего задач"
                value={formatNumber(data?.jobs_total ?? 0)}
                subtitle="За всё время"
                icon={BarChart3}
                color="bg-indigo-500"
              />
              <MetricCard
                title={`За ${windowHours}ч`}
                value={formatNumber((data?.jobs_window ?? 0) + (data?.takes_window ?? 0))}
                subtitle="Новых задач (Job + снимки)"
                icon={Clock}
                color="bg-cyan-500"
              />
              <MetricCard
                title="Успешно"
                value={formatNumber((data?.jobs_by_status?.SUCCEEDED ?? 0) + (data?.takes_succeeded ?? 0))}
                subtitle={(() => {
                  const total = (data?.jobs_window ?? 0) + (data?.takes_window ?? 0)
                  const succeeded = (data?.jobs_by_status?.SUCCEEDED ?? 0) + (data?.takes_succeeded ?? 0)
                  const pct = total ? Math.round((succeeded / total) * 100) : 0
                  return `${pct}% success rate`
                })()}
                icon={CheckCircle}
                color="bg-success"
              />
              <MetricCard
                title="Ошибки"
                value={formatNumber(
                  (data?.jobs_by_status?.FAILED ?? 0) +
                    (data?.jobs_by_status?.ERROR ?? 0) +
                    (data?.takes_failed ?? 0)
                )}
                subtitle={(() => {
                  const total = (data?.jobs_window ?? 0) + (data?.takes_window ?? 0)
                  const failed =
                    (data?.jobs_by_status?.FAILED ?? 0) +
                    (data?.jobs_by_status?.ERROR ?? 0) +
                    (data?.takes_failed ?? 0)
                  const pct = total ? Math.round((failed / total) * 100) : 0
                  return `${pct}% error rate`
                })()}
                icon={AlertCircle}
                color="bg-destructive"
              />
              <MetricCard
                title="В очереди"
                value={data?.queue_length ?? 0}
                subtitle="Celery queue"
                icon={Clock}
                color="bg-orange-500"
              />
              <MetricCard
                title={`Снимков за ${windowHours}ч`}
                value={formatNumber(data?.takes_window ?? 0)}
                subtitle="Take (основной поток)"
                icon={Activity}
                color="bg-violet-500"
              />
              <MetricCard
                title="Сред. время 3 снимков"
                value={
                  data?.take_avg_generation_sec != null
                    ? data.take_avg_generation_sec >= 60
                      ? `${(data.take_avg_generation_sec / 60).toFixed(1)} мин`
                      : `${Math.round(data.take_avg_generation_sec)} сек`
                    : '—'
                }
                subtitle={`За ${windowHours} ч · по дням — график ниже`}
                icon={Zap}
                color="bg-warning"
              />
            </div>
          </div>

          {/* График распределения ошибок по датам за 30 дней */}
          {errorsData?.errors_by_day?.length ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5" />
                  Распределение ошибок по датам ({errorsData.window_days} д.)
                </CardTitle>
                <CardDescription>Job и Take по дням</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={errorsData.errors_by_day}>
                      <defs>
                        <linearGradient id="colorJobsFailed" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#ef4444" stopOpacity={0.8} />
                          <stop offset="95%" stopColor="#ef4444" stopOpacity={0.1} />
                        </linearGradient>
                        <linearGradient id="colorTakesFailed" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#f97316" stopOpacity={0.8} />
                          <stop offset="95%" stopColor="#f97316" stopOpacity={0.1} />
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
                        dataKey="jobs_failed"
                        stroke="#ef4444"
                        fill="url(#colorJobsFailed)"
                        name="Job (перегенерация)"
                        strokeWidth={2}
                        stackId="1"
                      />
                      <Area
                        type="monotone"
                        dataKey="takes_failed"
                        stroke="#f97316"
                        fill="url(#colorTakesFailed)"
                        name="Take (снимок)"
                        strokeWidth={2}
                        stackId="1"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          ) : null}

          <div className="grid gap-6 md:grid-cols-2">
            {/* Полная телеметрия ошибок за 30 дней (Job + Take) */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <AlertCircle className="h-5 w-5 text-destructive" />
                  Ошибки ({errorsData?.window_days ?? 30} д.)
                </CardTitle>
                <CardDescription>
                  Все ошибки Job и Take за период (телеметрия)
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2 max-h-[400px] overflow-y-auto">
                  {Object.entries(errorsData?.combined ?? {})
                    .sort((a, b) => b[1] - a[1])
                    .map(([code, count]) => {
                      const jobCnt = errorsData?.jobs_failed_by_error?.[code] ?? 0
                      const takeCnt = errorsData?.takes_failed_by_error?.[code] ?? 0
                      return (
                        <div
                          key={code}
                          className="flex items-center justify-between p-3 rounded-lg border bg-card gap-2"
                        >
                          <span className="font-mono text-sm text-muted-foreground truncate flex-1" title={code}>
                            {code}
                          </span>
                          <div className="flex items-center gap-2 shrink-0">
                            {jobCnt > 0 && (
                              <Badge variant="secondary" title="Job (перегенерация)">
                                J: {formatNumber(jobCnt)}
                              </Badge>
                            )}
                            {takeCnt > 0 && (
                              <Badge variant="secondary" title="Take (снимок)">
                                T: {formatNumber(takeCnt)}
                              </Badge>
                            )}
                            <Badge variant="destructive">{formatNumber(count)}</Badge>
                          </div>
                        </div>
                      )
                    })}
                  {Object.keys(errorsData?.combined ?? {}).length === 0 && (
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
                    <span className="text-xl font-bold text-success">
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
