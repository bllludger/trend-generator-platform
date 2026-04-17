import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { trendsService, type TrendAnalyticsItem } from '@/services/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { AlertCircle, ArrowDown, ArrowUp, ArrowUpDown, BarChart3, CheckCircle, RefreshCw, TrendingUp, Trophy, Users, XCircle } from 'lucide-react'
import { formatNumber } from '@/lib/utils'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

function calcGenerated(item: TrendAnalyticsItem): number {
  return Number(item.generated_total ?? item.jobs_total + item.takes_total)
}

function calcSucceeded(item: TrendAnalyticsItem): number {
  return Number(item.succeeded_total ?? item.jobs_succeeded + item.takes_succeeded)
}

function calcFailed(item: TrendAnalyticsItem): number {
  return Number(item.failed_total ?? item.jobs_failed + item.takes_failed)
}

function calcSuccessRate(item: TrendAnalyticsItem): number {
  const generated = calcGenerated(item)
  if (!generated) return 0
  return Number(item.success_rate_pct ?? Math.round((calcSucceeded(item) / generated) * 1000) / 10)
}

function formatDateTime(value?: string): string {
  if (!value) return '—'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString('ru-RU')
}

function getRateClass(rate: number): string {
  if (rate >= 85) return 'text-emerald-600'
  if (rate >= 60) return 'text-amber-600'
  return 'text-rose-600'
}

type TrendTableSortKey = 'name' | 'users' | 'generated' | 'succeeded' | 'failed' | 'chosen' | 'successRate'
type TrendTableSortDirection = 'asc' | 'desc'

export function TrendsAnalyticsPage() {
  const [tableSort, setTableSort] = useState<{
    key: TrendTableSortKey
    direction: TrendTableSortDirection
  }>({
    key: 'generated',
    direction: 'desc',
  })

  const {
    data,
    isLoading,
    isError,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ['trends-analytics', 'all-time'],
    queryFn: () => trendsService.getAnalytics(undefined, true),
    refetchInterval: 60_000,
  })

  const items = useMemo(() => {
    const list = data?.items ?? []
    return [...list].sort((a, b) => {
      const generatedDiff = calcGenerated(b) - calcGenerated(a)
      if (generatedDiff !== 0) return generatedDiff
      return (b.chosen_total ?? 0) - (a.chosen_total ?? 0)
    })
  }, [data?.items])

  const sortedTableItems = useMemo(() => {
    const rows = [...items]
    const { key, direction } = tableSort
    rows.sort((a, b) => {
      let compare = 0
      if (key === 'name') {
        compare = a.name.localeCompare(b.name, 'ru')
      } else if (key === 'users') {
        compare = Number(a.users_total ?? 0) - Number(b.users_total ?? 0)
      } else if (key === 'generated') {
        compare = calcGenerated(a) - calcGenerated(b)
      } else if (key === 'succeeded') {
        compare = calcSucceeded(a) - calcSucceeded(b)
      } else if (key === 'failed') {
        compare = calcFailed(a) - calcFailed(b)
      } else if (key === 'chosen') {
        compare = Number(a.chosen_total ?? 0) - Number(b.chosen_total ?? 0)
      } else {
        compare = calcSuccessRate(a) - calcSuccessRate(b)
      }
      if (compare === 0) {
        compare = calcGenerated(b) - calcGenerated(a)
      }
      return direction === 'asc' ? compare : -compare
    })
    return rows
  }, [items, tableSort])

  const toggleTableSort = (key: TrendTableSortKey) => {
    setTableSort((prev) => {
      if (prev.key === key) {
        return { key, direction: prev.direction === 'asc' ? 'desc' : 'asc' }
      }
      return { key, direction: key === 'name' ? 'asc' : 'desc' }
    })
  }

  const sortIcon = (key: TrendTableSortKey) => {
    if (tableSort.key !== key) return <ArrowUpDown className="h-3.5 w-3.5 text-muted-foreground/70" />
    return tableSort.direction === 'asc'
      ? <ArrowUp className="h-3.5 w-3.5 text-foreground" />
      : <ArrowDown className="h-3.5 w-3.5 text-foreground" />
  }

  const itemsWithActivity = useMemo(
    () => items.filter((item) => calcGenerated(item) > 0 || Number(item.chosen_total ?? 0) > 0),
    [items]
  )

  const chartData = useMemo(
    () =>
      itemsWithActivity.slice(0, 12).map((item) => {
        const fullName = `${item.emoji ? `${item.emoji} ` : ''}${item.name}`
        const shortName = fullName.length > 30 ? `${fullName.slice(0, 30)}…` : fullName
        return {
          trend_id: item.trend_id,
          name: shortName,
          fullName,
          generated: calcGenerated(item),
          succeeded: calcSucceeded(item),
          failed: calcFailed(item),
          successRate: calcSuccessRate(item),
        }
      }),
    [itemsWithActivity]
  )

  const qualityLeaders = useMemo(
    () =>
      itemsWithActivity
        .filter((item) => calcGenerated(item) >= 3)
        .sort((a, b) => {
          const rateDiff = calcSuccessRate(b) - calcSuccessRate(a)
          if (rateDiff !== 0) return rateDiff
          return calcGenerated(b) - calcGenerated(a)
        })
        .slice(0, 8),
    [itemsWithActivity]
  )

  const errorHotspots = useMemo(
    () =>
      itemsWithActivity
        .filter((item) => calcFailed(item) > 0)
        .sort((a, b) => {
          const failedDiff = calcFailed(b) - calcFailed(a)
          if (failedDiff !== 0) return failedDiff
          return calcGenerated(b) - calcGenerated(a)
        })
        .slice(0, 8),
    [itemsWithActivity]
  )

  const fallbackSummary = useMemo(() => {
    const generatedTotal = items.reduce((acc, item) => acc + calcGenerated(item), 0)
    const succeededTotal = items.reduce((acc, item) => acc + calcSucceeded(item), 0)
    const failedTotal = items.reduce((acc, item) => acc + calcFailed(item), 0)
    const chosenTotal = items.reduce((acc, item) => acc + Number(item.chosen_total ?? 0), 0)
    const usersTotal = items.reduce((acc, item) => acc + Number(item.users_total ?? 0), 0)
    return {
      trends_total: items.length,
      trends_with_activity: itemsWithActivity.length,
      generated_total: generatedTotal,
      succeeded_total: succeededTotal,
      failed_total: failedTotal,
      success_rate_pct: generatedTotal > 0 ? Math.round((succeededTotal / generatedTotal) * 1000) / 10 : 0,
      users_total: usersTotal,
      chosen_total: chosenTotal,
      chosen_users: items.reduce((acc, item) => acc + Number(item.chosen_users ?? 0), 0),
    }
  }, [items, itemsWithActivity.length])

  const summary = data?.summary ?? fallbackSummary
  const updatedAt = formatDateTime(data?.generated_at)

  if (isLoading) {
    return (
      <div className="space-y-6 p-6">
        <Skeleton className="h-9 w-72" />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
        <Skeleton className="h-[420px] w-full" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="space-y-6 p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
              <BarChart3 className="h-6 w-6 text-muted-foreground" />
              Аналитика по трендам
            </h1>
          </div>
        </div>
        <Card className="border-destructive/50">
          <CardContent className="flex flex-col items-center justify-center gap-4 py-12">
            <AlertCircle className="h-12 w-12 text-destructive" />
            <p className="text-center text-muted-foreground">
              Не удалось загрузить данные. Повторите запрос.
            </p>
            <Button variant="outline" onClick={() => refetch()}>
              Повторить
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <BarChart3 className="h-6 w-6 text-muted-foreground" />
            Аналитика по трендам
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Единая витрина за всё время: без окон 30/90, только ключевые метрики и тренды.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="secondary">Период: всё время</Badge>
          <Badge variant="outline">Обновлено: {updatedAt}</Badge>
          <Button variant="outline" size="icon" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Активные тренды</CardDescription>
            <CardTitle className="text-3xl">{formatNumber(summary.trends_with_activity)}</CardTitle>
          </CardHeader>
          <CardContent className="pt-0 text-xs text-muted-foreground">
            Из {formatNumber(summary.trends_total)} всего
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Сгенерировано</CardDescription>
            <CardTitle className="text-3xl">{formatNumber(summary.generated_total)}</CardTitle>
          </CardHeader>
          <CardContent className="pt-0 text-xs text-muted-foreground">
            Job + Take
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Успешность</CardDescription>
            <CardTitle className={`text-3xl ${getRateClass(summary.success_rate_pct)}`}>
              {summary.success_rate_pct}%
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0 text-xs text-muted-foreground">
            {formatNumber(summary.succeeded_total)} успешных / {formatNumber(summary.failed_total)} ошибок
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Пользователи</CardDescription>
            <CardTitle className="text-3xl">{formatNumber(summary.users_total)}</CardTitle>
          </CardHeader>
          <CardContent className="pt-0 text-xs text-muted-foreground">
            С хотя бы одной генерацией
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Выбрано вариантов</CardDescription>
            <CardTitle className="text-3xl">{formatNumber(summary.chosen_total)}</CardTitle>
          </CardHeader>
          <CardContent className="pt-0 text-xs text-muted-foreground">
            События выбора результата
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Топ трендов по генерациям</CardTitle>
          <CardDescription>
            Топ-12 по объёму. Цветом показаны успешные и ошибочные генерации.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {chartData.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">Нет данных.</p>
          ) : (
            <ResponsiveContainer width="100%" height={420}>
              <BarChart data={chartData} layout="vertical" margin={{ top: 6, right: 24, left: 4, bottom: 6 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis type="number" tickFormatter={(v) => formatNumber(v)} />
                <YAxis type="category" dataKey="name" width={220} tick={{ fontSize: 12 }} />
                <Tooltip
                  content={({ active, payload }) =>
                    active && payload && payload.length > 0 ? (
                      <div className="rounded-md border bg-background px-3 py-2 shadow-md">
                        <p className="font-medium">{payload[0].payload?.fullName}</p>
                        <p className="text-sm text-emerald-600">
                          Успешно: {formatNumber(Number(payload[0].payload?.succeeded ?? 0))}
                        </p>
                        <p className="text-sm text-rose-600">
                          Ошибки: {formatNumber(Number(payload[0].payload?.failed ?? 0))}
                        </p>
                        <p className="text-sm text-muted-foreground">
                          Успешность: {Number(payload[0].payload?.successRate ?? 0)}%
                        </p>
                      </div>
                    ) : null
                  }
                />
                <Bar dataKey="succeeded" stackId="a" fill="#16a34a" radius={[0, 0, 0, 0]} name="Успешно" />
                <Bar dataKey="failed" stackId="a" fill="#ef4444" radius={[0, 4, 4, 0]} name="Ошибки" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Trophy className="h-4 w-4 text-amber-500" />
              Лидеры по качеству
            </CardTitle>
            <CardDescription>Тренды с лучшей стабильностью при объёме от 3 генераций.</CardDescription>
          </CardHeader>
          <CardContent>
            {qualityLeaders.length === 0 ? (
              <p className="py-4 text-sm text-muted-foreground">Недостаточно данных.</p>
            ) : (
              <ul className="space-y-3">
                {qualityLeaders.map((item) => {
                  const rate = calcSuccessRate(item)
                  const generated = calcGenerated(item)
                  return (
                    <li key={item.trend_id} className="flex items-center justify-between rounded-lg border p-3">
                      <div className="min-w-0">
                        <p className="truncate font-medium">
                          {item.emoji ? `${item.emoji} ` : ''}{item.name}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {formatNumber(generated)} генераций
                        </p>
                      </div>
                      <Badge variant="secondary" className={getRateClass(rate)}>
                        {rate}%
                      </Badge>
                    </li>
                  )
                })}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingUp className="h-4 w-4 text-rose-500" />
              Зоны риска
            </CardTitle>
            <CardDescription>Тренды с наибольшим числом ошибок для приоритетного улучшения.</CardDescription>
          </CardHeader>
          <CardContent>
            {errorHotspots.length === 0 ? (
              <p className="py-4 text-sm text-muted-foreground">Ошибок по трендам не обнаружено.</p>
            ) : (
              <ul className="space-y-3">
                {errorHotspots.map((item) => {
                  const failed = calcFailed(item)
                  const rate = calcSuccessRate(item)
                  return (
                    <li key={item.trend_id} className="flex items-center justify-between rounded-lg border p-3">
                      <div className="min-w-0">
                        <p className="truncate font-medium">
                          {item.emoji ? `${item.emoji} ` : ''}{item.name}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Успешность {rate}%
                        </p>
                      </div>
                      <Badge variant="outline" className="text-rose-600">
                        {formatNumber(failed)} ошибок
                      </Badge>
                    </li>
                  )
                })}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Все тренды</CardTitle>
          <CardDescription>
            Сводная таблица без дублей: пользователи, генерации, успехи, ошибки и выборы.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>
                  <Button variant="ghost" size="sm" className="h-auto p-0 font-semibold" onClick={() => toggleTableSort('name')}>
                    <span className="mr-1">Тренд</span>{sortIcon('name')}
                  </Button>
                </TableHead>
                <TableHead className="text-right">
                  <Button variant="ghost" size="sm" className="ml-auto h-auto p-0 font-semibold" onClick={() => toggleTableSort('users')}>
                    <span className="mr-1">Пользователи</span>{sortIcon('users')}
                  </Button>
                </TableHead>
                <TableHead className="text-right">
                  <Button variant="ghost" size="sm" className="ml-auto h-auto p-0 font-semibold" onClick={() => toggleTableSort('generated')}>
                    <span className="mr-1">Сгенерировано</span>{sortIcon('generated')}
                  </Button>
                </TableHead>
                <TableHead className="text-right">
                  <Button variant="ghost" size="sm" className="ml-auto h-auto p-0 font-semibold" onClick={() => toggleTableSort('succeeded')}>
                    <span className="mr-1">Успешно</span>{sortIcon('succeeded')}
                  </Button>
                </TableHead>
                <TableHead className="text-right">
                  <Button variant="ghost" size="sm" className="ml-auto h-auto p-0 font-semibold" onClick={() => toggleTableSort('failed')}>
                    <span className="mr-1">Ошибки</span>{sortIcon('failed')}
                  </Button>
                </TableHead>
                <TableHead className="text-right">
                  <Button variant="ghost" size="sm" className="ml-auto h-auto p-0 font-semibold" onClick={() => toggleTableSort('chosen')}>
                    <span className="mr-1">Выборы</span>{sortIcon('chosen')}
                  </Button>
                </TableHead>
                <TableHead className="text-right">
                  <Button variant="ghost" size="sm" className="ml-auto h-auto p-0 font-semibold" onClick={() => toggleTableSort('successRate')}>
                    <span className="mr-1">Успешность</span>{sortIcon('successRate')}
                  </Button>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedTableItems.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                    Нет данных.
                  </TableCell>
                </TableRow>
              ) : (
                sortedTableItems.map((item) => {
                  const generated = calcGenerated(item)
                  const succeeded = calcSucceeded(item)
                  const failed = calcFailed(item)
                  const users = Number(item.users_total ?? 0)
                  const chosen = Number(item.chosen_total ?? 0)
                  const rate = calcSuccessRate(item)
                  return (
                    <TableRow key={item.trend_id}>
                      <TableCell>
                        <span className="inline-flex max-w-[320px] items-center gap-2 truncate font-medium">
                          <span className="text-lg">{item.emoji || '—'}</span>
                          <span className="truncate">{item.name}</span>
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <span className="inline-flex items-center justify-end gap-1">
                          <Users className="h-4 w-4 text-muted-foreground" />
                          {formatNumber(users)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right font-medium">{formatNumber(generated)}</TableCell>
                      <TableCell className="text-right">
                        <span className="inline-flex items-center justify-end gap-1 text-emerald-600">
                          <CheckCircle className="h-4 w-4" />
                          {formatNumber(succeeded)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <span className="inline-flex items-center justify-end gap-1 text-rose-600">
                          <XCircle className="h-4 w-4" />
                          {formatNumber(failed)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">{formatNumber(chosen)}</TableCell>
                      <TableCell className={`text-right font-semibold ${getRateClass(rate)}`}>
                        {generated > 0 ? `${rate}%` : '—'}
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
