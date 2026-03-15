import { Component, useState, useEffect, useRef, type ReactNode } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { usersService, packsService, type UserDetailSession, type UserDetailPayment } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDateShort, formatNumber } from '@/lib/utils'

/** Генерирует уникальный ключ для идемпотентности (работает без crypto.randomUUID, в т.ч. по HTTP). */
function generateIdempotencyKey(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
    if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
      const buf = new Uint8Array(16)
      crypto.getRandomValues(buf)
      buf[6] = (buf[6]! & 0x0f) | 0x40
      buf[8] = (buf[8]! & 0x3f) | 0x80
      const hex = [...buf].map((b) => b.toString(16).padStart(2, '0')).join('')
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
    }
  } catch {
    // ignore
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`
}

/** Безопасная короткая дата: null/undefined/Invalid Date → '—' */
function safeDateShort(value: string | Date | null | undefined): string {
  if (value == null) return '—'
  const t = new Date(value).getTime()
  if (Number.isNaN(t)) return '—'
  return formatDateShort(value)
}
import {
  User as UserIcon,
  Package,
  CreditCard,
  ChevronRight,
  Shield,
  Ban,
  Gift,
} from 'lucide-react'
import { toast } from 'sonner'

class UserDetailErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean; error: Error | null }
> {
  state = { hasError: false, error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error) {
    this.setState({ error })
  }

  render() {
    if (this.state.hasError) {
      const err = this.state.error
      const errMsg = err?.message ?? (typeof err === 'string' ? err : 'Неизвестная ошибка')
      return (
        <div className="space-y-4 p-6">
          <p className="text-destructive">Ошибка при отображении карточки пользователя</p>
          <p className="text-sm text-muted-foreground font-mono max-w-2xl break-words" title={err?.stack}>
            {errMsg}
          </p>
          <Button variant="outline" onClick={() => this.setState({ hasError: false, error: null })}>
            Попробовать снова
          </Button>
          <Button variant="link" asChild>
            <Link to="/users">К списку</Link>
          </Button>
        </div>
      )
    }
    return this.props.children
  }
}

export function UserDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [grantOpen, setGrantOpen] = useState(false)
  const [grantPackId, setGrantPackId] = useState('')
  const [grantMessage, setGrantMessage] = useState('')
  const [resetLimitsOpen, setResetLimitsOpen] = useState(false)
  const grantIdempotencyKeyRef = useRef<string | null>(null)

  const { data: user, isLoading, isError, error: queryError, refetch } = useQuery({
    queryKey: ['user-detail', id],
    queryFn: () => usersService.getDetail(id!),
    enabled: !!id,
  })

  const { data: packs = [] } = useQuery({
    queryKey: ['packs'],
    queryFn: () => packsService.list(),
    enabled: grantOpen,
  })

  const grantMutation = useMutation({
    mutationFn: (body: { pack_id: string; activation_message?: string | null }) =>
      usersService.grantPack(id!, body, grantIdempotencyKeyRef.current ?? undefined),
    onSuccess: () => {
      setGrantOpen(false)
      setGrantPackId('')
      setGrantMessage('')
      refetch()
      toast.success('Пакет выдан')
    },
    onError: (err: unknown) => {
      const ax = err as { response?: { data?: { detail?: string | Array<{ msg?: string }> }; status?: number }; message?: string }
      const detail = ax?.response?.data?.detail
      const msg =
        (typeof detail === 'string' && detail) ||
        (Array.isArray(detail) && detail.length > 0 && detail[0]?.msg) ||
        ax?.message ||
        'Ошибка'
      toast.error(String(msg))
    },
  })

  const handleGrantSubmit = () => {
    const packId = (grantPackId ?? '').trim()
    if (!packId) {
      toast.error('Выберите пакет')
      return
    }
    grantMutation.mutate({
      pack_id: packId,
      activation_message: (grantMessage ?? '').trim() || undefined,
    })
  }

  const resetLimitsMutation = useMutation({
    mutationFn: () => usersService.resetLimits(id!),
    onSuccess: () => {
      setResetLimitsOpen(false)
      refetch()
      toast.success('Лимиты сброшены')
    },
    onError: (err: unknown) => {
      const ax = err as { response?: { data?: { detail?: string | Array<{ msg?: string }> }; status?: number }; message?: string }
      const detail = ax?.response?.data?.detail
      const msg =
        (typeof detail === 'string' && detail) ||
        (Array.isArray(detail) && detail.length > 0 && detail[0]?.msg) ||
        ax?.message ||
        'Ошибка'
      toast.error(String(msg))
    },
  })

  const packList = Array.isArray(packs) ? packs : []
  const enabledPacks = packList.filter((p: { enabled?: boolean }) => p.enabled !== false)

  useEffect(() => {
    if (!grantOpen) {
      setGrantPackId('')
      return
    }
    if (enabledPacks.length === 0) return
    setGrantPackId((current) => {
      if (current !== '') return current
      const defaultPack = enabledPacks.find((p: { is_trial?: boolean }) => !p.is_trial)
      return (defaultPack && defaultPack.id) ? String(defaultPack.id) : ''
    })
  }, [grantOpen, enabledPacks])

  if (!id) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <p className="text-muted-foreground">Не указан ID пользователя</p>
        <Button variant="link" asChild>
          <Link to="/users">К списку</Link>
        </Button>
      </div>
    )
  }

  if (isError) {
    const err = queryError as { response?: { data?: { detail?: string | Array<{ msg?: string }> }; status?: number }; message?: string } | undefined
    const detail = err?.response?.data?.detail
    const errorMsg =
      (typeof detail === 'string' && detail) ||
      (Array.isArray(detail) && detail.length > 0 && detail[0]?.msg) ||
      err?.message
    return (
      <div className="space-y-4">
        <p className="text-destructive">Не удалось загрузить пользователя</p>
        {errorMsg && (
          <p className="text-sm text-muted-foreground max-w-md">{String(errorMsg)}</p>
        )}
        <Button variant="outline" onClick={() => refetch()}>
          Повторить
        </Button>
        <Button variant="link" asChild>
          <Link to="/users">К списку</Link>
        </Button>
      </div>
    )
  }

  if (isLoading || !user) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-64 animate-pulse rounded bg-muted" />
        <div className="h-48 animate-pulse rounded-lg bg-muted" />
      </div>
    )
  }

  if (typeof user !== 'object' || !('id' in user)) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">Неверный ответ сервера</p>
        <Button variant="outline" onClick={() => refetch()}>
          Повторить
        </Button>
        <Button variant="link" asChild>
          <Link to="/users">К списку</Link>
        </Button>
      </div>
    )
  }

  const displayName =
    user.telegram_username
      ? `@${user.telegram_username}`
      : [user.telegram_first_name, user.telegram_last_name].filter(Boolean).join(' ') || user.telegram_id || user.id || '—'

  const sessions = Array.isArray(user.sessions) ? user.sessions : []
  const payments = Array.isArray(user.payments) ? user.payments : []

  return (
    <UserDetailErrorBoundary>
    <div className="space-y-6">
      {/* Breadcrumbs */}
      <nav className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link to="/users" className="hover:text-foreground">
          Пользователи
        </Link>
        <ChevronRight className="h-4 w-4" />
        <span className="text-foreground">{displayName}</span>
      </nav>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {displayName}
          </h1>
          <p className="font-mono text-sm text-muted-foreground">{user.telegram_id}</p>
        </div>
        <Button
          onClick={() => {
            grantIdempotencyKeyRef.current = generateIdempotencyKey()
            setGrantOpen(true)
          }}
        >
          <Gift className="mr-2 h-4 w-4" />
          Выдать пакет
        </Button>
      </div>

      {/* Profile */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <UserIcon className="h-4 w-4" />
            Профиль
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <span className="text-muted-foreground">Username:</span>{' '}
              {user.telegram_username ? `@${user.telegram_username}` : '—'}
            </div>
            <div>
              <span className="text-muted-foreground">Имя:</span>{' '}
              {[user.telegram_first_name, user.telegram_last_name].filter(Boolean).join(' ') || '—'}
            </div>
            <div>
              <span className="text-muted-foreground">Регистрация:</span>{' '}
              {safeDateShort(user.created_at)}
            </div>
            <div title="По последней задаче (Job) или снимку (Take)">
              <span className="text-muted-foreground">Последняя активность:</span>{' '}
              {safeDateShort(user.last_active)}
            </div>
            <div>
              <span className="text-muted-foreground">Модератор:</span>{' '}
              {user.is_moderator ? 'Да' : 'Нет'}
            </div>
            {(user.is_banned || user.is_suspended) && (
              <div className="flex items-center gap-2 text-warning">
                {user.is_banned && <Ban className="h-4 w-4" />}
                {user.is_suspended && <Shield className="h-4 w-4" />}
                <span>
                  {user.is_banned && 'Заблокирован'}
                  {user.is_banned && user.is_suspended && ' · '}
                  {user.is_suspended && 'Приостановлен'}
                </span>
              </div>
            )}
            {user.rate_limit_per_hour != null && (
              <div>
                <span className="text-muted-foreground">Лимит/час:</span> {user.rate_limit_per_hour}
              </div>
            )}
            {user.admin_notes && (
              <div className="sm:col-span-2">
                <span className="text-muted-foreground">Заметки:</span> {user.admin_notes}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Balances */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <CreditCard className="h-4 w-4" />
              Балансы и лимиты
            </CardTitle>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setResetLimitsOpen(true)}
              disabled={resetLimitsMutation.isPending}
            >
              Сбросить лимиты
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <span className="text-muted-foreground">Токены:</span>{' '}
              <span className="font-mono font-medium">
                {user.token_balance != null ? formatNumber(user.token_balance) : '—'}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Пробный тариф:</span>{' '}
              {user.trial_purchased ? 'Использован' : 'Нет'}
            </div>
            <div
              title="Один бесплатный снимок на аккаунт; при 0 из 1 в боте можно получить новую free_preview-сессию"
            >
              <span className="text-muted-foreground">Бесплатное фото (аккаунт):</span>{' '}
              {typeof user.free_takes_used === 'number'
                ? user.free_takes_used >= 1
                  ? 'исчерпано'
                  : `использовано ${user.free_takes_used} из 1`
                : '—'}
            </div>
            <div>
              <span className="text-muted-foreground">Беспл. генерации:</span>{' '}
              {(user.free_generations_used ?? 0)} / {(user.free_generations_limit != null ? user.free_generations_limit : '—')}
            </div>
            <div>
              <span className="text-muted-foreground">Копия:</span>{' '}
              {(user.copy_generations_used ?? 0)} / {(user.copy_generations_limit != null ? user.copy_generations_limit : '—')}
            </div>
            <div>
              <span className="text-muted-foreground">4К (оплач.):</span>{' '}
              {formatNumber(user.hd_paid_balance ?? 0)}
            </div>
            <div>
              <span className="text-muted-foreground">4К (промо):</span>{' '}
              {formatNumber(user.hd_promo_balance ?? 0)}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Current tariff */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Package className="h-4 w-4" />
            Текущий тариф
          </CardTitle>
        </CardHeader>
        <CardContent>
          {user.active_session ? (
            <div className="space-y-2 text-sm">
              <p>
                <span className="font-medium">
                  {user.active_session.pack_id === 'free_preview' ? 'Бесплатный' : (user.active_session.pack_name ?? '—')}
                </span>{' '}
                <span className="text-muted-foreground">({user.active_session.pack_id})</span>
              </p>
              <p title="По текущей сессии; для free_preview лимит 1 фото">
                Осталось фото: <span className="font-mono">{user.active_session.takes_remaining ?? 0}</span>
                {user.active_session.takes_limit != null && (
                  <span className="text-muted-foreground"> из {user.active_session.takes_limit}</span>
                )}
              </p>
              <p>
                Осталось 4К: <span className="font-mono">{user.active_session.hd_remaining ?? 0}</span>
                {user.active_session.hd_limit != null && (
                  <span className="text-muted-foreground"> из {user.active_session.hd_limit}</span>
                )}
              </p>
              {user.active_session.created_at && (
                <p className="text-muted-foreground">
                  Начало сессии: {safeDateShort(user.active_session.created_at)}
                </p>
              )}
            </div>
          ) : (
            <p className="text-muted-foreground">Нет активного тарифа</p>
          )}
        </CardContent>
      </Card>

      {/* Sessions history */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">История сессий</CardTitle>
        </CardHeader>
        <CardContent>
          {sessions.length === 0 ? (
            <p className="text-sm text-muted-foreground">Нет сессий</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Пакет</TableHead>
                    <TableHead>Статус</TableHead>
                    <TableHead>Использовано / лимит</TableHead>
                    <TableHead>Дата</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sessions.map((s: UserDetailSession, idx: number) => (
                    <TableRow key={s?.id ?? `session-${idx}`}>
                      <TableCell>
                        {s.pack_id === 'free_preview' ? 'Бесплатный' : (s.pack_name ?? '—')}{' '}
                        <span className="text-muted-foreground">({s.pack_id ?? '—'})</span>
                      </TableCell>
                      <TableCell>{s.status ?? '—'}</TableCell>
                      <TableCell>
                        {s.takes_used ?? 0} / {s.takes_limit ?? 0}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {safeDateShort(s.created_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Payments */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Платежи</CardTitle>
        </CardHeader>
        <CardContent>
          {payments.length === 0 ? (
            <p className="text-sm text-muted-foreground">Нет платежей</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Дата</TableHead>
                    <TableHead>Пакет</TableHead>
                    <TableHead>Сумма</TableHead>
                    <TableHead>Статус</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {payments.map((p: UserDetailPayment, idx: number) => (
                    <TableRow key={p?.id ?? `payment-${idx}`}>
                      <TableCell className="text-muted-foreground">
                        {safeDateShort(p.created_at)}
                      </TableCell>
                      <TableCell>{p.pack_id ?? '—'}</TableCell>
                      <TableCell>
                        {p.amount_kopecks != null
                          ? `${(Number(p.amount_kopecks) / 100).toFixed(2)} ₽`
                          : (p.stars_amount ?? 0) > 0
                            ? `${p.stars_amount} ⭐`
                            : (p.tokens_granted ?? 0) > 0
                              ? `${p.tokens_granted} токенов`
                              : '—'}
                      </TableCell>
                      <TableCell>{p.status ?? '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Grant pack modal */}
      <Dialog open={grantOpen} onOpenChange={setGrantOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Выдать пакет</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="grant-pack">Пакет</Label>
              <select
                id="grant-pack"
                value={grantPackId ?? ''}
                onChange={(e) => setGrantPackId(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="">Выберите пакет</option>
                {enabledPacks.map((p: { id: string; name: string; emoji?: string }) => (
                  <option key={p.id} value={p.id}>
                    {p.emoji ? `${p.emoji} ` : ''}{p.name} ({p.id})
                  </option>
                ))}
              </select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="grant-message">Сообщение пользователю при активации (опционально)</Label>
              <textarea
                id="grant-message"
                placeholder="Текст отправится в Telegram сразу после выдачи"
                value={grantMessage}
                onChange={(e) => setGrantMessage(e.target.value)}
                className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGrantOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={handleGrantSubmit}
              disabled={!(grantPackId ?? '').trim() || grantMutation.isPending}
            >
              {grantMutation.isPending ? 'Выдача...' : 'Выдать'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reset limits confirm */}
      <Dialog open={resetLimitsOpen} onOpenChange={setResetLimitsOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Сбросить лимиты</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Сбросить счётчики бесплатных генераций, перегенераций и бесплатного фото (аккаунт) для этого пользователя. Токены и 4К не изменятся.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetLimitsOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={() => resetLimitsMutation.mutate()}
              disabled={resetLimitsMutation.isPending}
            >
              {resetLimitsMutation.isPending ? 'Сброс...' : 'Сбросить'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
    </UserDetailErrorBoundary>
  )
}
