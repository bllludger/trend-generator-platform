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
import { Pagination } from '@/components/Pagination'
import { formatNumber } from '@/lib/utils'

type PaymentItem = {
  id: string
  pack_id: string
  stars_amount: number
  tokens_granted: number
  status: string
  created_at?: string
  telegram_id?: string
  username?: string
  is_bank_transfer?: boolean
}

const DAYS_OPTIONS = [7, 30, 90]

function formatStarsRub(stars: number, rate: number): string {
  return `${stars}⭐ (~${Math.round(stars * rate)} ₽)`
}

const PAYMENT_METHOD_OPTIONS = [
  { value: '', label: 'Все' },
  { value: 'stars', label: '⭐ Stars (Telegram)' },
  { value: 'bank_transfer', label: '💳 Перевод на карту' },
]

export function PaymentsPage() {
  const [days, setDays] = useState(30)
  const [page, setPage] = useState(1)
  const [paymentMethod, setPaymentMethod] = useState('')
  const [paymentToRefund, setPaymentToRefund] = useState<PaymentItem | null>(null)
  const pageSize = 20
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
    revenue_rub_approx?: number
    revenue_usd_approx?: number
    total_payments?: number
    refunds?: number
    unique_buyers?: number
    conversion_rate_pct?: number
    star_to_rub?: number
    by_pack?: Array<{ pack_id: string; count: number; stars: number }>
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
        <h1 className="text-3xl font-bold tracking-tight">Платежи (Stars)</h1>
        <p className="text-muted-foreground mt-2">
          Выручка по Telegram Stars. Stars зачисляются на баланс владельца бота в Telegram (вывод через Fragment → TON).
          Цены пакетов можно менять в разделе <Link to="/packs" className="text-primary hover:underline">Пакеты (цены)</Link>.
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
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Stars получено</CardTitle>
            <Coins className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatNumber(stats?.total_stars ?? 0)}</div>
            <p className="text-xs text-muted-foreground">
              за {days} дн. {stats?.revenue_rub_approx != null && `(~${formatNumber(stats.revenue_rub_approx)} ₽)`}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">≈ Выручка (USD)</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${(stats?.revenue_usd_approx ?? 0).toFixed(2)}</div>
            <p className="text-xs text-muted-foreground">~$0.013 за 1 Star · 1⭐ ≈ {stats?.star_to_rub ?? 1.3} ₽</p>
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
              {stats.by_pack.map((p: { pack_id: string; count: number; stars: number }) => (
                <Badge key={p.pack_id} variant="secondary" className="text-sm">
                  {p.pack_id}: {p.count} шт. · {formatStarsRub(p.stars, stats?.star_to_rub ?? 1.3)}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Таблица последних платежей */}
      <Card>
        <CardHeader>
          <CardTitle>Последние платежи</CardTitle>
          <p className="text-sm text-muted-foreground">
            Все платежи записываются в БД при successful_payment. Баланс Stars — на аккаунте владельца бота в Telegram.
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
                    <TableHead>Stars</TableHead>
                    <TableHead>Токены</TableHead>
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
                        {p.is_bank_transfer ? (
                          <Badge variant="outline" className="text-xs">💳 Перевод</Badge>
                        ) : (
                          <Badge variant="secondary" className="text-xs">⭐ Stars</Badge>
                        )}
                      </TableCell>
                      <TableCell>{p.pack_id}</TableCell>
                      <TableCell>{formatStarsRub(Number(p.stars_amount), Number(stats?.star_to_rub ?? 1.3))}</TableCell>
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
                          {String(p.status)}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {p.status !== 'refunded' && p.pack_id !== 'unlock_tokens' && !p.is_bank_transfer && (
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
                <>Будет выполнен возврат Stars через Telegram. Токены будут списаны с баланса пользователя.</>
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
