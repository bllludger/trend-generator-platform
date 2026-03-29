import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AlertCircle, RefreshCw } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatNumber } from '@/lib/utils'
import { telemetryService, type OverviewV3Kpi, type TelemetryOverviewV3Response } from '@/services/api'

type OverviewWindow = '24h' | '7d' | '30d' | '90d'
type TrendMode = 'flow' | 'revenue'

const WINDOW_OPTIONS: Array<{ value: OverviewWindow; label: string }> = [
  { value: '24h', label: '24ч' },
  { value: '7d', label: '7д' },
  { value: '30d', label: '30д' },
  { value: '90d', label: '90д' },
]

const KPI_META: Array<{ key: string; title: string; unit?: 'pct' | 'sec' | 'rub' | 'count' }> = [
  { key: 'started_users', title: 'Started users', unit: 'count' },
  { key: 'upload_rate', title: 'Upload rate', unit: 'pct' },
  { key: 'preview_reach_rate', title: 'Preview reach rate', unit: 'pct' },
  { key: 'median_time_to_preview_sec', title: 'Median time to first preview', unit: 'sec' },
  { key: 'favorite_selection_rate', title: 'Best variant selection rate', unit: 'pct' },
  { key: 'paywall_reach_rate', title: 'Paywall reach rate', unit: 'pct' },
  { key: 'first_purchase_rate', title: 'First purchase rate', unit: 'pct' },
  { key: 'revenue_per_started_user', title: 'Revenue per started user', unit: 'rub' },
]

const EXPERIENCE_META: Array<{ key: keyof TelemetryOverviewV3Response['experience_health']; title: string; unit?: 'pct' | 'sec' }> = [
  { key: 'preview_success_rate', title: 'Preview success rate', unit: 'pct' },
  { key: 'all_variants_failed_rate', title: 'All variants failed rate', unit: 'pct' },
  { key: 'median_time_to_first_preview_sec', title: 'Median time to first preview', unit: 'sec' },
  { key: 'p95_time_to_first_preview_sec', title: 'P95 time to first preview', unit: 'sec' },
  { key: 'value_delivery_success_rate', title: 'Value delivery success rate', unit: 'pct' },
]

const FLOW_SERIES: Array<{ key: keyof TelemetryOverviewV3Response['trend_flow'][number]; label: string; color: string }> = [
  { key: 'started_users', label: 'Started users', color: '#2563eb' },
  { key: 'photo_uploaded', label: 'Photo uploaded', color: '#14b8a6' },
  { key: 'preview_ready', label: 'Preview ready', color: '#8b5cf6' },
  { key: 'favorite_selected', label: 'Favorite selected', color: '#f59e0b' },
  { key: 'pay_success', label: 'Pay success', color: '#22c55e' },
]

const REVENUE_SERIES: Array<{ key: keyof TelemetryOverviewV3Response['trend_revenue'][number]; label: string; color: string }> = [
  { key: 'orders', label: 'Orders', color: '#2563eb' },
  { key: 'paid_users', label: 'Paid users', color: '#14b8a6' },
  { key: 'revenue', label: 'Revenue', color: '#f59e0b' },
  { key: 'revenue_per_started_user', label: 'Revenue per started user', color: '#8b5cf6' },
]

const TRUST_BADGE_VARIANT: Record<TelemetryOverviewV3Response['trust']['status'], 'success' | 'warning' | 'error' | 'destructive'> = {
  Good: 'success',
  Caution: 'warning',
  Degraded: 'error',
  Broken: 'destructive',
}

const KPI_TRUST_VARIANT: Record<OverviewV3Kpi['trust_label'], 'success' | 'warning' | 'outline' | 'destructive'> = {
  Trusted: 'success',
  Partial: 'warning',
  Directional: 'outline',
  Broken: 'destructive',
}

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

function formatDelta(delta: number | null): string {
  if (delta == null) return '—'
  if (delta > 0) return `+${delta}%`
  return `${delta}%`
}

function formatDateTime(value: string): string {
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString()
}

export function TelemetryOverviewV3() {
  const [window, setWindow] = useState<OverviewWindow>('7d')
  const [sourceInput, setSourceInput] = useState('')
  const [campaignInput, setCampaignInput] = useState('')
  const [entryTypeInput, setEntryTypeInput] = useState('')
  const [source, setSource] = useState('')
  const [campaign, setCampaign] = useState('')
  const [entryType, setEntryType] = useState('')
  const [flowMode, setFlowMode] = useState<'canonical_only' | 'all_flows'>('canonical_only')
  const [trustMode, setTrustMode] = useState<'trusted_only' | 'all_data'>('trusted_only')
  const [trendMode, setTrendMode] = useState<TrendMode>('flow')
  const [hiddenSeries, setHiddenSeries] = useState<Record<string, boolean>>({})

  const {
    data: overview,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['telemetry-overview-v3', window, source, campaign, entryType, flowMode, trustMode],
    queryFn: () =>
      telemetryService.getOverviewV3({
        window,
        source: source || undefined,
        campaign: campaign || undefined,
        entry_type: entryType || undefined,
        flow_mode: flowMode,
        trust_mode: trustMode,
      }),
    refetchInterval: 60_000,
  })

  const modeSeries = trendMode === 'flow' ? FLOW_SERIES : REVENUE_SERIES

  const applyFilters = () => {
    setSource(sourceInput.trim())
    setCampaign(campaignInput.trim())
    setEntryType(entryTypeInput.trim())
  }

  const clearFilters = () => {
    setSourceInput('')
    setCampaignInput('')
    setEntryTypeInput('')
    setSource('')
    setCampaign('')
    setEntryType('')
  }

  const trendData = useMemo(() => {
    if (!overview) return []
    if (trendMode === 'flow') return overview.trend_flow
    return overview.trend_revenue
  }, [overview, trendMode])

  const sampleSizeTooSmallKpis = useMemo(() => {
    const candidates: Array<OverviewV3Kpi | undefined> = [
      ...Object.values(overview?.kpis ?? {}),
      overview?.experience_health.preview_success_rate,
      overview?.experience_health.all_variants_failed_rate,
      overview?.experience_health.median_time_to_first_preview_sec,
      overview?.experience_health.p95_time_to_first_preview_sec,
      overview?.experience_health.value_delivery_success_rate,
    ]
    return candidates.filter((kpi): kpi is OverviewV3Kpi => kpi?.reason === 'Sample size too small')
  }, [overview])

  const shouldShowSampleSizeHint = sampleSizeTooSmallKpis.length >= 3

  const coverageOrReconciliationBroken = Boolean(
    overview &&
      overview.trust.status === 'Broken' &&
      (overview.trust.session_coverage_pct < 50 ||
        overview.trust.canonical_coverage_pct < 50 ||
        overview.trust.reconciliation_pct < 50),
  )

  const toggleSeries = (key: string) => {
    setHiddenSeries((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  if (isLoading) {
    return <div className="text-sm text-muted-foreground">Загрузка Overview v3...</div>
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
          <CardTitle className="text-base">Overview v3 недоступен</CardTitle>
          <CardDescription>Не удалось загрузить агрегированный слой. Попробуйте обновить данные.</CardDescription>
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
      <Card>
        <CardHeader className="pb-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle className="text-2xl">Аналитика продукта</CardTitle>
              <CardDescription>Обзор коммерческого ядра продукта</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex rounded-lg border bg-background p-1">
                {WINDOW_OPTIONS.map((opt) => (
                  <Button
                    key={opt.value}
                    variant={window === opt.value ? 'default' : 'ghost'}
                    size="sm"
                    onClick={() => setWindow(opt.value)}
                  >
                    {opt.label}
                  </Button>
                ))}
              </div>
              <Button variant="outline" size="icon" onClick={() => refetch()} disabled={isFetching}>
                <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Input placeholder="Source" value={sourceInput} onChange={(e) => setSourceInput(e.target.value)} />
            <Input placeholder="Campaign" value={campaignInput} onChange={(e) => setCampaignInput(e.target.value)} />
            <Input placeholder="Entry type" value={entryTypeInput} onChange={(e) => setEntryTypeInput(e.target.value)} />
          </div>
          <div className="flex flex-wrap gap-2">
            <Select value={flowMode} onValueChange={(v) => setFlowMode(v as 'canonical_only' | 'all_flows')}>
              <SelectTrigger className="w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="canonical_only">Canonical only</SelectItem>
                <SelectItem value="all_flows">All flows</SelectItem>
              </SelectContent>
            </Select>
            <Select value={trustMode} onValueChange={(v) => setTrustMode(v as 'trusted_only' | 'all_data')}>
              <SelectTrigger className="w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="trusted_only">Trusted only</SelectItem>
                <SelectItem value="all_data">All data</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="default" onClick={applyFilters}>Применить фильтры</Button>
            <Button variant="outline" onClick={clearFilters}>Сбросить</Button>
            <Badge variant="outline">Обновлено: {formatDateTime(overview.last_updated_at)}</Badge>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Trust</CardTitle>
          <CardDescription>Статус качества данных для decision-grade чтения метрик</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Badge variant={TRUST_BADGE_VARIANT[overview.trust.status]}>Data trust: {overview.trust.status}</Badge>
            <Badge variant="outline">Session coverage: {overview.trust.session_coverage_pct}%</Badge>
            <Badge variant="outline">Payment validity: {overview.trust.payment_validity_pct}%</Badge>
            <Badge variant="outline">Canonical coverage: {overview.trust.canonical_coverage_pct}%</Badge>
            <Badge variant="outline">Reconciliation: {overview.trust.reconciliation_pct}%</Badge>
            <Badge variant="outline">Legacy share: {overview.trust.legacy_share_pct}%</Badge>
            {typeof overview.trust.reconciliation_session_pct === 'number' && (
              <Badge variant="outline">Reconciliation strict: {overview.trust.reconciliation_session_pct}%</Badge>
            )}
            {typeof overview.trust.reconciliation_fallback_pct === 'number' && (
              <Badge variant="outline">Reconciliation fallback: {overview.trust.reconciliation_fallback_pct}%</Badge>
            )}
          </div>
          {overview.trust.warnings.length > 0 && (
            <div className="rounded-md border border-amber-500/50 bg-amber-500/10 p-3">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <AlertCircle className="h-4 w-4" />
                Warning summary
              </div>
              <div className="space-y-1 text-sm">
                {overview.trust.warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
              </div>
            </div>
          )}
          {coverageOrReconciliationBroken && (
            <div className="rounded-md border border-sky-500/30 bg-sky-500/10 p-3">
              <div className="mb-1 flex items-center gap-2 text-sm font-medium text-sky-700 dark:text-sky-300">
                <AlertCircle className="h-4 w-4" />
                Coverage or reconciliation is broken
              </div>
              <div className="text-sm text-muted-foreground">
                Switch <span className="font-medium">trust_mode</span> to <span className="font-medium">all_data</span> for the raw slice, then compare on
                <span className="font-medium"> 30д</span> or <span className="font-medium">90д</span> if you need steadier counts.
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {shouldShowSampleSizeHint && (
        <Card className="border-sky-500/30 bg-sky-500/5">
          <CardContent className="flex flex-col gap-4 p-4 md:flex-row md:items-start md:justify-between">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                <AlertCircle className="h-4 w-4 text-sky-600" />
                KPI sample size is too small
                <Badge variant="outline">{sampleSizeTooSmallKpis.length} KPI</Badge>
              </div>
              <p className="text-sm text-muted-foreground">
                Several KPI cards are sample-limited right now. For a more decision-grade read, switch <span className="font-medium">trust_mode</span> to
                <span className="font-medium"> all_data</span> and/or widen the window to <span className="font-medium">30д</span> or
                <span className="font-medium">90д</span>.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => setTrustMode('all_data')}>
                trust_mode: all_data
              </Button>
              <Button variant="outline" size="sm" onClick={() => setWindow('30d')}>
                30д
              </Button>
              <Button variant="outline" size="sm" onClick={() => setWindow('90d')}>
                90д
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {KPI_META.map((meta) => {
          const kpi = overview.kpis[meta.key]
          if (!kpi) return null
          return (
            <Card key={meta.key}>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">{meta.title}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="text-2xl font-semibold">{formatKpiValue(kpi.value, meta.unit)}</div>
                <div className="text-xs text-muted-foreground">
                  {kpi.numerator ?? '—'} / {kpi.denominator ?? '—'}
                </div>
                <div className="text-xs text-muted-foreground">Δ vs prev: {formatDelta(kpi.delta_vs_prev_pct)}</div>
                <Badge variant={KPI_TRUST_VARIANT[kpi.trust_label]}>{kpi.trust_label}</Badge>
                {kpi.reason && <div className="text-xs text-muted-foreground">{kpi.reason}</div>}
              </CardContent>
            </Card>
          )
        })}
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <CardTitle>Core Engine Trend</CardTitle>
              <CardDescription>Flow и Revenue режимы без смешивания несопоставимых сущностей</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Button variant={trendMode === 'flow' ? 'default' : 'outline'} size="sm" onClick={() => setTrendMode('flow')}>
                Flow
              </Button>
              <Button variant={trendMode === 'revenue' ? 'default' : 'outline'} size="sm" onClick={() => setTrendMode('revenue')}>
                Revenue
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {modeSeries.map((series) => (
              <Button
                key={series.key as string}
                variant={hiddenSeries[series.key as string] ? 'outline' : 'secondary'}
                size="sm"
                onClick={() => toggleSeries(series.key as string)}
              >
                {series.label}
              </Button>
            ))}
          </div>
          <div className="h-[320px]">
            <ResponsiveContainer width="100%" height="100%">
              {trendMode === 'flow' ? (
                <LineChart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend />
                  {FLOW_SERIES.filter((series) => !hiddenSeries[series.key as string]).map((series) => (
                    <Line
                      key={series.key as string}
                      type="monotone"
                      dataKey={series.key as string}
                      name={series.label}
                      stroke={series.color}
                      strokeWidth={2}
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
                  <Tooltip formatter={(value, name) => (name === 'Revenue' || name === 'Revenue per started user' ? [`${value} ₽`, name] : [value, name])} />
                  <Legend />
                  {REVENUE_SERIES.filter((series) => !hiddenSeries[series.key as string]).map((series) => (
                    <Line
                      key={series.key as string}
                      yAxisId={series.key === 'revenue' || series.key === 'revenue_per_started_user' ? 'right' : 'left'}
                      type="monotone"
                      dataKey={series.key as string}
                      name={series.label}
                      stroke={series.color}
                      strokeWidth={2}
                      dot={false}
                    />
                  ))}
                </LineChart>
              )}
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Bottleneck Snapshot</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {overview.bottlenecks.steps.map((step) => (
              <Card key={step.key} className="border">
                <CardContent className="pt-4 space-y-1">
                  <div className="text-sm font-medium">{step.label}</div>
                  <div className="text-xl font-semibold">{step.conversion_pct == null ? 'N/A' : `${step.conversion_pct}%`}</div>
                  <div className="text-xs text-muted-foreground">{step.numerator} / {step.denominator}</div>
                  <div className="text-xs text-muted-foreground">Δ {formatDelta(step.delta_vs_prev_pct)}</div>
                  <Badge variant={step.state === 'OK' ? 'success' : step.state === 'Watch' ? 'warning' : 'destructive'}>{step.state}</Badge>
                  {step.reason && <div className="text-xs text-muted-foreground">{step.reason}</div>}
                </CardContent>
              </Card>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">Biggest drop: {overview.bottlenecks.biggest_drop_step ?? '—'}</Badge>
            <Badge variant="outline">Biggest negative delta: {overview.bottlenecks.biggest_negative_delta ?? '—'}</Badge>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Experience Health</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {EXPERIENCE_META.map((meta) => {
              if (meta.key === 'latency_trend') return null
              const kpi = overview.experience_health[meta.key] as OverviewV3Kpi
              return (
                <Card key={meta.key} className="border">
                  <CardContent className="pt-4 space-y-1">
                    <div className="text-sm font-medium">{meta.title}</div>
                    <div className="text-xl font-semibold">{formatKpiValue(kpi.value, meta.unit)}</div>
                    <div className="text-xs text-muted-foreground">{kpi.numerator ?? '—'} / {kpi.denominator ?? '—'}</div>
                    <div className="text-xs text-muted-foreground">Δ {formatDelta(kpi.delta_vs_prev_pct)}</div>
                    <Badge variant={KPI_TRUST_VARIANT[kpi.trust_label]}>{kpi.trust_label}</Badge>
                    {kpi.reason && <div className="text-xs text-muted-foreground">{kpi.reason}</div>}
                  </CardContent>
                </Card>
              )
            })}
          </div>
          <div className="h-[180px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={overview.experience_health.latency_trend}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Area type="monotone" dataKey="median_time_to_preview_sec" stroke="#2563eb" fill="#2563eb33" name="Median sec" />
                <Area type="monotone" dataKey="p95_time_to_preview_sec" stroke="#f59e0b" fill="#f59e0b33" name="P95 sec" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Executive Summary</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p><span className="font-medium">Что происходит:</span> {overview.summary.what_is_happening}</p>
          <p><span className="font-medium">Главная проблема:</span> {overview.summary.main_problem}</p>
          <p><span className="font-medium">Что изменилось:</span> {overview.summary.change_vs_prev}</p>
        </CardContent>
      </Card>
    </div>
  )
}
