import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { securityService, type SecuritySettings, type SecurityOverview } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
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
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Pagination } from '@/components/Pagination'
import {
  Shield,
  Ban,
  Clock,
  Gauge,
  Search,
  Users,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Settings,
  RotateCcw,
  UserCheck,
  UserX,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

type ActionType = 'ban' | 'unban' | 'suspend' | 'resume' | 'rate_limit' | 'notes' | null

function SecuritySettingsForm() {
  const queryClient = useQueryClient()
  const { data: settings, isLoading } = useQuery<SecuritySettings>({
    queryKey: ['security-settings'],
    queryFn: securityService.getSettings,
  })
  const settingsTyped = settings
  const [form, setForm] = useState<Partial<SecuritySettings>>({})

  const updateMutation = useMutation({
    mutationFn: (payload: Partial<SecuritySettings>) => securityService.updateSettings(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['security-settings'] })
      toast.success('Настройки сохранены')
    },
    onError: () => toast.error('Ошибка при сохранении'),
  })

  const handleChange = (key: keyof SecuritySettings, value: number | boolean) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const payload = { ...settingsTyped, ...form }
    updateMutation.mutate(payload)
  }

  const current = { ...settingsTyped, ...form }

  if (isLoading || !settingsTyped) return <div className="text-center py-8">Загрузка...</div>

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Settings className="h-5 w-5" />
          Глобальные настройки безопасности
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Бесплатные запросы в день, rate limits, авто-приостановка при abuse, VIP-обход лимитов.
        </p>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-6">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="free_generations_per_user">Бесплатных генераций на аккаунт (жёсткий лимит)</Label>
              <Input
                id="free_generations_per_user"
                type="number"
                min={0}
                max={20}
                value={current.free_generations_per_user ?? 3}
                onChange={(e) => handleChange('free_generations_per_user', parseInt(e.target.value) || 0)}
              />
              <p className="text-xs text-muted-foreground">1 аккаунт = N бесплатных. Далее — токены. Нельзя абузить.</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="copy_generations_per_user">«Сделать такую же» — бесплатно на аккаунт</Label>
              <Input
                id="copy_generations_per_user"
                type="number"
                min={0}
                max={5}
                value={current.copy_generations_per_user ?? 1}
                onChange={(e) => handleChange('copy_generations_per_user', parseInt(e.target.value) || 0)}
              />
              <p className="text-xs text-muted-foreground">Отдельная квота. По умолчанию 1 раз на аккаунт.</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="free_requests_per_day">Бесплатных запросов в день (устарело, используется free_generations)</Label>
              <Input
                id="free_requests_per_day"
                type="number"
                min={0}
                value={current.free_requests_per_day ?? 10}
                onChange={(e) => handleChange('free_requests_per_day', parseInt(e.target.value) || 0)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new_user_first_day_limit">Лимит для новичка в первый день</Label>
              <Input
                id="new_user_first_day_limit"
                type="number"
                min={0}
                value={current.new_user_first_day_limit ?? 5}
                onChange={(e) => handleChange('new_user_first_day_limit', parseInt(e.target.value) || 0)}
              />
            </div>
          </div>

          <div className="border-t pt-4">
            <h4 className="font-medium mb-3">Rate limits (запросов/час)</h4>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="default_rate_limit_per_hour">Free пользователи</Label>
                <Input
                  id="default_rate_limit_per_hour"
                  type="number"
                  min={1}
                  value={current.default_rate_limit_per_hour ?? 20}
                  onChange={(e) => handleChange('default_rate_limit_per_hour', parseInt(e.target.value) || 1)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="subscriber_rate_limit_per_hour">Подписчики (PRO)</Label>
                <Input
                  id="subscriber_rate_limit_per_hour"
                  type="number"
                  min={1}
                  value={current.subscriber_rate_limit_per_hour ?? 100}
                  onChange={(e) => handleChange('subscriber_rate_limit_per_hour', parseInt(e.target.value) || 1)}
                />
              </div>
            </div>
          </div>

          <div className="border-t pt-4">
            <h4 className="font-medium mb-3">Защита от abuse (2026)</h4>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="max_failures_before_auto_suspend">Авто-приостановка после N ошибок</Label>
                <Input
                  id="max_failures_before_auto_suspend"
                  type="number"
                  min={0}
                  value={current.max_failures_before_auto_suspend ?? 15}
                  onChange={(e) => handleChange('max_failures_before_auto_suspend', parseInt(e.target.value) || 0)}
                />
                <p className="text-xs text-muted-foreground">0 = отключено</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="auto_suspend_hours">Длительность авто-приостановки (часов)</Label>
                <Input
                  id="auto_suspend_hours"
                  type="number"
                  min={1}
                  value={current.auto_suspend_hours ?? 24}
                  onChange={(e) => handleChange('auto_suspend_hours', parseInt(e.target.value) || 1)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cooldown_minutes_after_failures">Cooldown после ошибок (минут)</Label>
                <Input
                  id="cooldown_minutes_after_failures"
                  type="number"
                  min={0}
                  value={current.cooldown_minutes_after_failures ?? 10}
                  onChange={(e) => handleChange('cooldown_minutes_after_failures', parseInt(e.target.value) || 0)}
                />
              </div>
            </div>
          </div>

          <div className="border-t pt-4 flex items-center gap-2">
            <input
              type="checkbox"
              id="vip_bypass_rate_limit"
              checked={current.vip_bypass_rate_limit ?? false}
              onChange={(e) => handleChange('vip_bypass_rate_limit', e.target.checked)}
              className="h-4 w-4"
            />
            <Label htmlFor="vip_bypass_rate_limit" className="cursor-pointer">
              VIP (флаг в профиле) не ограничены по rate limit
            </Label>
          </div>

          {current.updated_at && (
            <p className="text-xs text-muted-foreground">
              Обновлено: {new Date(current.updated_at).toLocaleString('ru-RU')}
            </p>
          )}

          <Button type="submit" disabled={updateMutation.isPending}>
            {updateMutation.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
            Сохранить настройки
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

export function SecurityPage() {
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState('all')
  const [selectedUsers, setSelectedUsers] = useState<string[]>([])
  
  // Action dialog state
  const [actionType, setActionType] = useState<ActionType>(null)
  const [targetUser, setTargetUser] = useState<any>(null)
  const [actionReason, setActionReason] = useState('')
  const [suspendHours, setSuspendHours] = useState(24)
  const [rateLimit, setRateLimit] = useState<string>('')
  const [resetLimitsDialogOpen, setResetLimitsDialogOpen] = useState(false)

  const { data: overviewTyped } = useQuery<SecurityOverview>({
    queryKey: ['security-overview'],
    queryFn: securityService.getOverview,
  })

  const { data: usersData, isLoading } = useQuery({
    queryKey: ['security-users', page, filterStatus, search],
    queryFn: () => securityService.getUsers({
      page,
      page_size: 20,
      filter_status: filterStatus !== 'all' ? filterStatus : undefined,
      telegram_id: search || undefined,
    }),
  })

  const banMutation = useMutation({
    mutationFn: ({ userId, reason }: { userId: string; reason?: string }) =>
      securityService.banUser(userId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['security-users'] })
      queryClient.invalidateQueries({ queryKey: ['security-overview'] })
      toast.success('Пользователь забанен')
      closeDialog()
    },
    onError: () => toast.error('Ошибка при бане пользователя'),
  })

  const unbanMutation = useMutation({
    mutationFn: (userId: string) => securityService.unbanUser(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['security-users'] })
      queryClient.invalidateQueries({ queryKey: ['security-overview'] })
      toast.success('Пользователь разбанен')
      closeDialog()
    },
    onError: () => toast.error('Ошибка при разбане'),
  })

  const suspendMutation = useMutation({
    mutationFn: ({ userId, hours, reason }: { userId: string; hours: number; reason?: string }) =>
      securityService.suspendUser(userId, hours, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['security-users'] })
      queryClient.invalidateQueries({ queryKey: ['security-overview'] })
      toast.success('Пользователь приостановлен')
      closeDialog()
    },
    onError: () => toast.error('Ошибка при приостановке'),
  })

  const resumeMutation = useMutation({
    mutationFn: (userId: string) => securityService.resumeUser(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['security-users'] })
      queryClient.invalidateQueries({ queryKey: ['security-overview'] })
      toast.success('Пользователь возобновлён')
      closeDialog()
    },
    onError: () => toast.error('Ошибка при возобновлении'),
  })

  const rateLimitMutation = useMutation({
    mutationFn: ({ userId, limit }: { userId: string; limit: number | null }) =>
      securityService.setRateLimit(userId, limit),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['security-users'] })
      queryClient.invalidateQueries({ queryKey: ['security-overview'] })
      toast.success('Rate limit установлен')
      closeDialog()
    },
    onError: () => toast.error('Ошибка при установке rate limit'),
  })

  const resetLimitsMutation = useMutation({
    mutationFn: () => securityService.resetLimits(),
    onSuccess: (data: { users_updated?: number }) => {
      queryClient.invalidateQueries({ queryKey: ['security-users'] })
      queryClient.invalidateQueries({ queryKey: ['security-overview'] })
      toast.success(`Лимиты сброшены. Обновлено пользователей: ${data?.users_updated ?? 0}`)
      setResetLimitsDialogOpen(false)
    },
    onError: () => toast.error('Ошибка при сбросе лимитов'),
  })

  const setModeratorMutation = useMutation({
    mutationFn: ({ userId, isModerator }: { userId: string; isModerator: boolean }) =>
      securityService.setModerator(userId, isModerator),
    onSuccess: (_, { isModerator }) => {
      queryClient.invalidateQueries({ queryKey: ['security-users'] })
      queryClient.invalidateQueries({ queryKey: ['security-overview'] })
      toast.success(isModerator ? 'Пользователь назначен модератором' : 'Модератор снят')
    },
    onError: () => toast.error('Ошибка при изменении статуса модератора'),
  })

  const closeDialog = () => {
    setActionType(null)
    setTargetUser(null)
    setActionReason('')
    setSuspendHours(24)
    setRateLimit('')
  }

  const openAction = (type: ActionType, user: any) => {
    setActionType(type)
    setTargetUser(user)
    if (type === 'rate_limit' && user.rate_limit_per_hour) {
      setRateLimit(String(user.rate_limit_per_hour))
    }
  }

  const handleAction = () => {
    if (!targetUser) return

    switch (actionType) {
      case 'ban':
        banMutation.mutate({ userId: targetUser.id, reason: actionReason || undefined })
        break
      case 'unban':
        unbanMutation.mutate(targetUser.id)
        break
      case 'suspend':
        suspendMutation.mutate({
          userId: targetUser.id,
          hours: suspendHours,
          reason: actionReason || undefined,
        })
        break
      case 'resume':
        resumeMutation.mutate(targetUser.id)
        break
      case 'rate_limit':
        const limit = rateLimit.trim() ? parseInt(rateLimit) : null
        rateLimitMutation.mutate({ userId: targetUser.id, limit })
        break
    }
  }

  const toggleSelectUser = (userId: string) => {
    setSelectedUsers((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]
    )
  }

  const toggleSelectAll = () => {
    if (selectedUsers.length === usersData?.items?.length) {
      setSelectedUsers([])
    } else {
      setSelectedUsers(usersData?.items?.map((u: any) => u.id) || [])
    }
  }

  const getStatusBadge = (user: any) => {
    if (user.is_banned) {
      return <Badge variant="destructive"><Ban className="h-3 w-3 mr-1" /> Забанен</Badge>
    }
    if (user.is_suspended) {
      return <Badge variant="secondary" className="bg-orange-100 text-orange-700"><Clock className="h-3 w-3 mr-1" /> Приостановлен</Badge>
    }
    return <Badge variant="outline" className="text-green-600"><CheckCircle2 className="h-3 w-3 mr-1" /> Активен</Badge>
  }

  const isPending = banMutation.isPending || unbanMutation.isPending ||
                    suspendMutation.isPending || resumeMutation.isPending ||
                    rateLimitMutation.isPending

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-red-600 to-orange-600 bg-clip-text text-transparent">
          Security & Moderation
        </h1>
        <p className="text-muted-foreground mt-2">
          Управление доступом и контроль пользователей
        </p>
      </div>

      <Tabs defaultValue="users" className="space-y-6">
        <TabsList className="grid w-full max-w-2xl grid-cols-3">
          <TabsTrigger value="overview">Обзор</TabsTrigger>
          <TabsTrigger value="users">Пользователи</TabsTrigger>
          <TabsTrigger value="settings">Настройки</TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="space-y-6">
          <div className="grid gap-4 md:grid-cols-5">
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-muted-foreground">Забанено</p>
                    <p className="text-3xl font-bold text-red-600">{overviewTyped?.banned_count ?? 0}</p>
                  </div>
                  <div className="p-3 rounded-xl bg-red-100">
                    <Ban className="h-6 w-6 text-red-600" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-muted-foreground">Приостановлено</p>
                    <p className="text-3xl font-bold text-orange-600">{overviewTyped?.suspended_count ?? 0}</p>
                  </div>
                  <div className="p-3 rounded-xl bg-orange-100">
                    <Clock className="h-6 w-6 text-orange-600" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-muted-foreground">С rate limit</p>
                    <p className="text-3xl font-bold text-blue-600">{overviewTyped?.rate_limited_count ?? 0}</p>
                  </div>
                  <div className="p-3 rounded-xl bg-blue-100">
                    <Gauge className="h-6 w-6 text-blue-600" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-muted-foreground">Модераторы</p>
                    <p className="text-3xl font-bold text-emerald-600">{overviewTyped?.moderators_count ?? 0}</p>
                  </div>
                  <div className="p-3 rounded-xl bg-emerald-100">
                    <UserCheck className="h-6 w-6 text-emerald-600" />
                  </div>
                </div>
                <p className="text-xs text-muted-foreground mt-1">Без лимитов</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-muted-foreground">Всего</p>
                    <p className="text-3xl font-bold">{overviewTyped?.total_users ?? 0}</p>
                  </div>
                  <div className="p-3 rounded-xl bg-gray-100">
                    <Users className="h-6 w-6 text-gray-600" />
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Shield className="h-5 w-5" />
                Глобальные настройки
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Лимиты и квоты задаются во вкладке «Настройки». Там же: бесплатные запросы в день, авто-приостановка, VIP.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Users Tab */}
        <TabsContent value="users" className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-4">
                <div className="relative flex-1 max-w-sm">
                  <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Поиск по Telegram ID..."
                    value={search}
                    onChange={(e) => {
                      setSearch(e.target.value)
                      setPage(1)
                    }}
                    className="pl-8"
                  />
                </div>
                <Select
                  value={filterStatus}
                  onValueChange={(v) => {
                    setFilterStatus(v)
                    setPage(1)
                  }}
                >
                  <SelectTrigger className="w-40">
                    <SelectValue placeholder="Статус" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Все</SelectItem>
                    <SelectItem value="active">Активные</SelectItem>
                    <SelectItem value="banned">Забаненные</SelectItem>
                    <SelectItem value="suspended">Приостановленные</SelectItem>
                    <SelectItem value="rate_limited">С rate limit</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="text-center py-8">Загрузка...</div>
              ) : (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-10">
                          <input
                            type="checkbox"
                            checked={selectedUsers.length === usersData?.items?.length && usersData?.items?.length > 0}
                            onChange={toggleSelectAll}
                            className="h-4 w-4"
                          />
                        </TableHead>
                        <TableHead>Telegram ID</TableHead>
                        <TableHead>Ник / Имя</TableHead>
                        <TableHead>Статус</TableHead>
                        <TableHead>Модератор</TableHead>
                        <TableHead>Rate Limit</TableHead>
                        <TableHead>Подписка</TableHead>
                        <TableHead>Jobs</TableHead>
                        <TableHead>Действия</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {usersData?.items?.map((user: any) => (
                        <TableRow key={user.id}>
                          <TableCell>
                            <input
                              type="checkbox"
                              checked={selectedUsers.includes(user.id)}
                              onChange={() => toggleSelectUser(user.id)}
                              className="h-4 w-4"
                            />
                          </TableCell>
                          <TableCell className="font-mono text-sm">{user.telegram_id}</TableCell>
                          <TableCell>
                            {user.telegram_username ? (
                              <span className="text-primary font-medium">@{user.telegram_username}</span>
                            ) : (user.telegram_first_name || user.telegram_last_name) ? (
                              <span className="text-muted-foreground">
                                {[user.telegram_first_name, user.telegram_last_name].filter(Boolean).join(' ')}
                              </span>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </TableCell>
                          <TableCell>{getStatusBadge(user)}</TableCell>
                          <TableCell>
                            {user.is_moderator ? (
                              <Badge variant="secondary" className="bg-emerald-100 text-emerald-700">
                                <UserCheck className="h-3 w-3 mr-1" /> Модератор
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground text-sm">—</span>
                            )}
                            <Button
                              size="sm"
                              variant="ghost"
                              className="ml-1 h-7"
                              onClick={() => setModeratorMutation.mutate({ userId: user.id, isModerator: !user.is_moderator })}
                              disabled={setModeratorMutation.isPending && (setModeratorMutation.variables as { userId: string } | undefined)?.userId === user.id}
                              title={user.is_moderator ? 'Убрать модератора' : 'Сделать модератором'}
                            >
                              {setModeratorMutation.isPending && (setModeratorMutation.variables as { userId: string } | undefined)?.userId === user.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : user.is_moderator ? (
                                <UserX className="h-4 w-4" />
                              ) : (
                                <UserCheck className="h-4 w-4" />
                              )}
                            </Button>
                          </TableCell>
                          <TableCell>
                            {user.rate_limit_per_hour != null ? (
                              <Badge variant="outline">{user.rate_limit_per_hour}/ч</Badge>
                            ) : (
                              <span className="text-muted-foreground text-sm" title="По умолчанию (Free/PRO)">—</span>
                            )}
                          </TableCell>
                          <TableCell>
                            {user.subscription_active ? (
                              <Badge variant="success">PRO</Badge>
                            ) : (
                              <span className="text-muted-foreground text-sm">Free</span>
                            )}
                          </TableCell>
                          <TableCell className="font-mono text-sm">
                            {typeof user.jobs_count === 'number' ? user.jobs_count : '—'}
                          </TableCell>
                          <TableCell>
                            <div className="flex gap-1">
                              {user.is_banned ? (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => openAction('unban', user)}
                                >
                                  Разбанить
                                </Button>
                              ) : user.is_suspended ? (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => openAction('resume', user)}
                                >
                                  Возобновить
                                </Button>
                              ) : (
                                <>
                                  <Button
                                    size="sm"
                                    variant="destructive"
                                    onClick={() => openAction('ban', user)}
                                  >
                                    Бан
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="secondary"
                                    onClick={() => openAction('suspend', user)}
                                  >
                                    Пауза
                                  </Button>
                                </>
                              )}
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => openAction('rate_limit', user)}
                              >
                                <Gauge className="h-4 w-4" />
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>

                  {usersData && (
                    <Pagination
                      currentPage={page}
                      totalPages={usersData.pages ?? Math.max(1, Math.ceil((usersData.total ?? 0) / 20))}
                      onPageChange={setPage}
                    />
                  )}

                  {selectedUsers.length > 0 && (
                    <div className="mt-4 p-4 border rounded-lg bg-muted/30 flex items-center justify-between">
                      <span>Выбрано: {selectedUsers.length}</span>
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => {
                            // Bulk ban would go here
                            toast.info('Массовые действия — в разработке')
                          }}
                        >
                          Массовый бан
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setSelectedUsers([])}
                        >
                          Отменить выбор
                        </Button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Settings Tab */}
        <TabsContent value="settings" className="space-y-6">
          <SecuritySettingsForm />
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <RotateCcw className="h-5 w-5" />
                Сброс лимитов
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                Обнулить счётчики бесплатных и «Сделать такую же» генераций у всех пользователей. Токены и подписки не затрагиваются.
              </p>
            </CardHeader>
            <CardContent>
              <Button
                variant="outline"
                onClick={() => setResetLimitsDialogOpen(true)}
                disabled={resetLimitsMutation.isPending}
              >
                {resetLimitsMutation.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RotateCcw className="h-4 w-4 mr-2" />}
                Сбросить все лимиты
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Reset limits confirmation */}
      <Dialog open={resetLimitsDialogOpen} onOpenChange={setResetLimitsDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <RotateCcw className="h-5 w-5" />
              Сбросить все лимиты?
            </DialogTitle>
            <DialogDescription>
              Обнулятся счётчики бесплатных генераций и «Сделать такую же» у <strong>всех</strong> пользователей.
              Токены и подписки не изменятся. Действие нельзя отменить.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetLimitsDialogOpen(false)}>
              Отмена
            </Button>
            <Button
              variant="destructive"
              onClick={() => resetLimitsMutation.mutate()}
              disabled={resetLimitsMutation.isPending}
            >
              {resetLimitsMutation.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
              Сбросить лимиты
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Action Dialog */}
      <Dialog open={!!actionType} onOpenChange={(open) => !open && closeDialog()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {actionType === 'ban' && <><AlertTriangle className="h-5 w-5 text-red-600" /> Забанить пользователя</>}
              {actionType === 'unban' && <><CheckCircle2 className="h-5 w-5 text-green-600" /> Разбанить пользователя</>}
              {actionType === 'suspend' && <><Clock className="h-5 w-5 text-orange-600" /> Приостановить пользователя</>}
              {actionType === 'resume' && <><CheckCircle2 className="h-5 w-5 text-green-600" /> Возобновить доступ</>}
              {actionType === 'rate_limit' && <><Gauge className="h-5 w-5 text-blue-600" /> Установить Rate Limit</>}
            </DialogTitle>
            <DialogDescription>
              Telegram ID: <strong>{targetUser?.telegram_id}</strong>
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {(actionType === 'ban' || actionType === 'suspend') && (
              <div className="space-y-2">
                <Label>Причина (опционально)</Label>
                <Textarea
                  value={actionReason}
                  onChange={(e) => setActionReason(e.target.value)}
                  placeholder="Укажите причину..."
                  rows={2}
                />
              </div>
            )}

            {actionType === 'suspend' && (
              <div className="space-y-2">
                <Label>Длительность</Label>
                <Select value={String(suspendHours)} onValueChange={(v) => setSuspendHours(Number(v))}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">1 час</SelectItem>
                    <SelectItem value="6">6 часов</SelectItem>
                    <SelectItem value="12">12 часов</SelectItem>
                    <SelectItem value="24">24 часа</SelectItem>
                    <SelectItem value="72">3 дня</SelectItem>
                    <SelectItem value="168">7 дней</SelectItem>
                    <SelectItem value="720">30 дней</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}

            {actionType === 'rate_limit' && (
              <div className="space-y-2">
                <Label>Лимит запросов в час</Label>
                <Input
                  type="number"
                  value={rateLimit}
                  onChange={(e) => setRateLimit(e.target.value)}
                  placeholder="Пусто = глобальный лимит"
                  min={0}
                />
                <p className="text-xs text-muted-foreground">
                  Оставьте пустым для использования глобального лимита
                </p>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeDialog}>
              Отмена
            </Button>
            <Button
              onClick={handleAction}
              disabled={isPending}
              variant={actionType === 'ban' ? 'destructive' : 'default'}
            >
              {isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : null}
              {actionType === 'ban' && 'Забанить'}
              {actionType === 'unban' && 'Разбанить'}
              {actionType === 'suspend' && 'Приостановить'}
              {actionType === 'resume' && 'Возобновить'}
              {actionType === 'rate_limit' && 'Применить'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
