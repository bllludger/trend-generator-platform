import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { paymentsService } from '@/services/api'
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
import { Coins, DollarSign, ShoppingBag, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
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
  is_bank_transfer?: boolean
  payment_method?: 'stars' | 'yoomoney' | 'yookassa_link' | 'yookassa_unlock' | 'bank_transfer'
}

const DAYS_OPTIONS = [7, 30, 90]
const HISTORY_DAYS_OPTIONS = [
  { value: 7, label: '7 дн.' },
  { value: 30, label: '30 дн.' },
  { value: 90, label: '90 дн.' },
  { value: 0, label: 'Всё время' },
]

function formatStarsRub(stars: number, rate: number): string {
  return `${stars}⭐ (~${Math.round(stars * rate)} ₽)`
}

const PAYMENT_METHOD_OPTIONS = [
  { value: '', label: 'Все' },
  { value: 'stars', label: '⭐ Stars (Telegram)' },
  { value: 'yoomoney', label: '💳 ЮMoney' },
  { value: 'yookassa_link', label: '🔗 ЮKassa (пакеты)' },
  { value: 'yookassa_unlock', label: '🔓 ЮKassa (unlock)' },
  { value: 'bank_transfer', label: '🏦 Перевод на карту' },
]

export function PaymentsPage() {
  const [days, setDays] = useState(30)
  const [historyDays, setHistoryDays] = useState(30)
  const [page, setPage] = useState(1)
  const [paymentMethod, setPaymentMethod] = useState('')
  const [paymentToRefund, setPaymentToRefund] = useState<PaymentItem | null>(null)
  const pageSize = 20

  const historyParams = (() => {
    if (historyDays === 0) return {}
    const to = new Date()
    const from = new Date(to)
    from.setDate(from.getDate() - historyDays)
    return {
      date_from: from.toISOString().slice(0, 10),
      date_to: to.toISOString().slice(0, 10),
    }
  })()
  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['payments-history', historyParams],
    queryFn: () => paymentsService.getHistory({ ...historyParams, granularity: 'day' }),
  })
  const historySeries = historyData?.series ?? []
  const queryClient = useQueryClient()

  const refundMutation = useMutation({
    mutationFn: (paymentId: string) => paymentsService.refund(paymentId),
    onSuccess: () => {
      setPaymentToRefund(null)
      queryClient.invalidateQueries({ queryKey: ['payments-list'] })
      queryClient.invalidateQueries({ queryKey: ['payments-stats'] })
    },
  })

  type PaymentsStats = {
    total_stars?: number
    total_rub_yoomoney?: number
    revenue_rub_approx?: number
    revenue_rub_stars?: number
    revenue_usd_approx?: number
    total_payments?: number
    refunds?: number
    unique_buyers?: number
    conversion_rate_pct?: number
    star_to_rub?: number
    by_pack?: Array<{ pack_id: string; count: number; stars: number; rub?: number }>
  }
  type PaymentsListResponse = { items?: PaymentItem[]; page?: number; pages?: number; total?: number }

  const { data: stats, isLoading: statsLoading } = useQuery<PaymentsStats>({
    queryKey: ['payments-stats', days],
    queryFn: () => paymentsService.getStats(days) as Promise<PaymentsStats>,
  })

  const { data: list, isLoading: listLoading } = useQuery<PaymentsListResponse>({
    queryKey: ['payments-list', page, pageSize, paymentMethod],
    queryFn: () => paymentsService.list({
      page,
      page_size: pageSize,
      ...(paymentMethod ? { payment_method: paymentMethod } : {}),
    }) as Promise<PaymentsListResponse>,
  })
  const payments: PaymentItem[] = Array.isArray(list?.items) ? list.items : []

  if (statsLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-muted-foreground">Загрузка...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Платежи</h1>
        <p className="text-muted-foreground mt-2">
          Выручка: Stars (Telegram → Fragment/TON) и ЮMoney (рубли). Цены пакетов — в разделе <Link to="/payments/packs" className="text-primary hover:underline">Пакеты (цены)</Link>.
        </p>
      </div>

      {/* Период */}
      <div className="flex gap-2 items-center">
        <span className="text-sm text-muted-foreground">Период:</span>
        {DAYS_OPTIONS.map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={`px-3 py-1 rounded text-sm font-medium ${
              days === d
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted hover:bg-muted/80'
            }`}
          >
            {d} дн.
          </button>
        ))}
      </div>

      {/* Карточки */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Stars получено</CardTitle>
            <Coins className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatNumber(stats?.total_stars ?? 0)}</div>
            <p className="text-xs text-muted-foreground">
              за {days} дн. {stats?.revenue_rub_stars != null && stats.revenue_rub_stars > 0 && `(~${formatNumber(stats.revenue_rub_stars)} ₽)`}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">ЮMoney (₽)</CardTitle>
            <Coins className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatNumber(stats?.total_rub_yoomoney ?? 0)} ₽</div>
            <p className="text-xs text-muted-foreground">за {days} дн.</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Выручка (₽)</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatNumber(Math.round(stats?.revenue_rub_approx ?? 0))} ₽</div>
            <p className="text-xs text-muted-foreground">всего за {days} дн. (Stars + ЮMoney)</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Транзакций</CardTitle>
            <ShoppingBag className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatNumber(stats?.total_payments ?? 0)}</div>
            <p className="text-xs text-muted-foreground">Возвратов: {stats?.refunds ?? 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Покупателей</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatNumber(stats?.unique_buyers ?? 0)}</div>
            <p className="text-xs text-muted-foreground">Конверсия: {stats?.conversion_rate_pct ?? 0}%</p>
          </CardContent>
        </Card>
      </div>

      {/* По пакетам */}
      {stats?.by_pack && stats.by_pack.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>По пакетам</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {stats.by_pack.map((p: { pack_id: string; count: number; stars: number; rub?: number }) => (
                <Badge key={p.pack_id} variant="secondary" className="text-sm">
                  {p.pack_id}: {p.count} шт.
                  {p.stars > 0 && ` · ${formatStarsRub(p.stars, stats?.star_to_rub ?? 1.3)}`}
                  {p.rub != null && p.rub > 0 && ` · ${formatNumber(p.rub)} ₽`}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Исторический график: выручка и покупки */}
      <Card>
        <CardHeader>
          <CardTitle>История: выручка и покупки</CardTitle>
          <p className="text-sm text-muted-foreground">
            Выручка в рублях и количество транзакций по дням. Период — для графика.
          </p>
          <div className="flex gap-2 mt-3">
            {HISTORY_DAYS_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setHistoryDays(opt.value)}
                className={`px-3 py-1 rounded text-sm font-medium ${
                  historyDays === opt.value
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted hover:bg-muted/80'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          {historyLoading ? (
            <div className="text-muted-foreground py-8">Загрузка...</div>
          ) : historySeries.length === 0 ? (
            <div className="text-muted-foreground py-8">Нет данных за выбранный период.</div>
          ) : (
            <div className="h-[320px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={historySeries} margin={{ top: 5, right: 50, left: 0, bottom: 5 }}>
                  <defs>
                    <linearGradient id="paymentsRevenueGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.8} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0.1} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} className="text-muted-foreground" />
                  <YAxis
                    yAxisId="left"
                    tick={{ fontSize: 11 }}
                    className="text-muted-foreground"
                    tickFormatter={(v) => `${formatNumber(v)} ₽`}
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
                      borderRadius: '8px',
                    }}
                    formatter={(value: number, name: string) => {
                      if (name === 'Выручка, ₽') return [formatNumber(value) + ' ₽', name]
                      return [value, name]
                    }}
                    labelFormatter={(label) => `Дата: ${label}`}
                  />
                  <Legend wrapperStyle={{ fontSize: '12px' }} />
                  <Area
                    yAxisId="left"
                    type="monotone"
                    dataKey="revenue_rub"
                    stroke="#10b981"
                    fill="url(#paymentsRevenueGrad)"
                    name="Выручка, ₽"
                    strokeWidth={2}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="transactions_count"
                    name="Транзакций"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="unique_buyers"
                    name="Покупателей"
                    stroke="#f59e0b"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Таблица последних платежей */}
      <Card>
        <CardHeader>
          <CardTitle>Последние платежи</CardTitle>
          <p className="text-sm text-muted-foreground">
            Платежи записываются при successful_payment (Stars, ЮMoney) или после подтверждения перевода на карту.
          </p>
          <div className="flex gap-2 mt-3">
            {PAYMENT_METHOD_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => { setPaymentMethod(opt.value); setPage(1) }}
                className={`px-3 py-1 rounded text-sm font-medium ${
                  paymentMethod === opt.value
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted hover:bg-muted/80'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          {listLoading ? (
            <div className="text-muted-foreground py-8">Загрузка...</div>
          ) : payments.length === 0 ? (
            <div className="text-muted-foreground py-8">Платежей пока нет.</div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Дата</TableHead>
                    <TableHead>Способ</TableHead>
                    <TableHead>Пакет</TableHead>
                    <TableHead>Сумма</TableHead>
                    <TableHead>Фото</TableHead>
                    <TableHead>Пользователь</TableHead>
                    <TableHead>Статус</TableHead>
                    <TableHead className="w-[100px]">Действия</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {payments.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell className="text-muted-foreground text-sm">
                        {p.created_at ? new Date(p.created_at).toLocaleString('ru') : '—'}
                      </TableCell>
                      <TableCell>
                        {p.payment_method === 'bank_transfer' && (
                          <Badge variant="outline" className="text-xs">🏦 Перевод</Badge>
                        )}
                        {p.payment_method === 'yoomoney' && (
                          <Badge variant="secondary" className="text-xs">💳 ЮMoney</Badge>
                        )}
                        {p.payment_method === 'yookassa_link' && (
                          <Badge variant="secondary" className="text-xs">🔗 ЮKassa</Badge>
                        )}
                        {p.payment_method === 'yookassa_unlock' && (
                          <Badge variant="secondary" className="text-xs">🔓 ЮKassa unlock</Badge>
                        )}
                        {(p.payment_method === 'stars' || !p.payment_method) && (
                          <Badge variant="secondary" className="text-xs">⭐ Stars</Badge>
                        )}
                      </TableCell>
                      <TableCell>{p.pack_id}</TableCell>
                      <TableCell>
                        {(p.payment_method === 'yoomoney' || p.payment_method === 'yookassa_link' || p.payment_method === 'yookassa_unlock' || p.payment_method === 'bank_transfer') && p.amount_kopecks != null ? (
                          `${formatNumber(p.amount_kopecks / 100)} ₽`
                        ) : (
                          formatStarsRub(Number(p.stars_amount), Number(stats?.star_to_rub ?? 1.3))
                        )}
                      </TableCell>
                      <TableCell>{Number(p.tokens_granted)}</TableCell>
                      <TableCell>
                        {p.telegram_id && (
                          <a
                            href={`https://t.me/${p.username || p.telegram_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary hover:underline"
                          >
                            {p.username ? `@${p.username}` : p.telegram_id}
                          </a>
                        )}
                        {!p.telegram_id && '—'}
                      </TableCell>
                      <TableCell>
                        <Badge variant={p.status === 'refunded' ? 'destructive' : 'default'}>
                          {p.status === 'refunded' ? 'Возврат' : p.status === 'completed' ? 'Оплачен' : String(p.status)}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {p.status !== 'refunded' && p.pack_id !== 'unlock_tokens' && p.payment_method === 'stars' && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setPaymentToRefund(p)}
                          >
                            Возврат
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
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
              {paymentToRefund?.pack_id === 'unlock' ? (
                <>
                  Возврат Stars. Файл пользователю уже отправлен, доступ не отзывается.
                </>
              ) : (
                <>Будет выполнен возврат Stars через Telegram. Фото будут списаны с баланса пользователя.</>
              )}
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
