import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { RefreshCw } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatNumber } from '@/lib/utils'
import { telemetryService, type TelemetryOverviewV3Response } from '@/services/api'

type TrendMode = 'flow' | 'revenue'

const KPI_META: Array<{ key: string; title: string; unit?: 'pct' | 'sec' | 'rub' | 'count' }> = [
  { key: 'started_users', title: 'Стартовавшие пользователи', unit: 'count' },
  { key: 'preview_reach_rate', title: 'Дошли до превью', unit: 'pct' },
  { key: 'favorite_selection_rate', title: 'Выбор варианта', unit: 'pct' },
  { key: 'first_purchase_rate', title: 'Первая покупка', unit: 'pct' },
  { key: 'revenue_per_started_user', title: 'Выручка на старт', unit: 'rub' },
]

const FLOW_SERIES: Array<{ key: keyof TelemetryOverviewV3Response['trend_flow'][number]; label: string; color: string }> = [
  { key: 'started_users', label: 'Старт', color: '#2563eb' },
  { key: 'photo_uploaded', label: 'Фото', color: '#06b6d4' },
  { key: 'preview_ready', label: 'Превью', color: '#8b5cf6' },
  { key: 'favorite_selected', label: 'Выбор', color: '#f59e0b' },
  { key: 'pay_success', label: 'Оплата', color: '#22c55e' },
]

const REVENUE_SERIES: Array<{ key: keyof TelemetryOverviewV3Response['trend_revenue'][number]; label: string; color: string }> = [
  { key: 'orders', label: 'Заказы', color: '#2563eb' },
  { key: 'paid_users', label: 'Платящие', color: '#06b6d4' },
  { key: 'revenue', label: 'Выручка', color: '#f59e0b' },
  { key: 'revenue_per_started_user', label: 'Выручка/старт', color: '#8b5cf6' },
]

function formatKpiValue(value: number | null, unit: 'pct' | 'sec' | 'rub' | 'count' | undefined): string {
  if (value == null) return 'N/A'
  if (unit === 'pct') return `${value}%`
  if (unit === 'rub') return `${formatNumber(value)} ₽`
  if (unit === 'sec') {
    if (value >= 3600) return `${(value / 3600).toFixed(1)} ч`
    if (value >= 60) return `${(value / 60).toFixed(1)} мин`
    return `${Math.round(value)} сек`
  }
  return formatNumber(value)
}

function formatDateTime(value: string): string {
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString('ru-RU')
}

export function TelemetryOverviewV3() {
  const window = 'all' as const
  const trendModeFixed = 'all_flows' as const
  const trustModeFixed = 'all_data' as const
  const [trendMode, setTrendMode] = useState<TrendMode>('flow')

  const {
    data: overview,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['telemetry-overview-v3', window, trendModeFixed, trustModeFixed],
    queryFn: () =>
      telemetryService.getOverviewV3({
        window,
        flow_mode: trendModeFixed,
        trust_mode: trustModeFixed,
      }),
    refetchInterval: 60_000,
  })

  const trendData = useMemo(() => {
    if (!overview) return []
    return trendMode === 'flow' ? overview.trend_flow : overview.trend_revenue
  }, [overview, trendMode])

  const bottleneckData = useMemo(
    () =>
      (overview?.bottlenecks.steps ?? []).map((step) => ({
        label: step.label,
        value: step.conversion_pct ?? 0,
      })),
    [overview],
  )

  if (isLoading) {
    return <div className="text-sm text-muted-foreground">Загрузка аналитики...</div>
  }

  if (isError || !overview) {
    const errorDetail = (() => {
      if (!error) return null
      if (isAxiosError(error)) {
        const status = error.response?.status
        const detail = (error.response?.data as { detail?: string } | undefined)?.detail || error.message
        return status ? `HTTP ${status}: ${detail}` : detail
      }
      if (error instanceof Error) return error.message
      return String(error)
    })()

    return (
      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="text-base">Аналитика недоступна</CardTitle>
          {errorDetail && <div className="text-sm text-destructive">{errorDetail}</div>}
        </CardHeader>
        <CardContent>
          <Button variant="outline" onClick={() => refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Повторить
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <Card className="border-border/70 shadow-sm">
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-2xl">Аналитика продукта</CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant="secondary">Все данные</Badge>
              <Badge variant="outline">Обновлено: {formatDateTime(overview.last_updated_at)}</Badge>
              <Button variant="outline" size="icon" onClick={() => refetch()} disabled={isFetching}>
                <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {KPI_META.map((meta) => {
          const kpi = overview.kpis[meta.key]
          if (!kpi) return null
          return (
            <Card key={meta.key} className="border-border/80 bg-gradient-to-b from-background to-slate-50/60 dark:to-slate-950/20">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">{meta.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-semibold tracking-tight">{formatKpiValue(kpi.value, meta.unit)}</div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <Card className="border-border/80 shadow-sm">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>Динамика</CardTitle>
            <div className="flex items-center gap-2 rounded-lg border border-border p-1">
              <Button variant={trendMode === 'flow' ? 'default' : 'ghost'} size="sm" onClick={() => setTrendMode('flow')}>
                Flow
              </Button>
              <Button variant={trendMode === 'revenue' ? 'default' : 'ghost'} size="sm" onClick={() => setTrendMode('revenue')}>
                Revenue
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="h-[360px]">
            <ResponsiveContainer width="100%" height="100%">
              {trendMode === 'flow' ? (
                <LineChart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend />
                  {FLOW_SERIES.map((series) => (
                    <Line
                      key={series.key as string}
                      type="monotone"
                      dataKey={series.key as string}
                      name={series.label}
                      stroke={series.color}
                      strokeWidth={2.5}
                      dot={false}
                    />
                  ))}
                </LineChart>
              ) : (
                <LineChart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
                  <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(value, name) => (name === 'Выручка' || name === 'Выручка/старт' ? [`${value} ₽`, name] : [value, name])} />
                  <Legend />
                  {REVENUE_SERIES.map((series) => (
                    <Line
                      key={series.key as string}
                      yAxisId={series.key === 'revenue' || series.key === 'revenue_per_started_user' ? 'right' : 'left'}
                      type="monotone"
                      dataKey={series.key as string}
                      name={series.label}
                      stroke={series.color}
                      strokeWidth={2.5}
                      dot={false}
                    />
                  ))}
                </LineChart>
              )}
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/80 shadow-sm">
        <CardHeader>
          <CardTitle>Конверсия по шагам</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[320px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={bottleneckData} margin={{ top: 12, right: 20, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(value: number) => [`${value}%`, 'Конверсия']} />
                <Bar dataKey="value" radius={[8, 8, 0, 0]}>
                  {bottleneckData.map((entry) => (
                    <Cell key={entry.label} fill={entry.value >= 60 ? '#22c55e' : entry.value >= 30 ? '#f59e0b' : '#ef4444'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
