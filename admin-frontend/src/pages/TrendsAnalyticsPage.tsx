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
import { BarChart3, CheckCircle, XCircle } from 'lucide-react'
import { useState, useMemo } from 'react'
import { formatNumber } from '@/lib/utils'

const PERIOD_OPTIONS = [
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
  const { data, isLoading } = useQuery({
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

  if (isLoading) {
    return (
      <div className="space-y-6 p-6">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-[400px] w-full" />
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

      <Card>
        <CardHeader>
          <CardTitle>Все тренды за {windowDays} д.</CardTitle>
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
                            <CheckCircle className="h-4 w-4 text-emerald-600 inline" />
                            {formatNumber(jobsSucceeded)} / {formatNumber(jobsTotal)}
                            {jobsFailed > 0 && (
                              <span className="text-red-600 text-xs"> (−{formatNumber(jobsFailed)})</span>
                            )}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        {takesTotal === 0 ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <span className="inline-flex items-center gap-1">
                            <CheckCircle className="h-4 w-4 text-emerald-600 inline" />
                            {formatNumber(takesSucceeded)} / {formatNumber(takesTotal)}
                            {takesFailed > 0 && (
                              <span className="text-red-600 text-xs"> (−{formatNumber(takesFailed)})</span>
                            )}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        {failed === 0 ? (
                          <span className="text-muted-foreground">0</span>
                        ) : (
                          <span className="text-red-600 font-medium inline-flex items-center gap-1">
                            <XCircle className="h-4 w-4" />
                            {formatNumber(failed)}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <span className={rate >= 80 ? 'text-emerald-600' : rate >= 50 ? 'text-amber-600' : 'text-red-600'}>
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
