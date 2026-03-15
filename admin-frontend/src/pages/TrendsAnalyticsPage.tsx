import { useQuery } from '@tanstack/react-query'
import { trendsService, type TrendAnalyticsItem } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { BarChart3, CheckCircle, XCircle, Sparkles, AlertCircle } from 'lucide-react'
import { useState, useMemo } from 'react'
import { formatNumber } from '@/lib/utils'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'

const PERIOD_OPTIONS = [
  { value: 0, label: 'Всё время' },
  { value: 7, label: '7 дней' },
  { value: 14, label: '14 дней' },
  { value: 30, label: '30 дней' },
  { value: 90, label: '90 дней' },
]

function successRate(succeeded: number, total: number): number {
  if (total === 0) return 0
  return Math.round((succeeded / total) * 100)
}

export function TrendsAnalyticsPage() {
  const [windowDays, setWindowDays] = useState(30)
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['trends-analytics', windowDays],
    queryFn: () => trendsService.getAnalytics(windowDays),
  })

  const items = useMemo(() => {
    const list = data?.items ?? []
    return [...list].sort((a, b) => {
      const totalA = a.jobs_total + a.takes_total
      const totalB = b.jobs_total + b.takes_total
      return totalB - totalA
    })
  }, [data?.items])

  const top20 = useMemo(() => items.slice(0, 20), [items])
  const topForList = useMemo(() => items.filter((i) => (i.jobs_total + i.takes_total) > 0 || (i.chosen_total ?? 0) > 0).slice(0, 10), [items])
  const periodLabel =
    data != null && (data.window_days == null || data.window_days === 0)
      ? 'всё время'
      : data != null
        ? `${data.window_days} д.`
        : ''
  const chartData = useMemo(
    () =>
      top20.map((i) => {
        const total = i.jobs_total + i.takes_total
        const shortName = i.name.length > 25 ? i.name.slice(0, 25) + '…' : i.name
        return { name: (i.emoji ? i.emoji + ' ' : '') + shortName, total, fullName: i.name }
      }),
    [top20]
  )

  if (isLoading) {
    return (
      <div className="space-y-6 p-6">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-[400px] w-full" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="space-y-6 p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
              <BarChart3 className="h-6 w-6 text-muted-foreground" />
              Аналитика по трендам
            </h1>
          </div>
        </div>
        <Card className="border-destructive/50">
          <CardContent className="flex flex-col items-center justify-center gap-4 py-12">
            <AlertCircle className="h-12 w-12 text-destructive" />
            <p className="text-center text-muted-foreground">
              Не удалось загрузить данные. Проверьте соединение и повторите попытку.
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
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <BarChart3 className="h-6 w-6 text-muted-foreground" />
            Аналитика по трендам
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Успешные генерации и ошибки по каждому тренду за выбранный период
          </p>
        </div>
        <Select value={String(windowDays)} onValueChange={(v) => setWindowDays(Number(v))}>
          <SelectTrigger className="w-[160px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PERIOD_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={String(opt.value)}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Топ 20 трендов по количеству сгенерированного */}
      <Card>
        <CardHeader>
          <CardTitle>Топ 20 трендов по количеству сгенерированного</CardTitle>
          <CardDescription>
            Всего сгенерировано = задачи (Job) + снимки (Take) за выбранный период
          </CardDescription>
        </CardHeader>
        <CardContent>
          {chartData.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">Нет данных за период</p>
          ) : (
            <ResponsiveContainer width="100%" height={400}>
              <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 24, left: 4, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis type="number" tickFormatter={(v) => formatNumber(v)} />
                <YAxis type="category" dataKey="name" width={180} tick={{ fontSize: 12 }} />
                <Tooltip
                  content={({ active, payload }) =>
                    active && payload?.[0] ? (
                      <div className="rounded-md border bg-background px-3 py-2 shadow-md">
                        <p className="font-medium">{payload[0].payload?.fullName ?? payload[0].payload?.name}</p>
                        <p className="text-sm text-muted-foreground">
                          Сгенерировано: {formatNumber(Number(payload[0]?.value ?? 0))}
                        </p>
                      </div>
                    ) : null
                  }
                />
                <Bar dataKey="total" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} name="Сгенерировано" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      {/* Топ трендов списком */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4 text-muted-foreground" />
            Топ трендов за {periodLabel || 'выбранный период'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {topForList.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Пока нет активности по трендам</p>
          ) : (
            <ul className="space-y-3">
              {topForList.map((trend) => {
                const jobs = trend.jobs_total
                const takes = trend.takes_total
                const total = jobs + takes
                const succeeded = trend.jobs_succeeded + trend.takes_succeeded
                const failed = trend.jobs_failed + trend.takes_failed
                const rate = total > 0 ? Math.round((succeeded / total) * 100) : 0
                const chosen = trend.chosen_total ?? 0
                const parts: string[] = []
                if (jobs > 0) parts.push(`${jobs} задач`)
                if (takes > 0) parts.push(`${takes} снимков`)
                if (chosen > 0) parts.push(`${chosen} выбрано картинок`)
                const subtitle = parts.length > 0 ? parts.join(' · ') : '—'
                return (
                  <li
                    key={trend.trend_id}
                    className="flex items-center justify-between gap-4 rounded-lg border border-border-muted bg-muted/30 px-3 py-3 transition-colors hover:bg-muted/50"
                  >
                    <div className="flex min-w-0 flex-1 items-center gap-3">
                      <span className="text-xl leading-none">{trend.emoji || '—'}</span>
                      <div className="min-w-0">
                        <p className="truncate font-medium text-foreground">{trend.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {subtitle}
                          {' · '}
                          {rate}% успешность
                        </p>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <div className="h-2 w-16 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-success"
                          style={{ width: `${rate}%` }}
                        />
                      </div>
                      <div className="text-right" title="Успешных / с ошибками за период">
                        <span className="text-sm font-semibold text-success">+{succeeded}</span>
                        {failed > 0 && (
                          <span className="ml-1 text-xs text-destructive">−{failed}</span>
                        )}
                      </div>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Все тренды за {periodLabel || 'выбранный период'}</CardTitle>
          <CardDescription>
            Задачи (Job) — перегенерация/превью; снимки (Take) — основной флоу «Создать фото». Ошибки — неуспешные или не доставленные.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Тренд</TableHead>
                <TableHead className="text-right">Задач</TableHead>
                <TableHead className="text-right">Снимков</TableHead>
                <TableHead className="text-right">Ошибки</TableHead>
                <TableHead className="text-right">% успешности</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                    Нет данных за период
                  </TableCell>
                </TableRow>
              ) : (
                items.map((row: TrendAnalyticsItem) => {
                  const jobsTotal = row.jobs_total
                  const jobsSucceeded = row.jobs_succeeded
                  const jobsFailed = row.jobs_failed
                  const takesTotal = row.takes_total
                  const takesSucceeded = row.takes_succeeded
                  const takesFailed = row.takes_failed
                  const total = jobsTotal + takesTotal
                  const succeeded = jobsSucceeded + takesSucceeded
                  const failed = jobsFailed + takesFailed
                  const rate = successRate(succeeded, total)
                  return (
                    <TableRow key={row.trend_id}>
                      <TableCell>
                        <span className="font-medium inline-flex items-center gap-2">
                          <span className="text-lg">{row.emoji || '—'}</span>
                          <span className="truncate max-w-[280px]">{row.name}</span>
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        {jobsTotal === 0 ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <span className="inline-flex items-center gap-1">
                            <CheckCircle className="h-4 w-4 text-success inline" />
                            {formatNumber(jobsSucceeded)} / {formatNumber(jobsTotal)}
                            {jobsFailed > 0 && (
                              <span className="text-destructive text-xs"> (−{formatNumber(jobsFailed)})</span>
                            )}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        {takesTotal === 0 ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <span className="inline-flex items-center gap-1">
                            <CheckCircle className="h-4 w-4 text-success inline" />
                            {formatNumber(takesSucceeded)} / {formatNumber(takesTotal)}
                            {takesFailed > 0 && (
                              <span className="text-destructive text-xs"> (−{formatNumber(takesFailed)})</span>
                            )}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        {failed === 0 ? (
                          <span className="text-muted-foreground">0</span>
                        ) : (
                          <span className="text-destructive font-medium inline-flex items-center gap-1">
                            <XCircle className="h-4 w-4" />
                            {formatNumber(failed)}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <span className={rate >= 80 ? 'text-success' : rate >= 50 ? 'text-warning' : 'text-destructive'}>
                          {total === 0 ? '—' : `${rate}%`}
                        </span>
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
