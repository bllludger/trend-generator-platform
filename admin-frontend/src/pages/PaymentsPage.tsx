import { useMemo, useState } from 'react'
import type { ElementType } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { paymentsService, telemetryService } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
  Activity,
  BarChart3,
  CreditCard,
  DollarSign,
  MousePointerClick,
  RefreshCw,
  Repeat,
  ShoppingBag,
  Users,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ProductMetricsV2 } from '@/types'
import { Pagination } from '@/components/Pagination'
import { formatNumber } from '@/lib/utils'

type PaymentItem = {
  id: string
  pack_id: string
  stars_amount: number
  amount_kopecks?: number | null
  tokens_granted: number
  status: string
  created_at?: string
  telegram_id?: string
  username?: string
  payment_method?: 'stars' | 'yoomoney' | 'yookassa_link' | 'yookassa_unlock' | 'bank_transfer'
}

type PaymentsStats = {
  all_time?: boolean
  days?: number | null
  revenue_rub_approx?: number
  total_payments?: number
  refunds?: number
  unique_buyers?: number
  conversion_rate_pct?: number
  star_to_rub?: number
  by_pack?: Array<{ pack_id: string; count: number; stars: number; rub?: number }>
}

type PaymentsListResponse = { items?: PaymentItem[]; page?: number; pages?: number; total?: number }

type PaymentSortKey = 'created_at' | 'amount' | 'pack_id' | 'status'
type SortDirection = 'asc' | 'desc'

const PAYMENT_METHOD_OPTIONS = [
  { value: 'all', label: 'Все методы' },
  { value: 'yoomoney', label: 'ЮMoney' },
  { value: 'yookassa_link', label: 'ЮKassa (пакеты)' },
  { value: 'yookassa_unlock', label: 'ЮKassa (unlock)' },
  { value: 'bank_transfer', label: 'Перевод на карту' },
  { value: 'stars', label: 'Telegram' },
]

const PAYMENT_SORT_OPTIONS: Array<{ value: PaymentSortKey; label: string }> = [
  { value: 'created_at', label: 'По дате' },
  { value: 'amount', label: 'По сумме' },
  { value: 'pack_id', label: 'По пакету' },
  { value: 'status', label: 'По статусу' },
]

const FUNNEL_STEPS: Array<{ key: string; label: string }> = [
  { key: 'bot_started', label: 'Старт' },
  { key: 'photo_uploaded', label: 'Фото загружено' },
  { key: 'take_preview_ready', label: 'Варианты готовы' },
  { key: 'pay_initiated', label: 'Нажата оплата' },
  { key: 'pay_success', label: 'Оплата успешна' },
]

function formatRub(value: number): string {
  return new Intl.NumberFormat('ru-RU', {
    maximumFractionDigits: value < 1000 ? 2 : 0,
  }).format(value)
}

function formatDateTime(value?: string): string {
  if (!value) return '—'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString('ru-RU')
}

function formatShortDate(value: string): string {
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' })
}

function getPaymentMethodLabel(method?: PaymentItem['payment_method']): string {
  if (method === 'bank_transfer') return 'Перевод'
  if (method === 'yoomoney') return 'ЮMoney'
  if (method === 'yookassa_link') return 'ЮKassa'
  if (method === 'yookassa_unlock') return 'ЮKassa unlock'
  return 'Telegram'
}

function getPaymentAmountRub(payment: PaymentItem, starToRub: number): number {
  if (payment.amount_kopecks != null && payment.amount_kopecks > 0) {
    return payment.amount_kopecks / 100
  }
  return Number(payment.stars_amount || 0) * starToRub
}

function getStatusLabel(status: string): string {
  if (status === 'completed') return 'Оплачен'
  if (status === 'refunded') return 'Возврат'
  return status
}

interface MetricCardProps {
  title: string
  value: string
  subtitle: string
  icon: ElementType
}

function MetricCard({ title, value, subtitle, icon: Icon }: MetricCardProps) {
  return (
    <Card className="border-border/70 shadow-sm">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <div className="rounded-full border border-border/80 bg-muted/30 p-2">
          <Icon className="h-4 w-4 text-muted-foreground" />
        </div>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-semibold tracking-tight">{value}</div>
        <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
      </CardContent>
    </Card>
  )
}

export function PaymentsPage() {
  const [page, setPage] = useState(1)
  const [paymentMethod, setPaymentMethod] = useState('all')
  const [sortBy, setSortBy] = useState<PaymentSortKey>('created_at')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [paymentToRefund, setPaymentToRefund] = useState<PaymentItem | null>(null)
  const pageSize = 20
  const queryClient = useQueryClient()

  const {
    data: stats,
    isLoading: statsLoading,
    refetch: refetchStats,
  } = useQuery<PaymentsStats>({
    queryKey: ['payments-stats', 'all-time'],
    queryFn: () => paymentsService.getStats({ allTime: true }) as Promise<PaymentsStats>,
  })

  const {
    data: historyData,
    isLoading: historyLoading,
    refetch: refetchHistory,
  } = useQuery({
    queryKey: ['payments-history', 'all-time'],
    queryFn: () => paymentsService.getHistory({ granularity: 'day' }),
  })

  const {
    data: productFunnel,
    isLoading: funnelLoading,
    refetch: refetchFunnel,
  } = useQuery({
    queryKey: ['telemetry-product-funnel', 'all-time', 'payments'],
    queryFn: () => telemetryService.getProductFunnel(undefined, true),
  })

  const {
    data: productMetrics,
    isLoading: metricsLoading,
    refetch: refetchMetrics,
  } = useQuery<ProductMetricsV2>({
    queryKey: ['telemetry-product-metrics-v2', 'all-time', 'payments'],
    queryFn: () => telemetryService.getProductMetricsV2(undefined, true),
  })

  const {
    data: list,
    isLoading: listLoading,
    refetch: refetchList,
  } = useQuery<PaymentsListResponse>({
    queryKey: ['payments-list', page, pageSize, paymentMethod],
    queryFn: () =>
      paymentsService.list({
        page,
        page_size: pageSize,
        ...(paymentMethod !== 'all' ? { payment_method: paymentMethod } : {}),
      }) as Promise<PaymentsListResponse>,
  })

  const refundMutation = useMutation({
    mutationFn: (paymentId: string) => paymentsService.refund(paymentId),
    onSuccess: () => {
      setPaymentToRefund(null)
      queryClient.invalidateQueries({ queryKey: ['payments-list'] })
      queryClient.invalidateQueries({ queryKey: ['payments-stats'] })
      queryClient.invalidateQueries({ queryKey: ['payments-history'] })
    },
  })

  const historySeries = historyData?.series ?? []
  const payments: PaymentItem[] = Array.isArray(list?.items) ? list.items : []
  const starToRub = Number(stats?.star_to_rub ?? 1.3)

  const totalRevenueRub = Number(stats?.revenue_rub_approx ?? 0)
  const totalPayments = Number(stats?.total_payments ?? 0)
  const totalRefunds = Number(stats?.refunds ?? 0)
  const uniqueBuyers = Number(stats?.unique_buyers ?? 0)

  const aovRub = totalPayments > 0 ? totalRevenueRub / totalPayments : 0
  const refundRatePct = totalPayments > 0 ? (totalRefunds / totalPayments) * 100 : 0

  const funnelCounts = productFunnel?.funnel_counts ?? {}
  const startedUsers = Number(funnelCounts.bot_started ?? 0)
  const photoUploadedUsers = Number(funnelCounts.photo_uploaded ?? 0)
  const previewReadyUsers = Number(funnelCounts.take_preview_ready ?? 0)
  const payInitiatedUsers = Number(funnelCounts.pay_initiated ?? 0)
  const paySuccessUsers = Number(funnelCounts.pay_success ?? 0)

  const dropAfterPhoto = Math.max(0, photoUploadedUsers - previewReadyUsers)
  const payFromInitiatedPct = payInitiatedUsers > 0 ? (paySuccessUsers / payInitiatedUsers) * 100 : 0
  const previewToPayPct = Number(productMetrics?.preview_to_pay_pct ?? 0)
  const repeatPurchasePct = Number(productMetrics?.repeat_purchase_rate_pct ?? 0)
  const avgStartToResultSec = Number(productMetrics?.avg_time_start_to_result_sec ?? 0)

  const sortedPayments = useMemo(() => {
    const rows = [...payments]
    rows.sort((a, b) => {
      let diff = 0
      if (sortBy === 'created_at') {
        diff = (new Date(a.created_at || 0).getTime() || 0) - (new Date(b.created_at || 0).getTime() || 0)
      } else if (sortBy === 'amount') {
        diff = getPaymentAmountRub(a, starToRub) - getPaymentAmountRub(b, starToRub)
      } else if (sortBy === 'pack_id') {
        diff = a.pack_id.localeCompare(b.pack_id, 'ru')
      } else {
        diff = a.status.localeCompare(b.status, 'ru')
      }
      return sortDirection === 'asc' ? diff : -diff
    })
    return rows
  }, [payments, sortBy, sortDirection, starToRub])

  const byPack = useMemo(() => {
    return [...(stats?.by_pack ?? [])]
      .map((item) => {
        const starsRub = Number(item.stars || 0) * starToRub
        const directRub = Number(item.rub || 0)
        return {
          pack_id: item.pack_id,
          count: Number(item.count || 0),
          revenue_rub: Math.round((starsRub + directRub) * 100) / 100,
        }
      })
      .sort((a, b) => {
        const revDiff = b.revenue_rub - a.revenue_rub
        if (revDiff !== 0) return revDiff
        return b.count - a.count
      })
  }, [stats?.by_pack, starToRub])

  const isRefreshing = statsLoading || historyLoading || funnelLoading || metricsLoading

  const refreshAll = async () => {
    await Promise.all([refetchStats(), refetchHistory(), refetchFunnel(), refetchMetrics(), refetchList()])
  }

  if (statsLoading && !stats) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="text-muted-foreground">Загрузка...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
            <CreditCard className="h-7 w-7 text-muted-foreground" />
            Платежная аналитика
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Единый экран коммерческой воронки и выручки за весь период. Управление пакетами доступно в разделе{' '}
            <Link to="/payments/packs" className="text-primary hover:underline">
              Пакеты
            </Link>
            .
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="secondary">Период: всё время</Badge>
          <Button variant="outline" size="icon" onClick={refreshAll} disabled={isRefreshing}>
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="Выручка"
          value={`${formatRub(totalRevenueRub)} ₽`}
          subtitle="Подтвержденные платежи за всё время"
          icon={DollarSign}
        />
        <MetricCard
          title="Покупатели"
          value={formatNumber(uniqueBuyers)}
          subtitle="Уникальные пользователи с оплатой"
          icon={Users}
        />
        <MetricCard
          title="Транзакции"
          value={formatNumber(totalPayments)}
          subtitle={`Возвратов: ${formatNumber(totalRefunds)}`}
          icon={ShoppingBag}
        />
        <MetricCard
          title="Средний чек"
          value={`${formatRub(aovRub)} ₽`}
          subtitle="Average order value"
          icon={BarChart3}
        />
        <MetricCard
          title="Preview → Pay"
          value={`${previewToPayPct.toFixed(1)}%`}
          subtitle="Конверсия из готовых вариантов в оплату"
          icon={MousePointerClick}
        />
        <MetricCard
          title="Оплата после клика"
          value={`${payFromInitiatedPct.toFixed(1)}%`}
          subtitle="Pay success / Pay initiated"
          icon={Activity}
        />
        <MetricCard
          title="Повторные покупки"
          value={`${repeatPurchasePct.toFixed(1)}%`}
          subtitle="Доля пользователей с 2+ оплатами"
          icon={Repeat}
        />
        <MetricCard
          title="Доля возвратов"
          value={`${refundRatePct.toFixed(1)}%`}
          subtitle={
            avgStartToResultSec > 0
              ? `Среднее время Start → Result: ${(avgStartToResultSec / 60).toFixed(1)} мин`
              : 'Среднее время Start → Result: —'
          }
          icon={RefreshCw}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="border-border/70 shadow-sm">
          <CardHeader>
            <CardTitle>Воронка оплаты</CardTitle>
            <p className="text-sm text-muted-foreground">
              Ключевые шаги пользователя в оплате за всё время.
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            {FUNNEL_STEPS.map((step) => {
              const value = Number(funnelCounts[step.key] ?? 0)
              const percent = startedUsers > 0 ? Math.round((value / startedUsers) * 100) : 0
              return (
                <div key={step.key} className="space-y-1.5">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">{step.label}</span>
                    <span className="font-medium text-foreground">{formatNumber(value)} · {percent}%</span>
                  </div>
                  <div className="h-2 rounded-full bg-muted/60">
                    <div
                      className="h-2 rounded-full bg-primary transition-all"
                      style={{ width: `${Math.max(2, Math.min(percent, 100))}%` }}
                    />
                  </div>
                </div>
              )
            })}
            <div className="grid gap-2 pt-2 sm:grid-cols-2">
              <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                <p className="text-xs text-muted-foreground">Нажали кнопку оплаты</p>
                <p className="mt-1 text-xl font-semibold">{formatNumber(payInitiatedUsers)}</p>
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                <p className="text-xs text-muted-foreground">Не дошли после загрузки фото</p>
                <p className="mt-1 text-xl font-semibold">{formatNumber(dropAfterPhoto)}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/70 shadow-sm">
          <CardHeader>
            <CardTitle>Пакеты и выручка</CardTitle>
            <p className="text-sm text-muted-foreground">
              Распределение по пакетам без дублей и лишних блоков.
            </p>
          </CardHeader>
          <CardContent>
            {byPack.length === 0 ? (
              <div className="py-8 text-sm text-muted-foreground">Нет платежей для отображения.</div>
            ) : (
              <div className="space-y-3">
                {byPack.map((row) => {
                  const revenueShare = totalRevenueRub > 0 ? Math.round((row.revenue_rub / totalRevenueRub) * 100) : 0
                  return (
                    <div key={row.pack_id} className="rounded-lg border border-border/70 p-3">
                      <div className="mb-2 flex items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-foreground">{row.pack_id}</p>
                          <p className="text-xs text-muted-foreground">{formatNumber(row.count)} оплат</p>
                        </div>
                        <div className="text-right">
                          <p className="text-sm font-semibold">{formatRub(row.revenue_rub)} ₽</p>
                          <p className="text-xs text-muted-foreground">{revenueShare}% доля</p>
                        </div>
                      </div>
                      <div className="h-2 rounded-full bg-muted/60">
                        <div className="h-2 rounded-full bg-emerald-500" style={{ width: `${Math.max(2, revenueShare)}%` }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="border-border/70 shadow-sm">
        <CardHeader>
          <CardTitle>Динамика выручки и оплат</CardTitle>
          <p className="text-sm text-muted-foreground">
            Современный комбинированный график за весь период: выручка, количество транзакций и покупателей.
          </p>
        </CardHeader>
        <CardContent>
          {historyLoading ? (
            <div className="py-8 text-muted-foreground">Загрузка...</div>
          ) : historySeries.length === 0 ? (
            <div className="py-8 text-muted-foreground">История платежей пока пустая.</div>
          ) : (
            <div className="h-[360px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={historySeries} margin={{ top: 8, right: 16, left: 4, bottom: 8 }}>
                  <defs>
                    <linearGradient id="paymentsRevenueGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#2563eb" stopOpacity={0.36} />
                      <stop offset="95%" stopColor="#2563eb" stopOpacity={0.04} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(value: string) => formatShortDate(value)}
                    className="text-muted-foreground"
                  />
                  <YAxis
                    yAxisId="left"
                    tick={{ fontSize: 11 }}
                    className="text-muted-foreground"
                    tickFormatter={(value) => `${formatNumber(Math.round(Number(value)))} ₽`}
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tick={{ fontSize: 11 }}
                    className="text-muted-foreground"
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'hsl(var(--background))',
                      border: '1px solid hsl(var(--border))',
                      borderRadius: '10px',
                    }}
                    labelFormatter={(label) => formatDateTime(label)}
                    formatter={(value: number, name: string) => {
                      if (name === 'Выручка') return [`${formatRub(value)} ₽`, name]
                      return [formatNumber(value), name]
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Area
                    yAxisId="left"
                    type="monotone"
                    dataKey="revenue_rub"
                    stroke="#2563eb"
                    fill="url(#paymentsRevenueGradient)"
                    name="Выручка"
                    strokeWidth={2.2}
                    isAnimationActive={false}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="transactions_count"
                    name="Транзакции"
                    stroke="#16a34a"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="unique_buyers"
                    name="Покупатели"
                    stroke="#f59e0b"
                    strokeWidth={2}
                    dot={false}
                    strokeDasharray="5 3"
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-border/70 shadow-sm">
        <CardHeader>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <CardTitle>Транзакции</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                Чистая таблица оплат с фильтром по методу и сортировкой.
              </p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Select
                value={paymentMethod}
                onValueChange={(value) => {
                  setPaymentMethod(value)
                  setPage(1)
                }}
              >
                <SelectTrigger className="w-[220px]">
                  <SelectValue placeholder="Метод оплаты" />
                </SelectTrigger>
                <SelectContent>
                  {PAYMENT_METHOD_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select value={sortBy} onValueChange={(value) => setSortBy(value as PaymentSortKey)}>
                <SelectTrigger className="w-[210px]">
                  <SelectValue placeholder="Сортировка" />
                </SelectTrigger>
                <SelectContent>
                  {PAYMENT_SORT_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Button
                variant="outline"
                onClick={() => setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))}
                className="min-w-[130px]"
              >
                {sortDirection === 'asc' ? 'По возрастанию' : 'По убыванию'}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {listLoading ? (
            <div className="py-8 text-muted-foreground">Загрузка...</div>
          ) : sortedPayments.length === 0 ? (
            <div className="py-8 text-muted-foreground">Платежей пока нет.</div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Дата</TableHead>
                    <TableHead>Пользователь</TableHead>
                    <TableHead>Пакет</TableHead>
                    <TableHead>Метод</TableHead>
                    <TableHead>Сумма</TableHead>
                    <TableHead>Токены</TableHead>
                    <TableHead>Статус</TableHead>
                    <TableHead className="w-[120px]">Действия</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedPayments.map((payment) => {
                    const amountRub = getPaymentAmountRub(payment, starToRub)
                    return (
                      <TableRow key={payment.id}>
                        <TableCell className="text-sm text-muted-foreground">
                          {formatDateTime(payment.created_at)}
                        </TableCell>
                        <TableCell>
                          {payment.telegram_id ? (
                            <a
                              href={`https://t.me/${payment.username || payment.telegram_id}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="font-medium text-primary hover:underline"
                            >
                              {payment.username ? `@${payment.username}` : payment.telegram_id}
                            </a>
                          ) : (
                            '—'
                          )}
                        </TableCell>
                        <TableCell className="font-medium">{payment.pack_id}</TableCell>
                        <TableCell>
                          <Badge variant="outline">{getPaymentMethodLabel(payment.payment_method)}</Badge>
                        </TableCell>
                        <TableCell className="font-medium">{formatRub(amountRub)} ₽</TableCell>
                        <TableCell>{formatNumber(Number(payment.tokens_granted || 0))}</TableCell>
                        <TableCell>
                          <Badge variant={payment.status === 'refunded' ? 'destructive' : 'secondary'}>
                            {getStatusLabel(payment.status)}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {payment.status !== 'refunded' && payment.pack_id !== 'unlock_tokens' && payment.payment_method === 'stars' && (
                            <Button variant="outline" size="sm" onClick={() => setPaymentToRefund(payment)}>
                              Возврат
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>

              {list && (list.pages ?? 0) > 1 && (
                <Pagination
                  currentPage={page}
                  totalPages={list.pages ?? 1}
                  onPageChange={setPage}
                />
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!paymentToRefund} onOpenChange={(open) => !open && setPaymentToRefund(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Подтвердить возврат</DialogTitle>
            <DialogDescription>
              Будет выполнен возврат через Telegram. Проверьте, что это действительно необходимо.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPaymentToRefund(null)}>
              Отмена
            </Button>
            <Button
              variant="destructive"
              disabled={refundMutation.isPending}
              onClick={() => paymentToRefund && refundMutation.mutate(paymentToRefund.id)}
            >
              {refundMutation.isPending ? 'Выполняется…' : 'Выполнить возврат'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
