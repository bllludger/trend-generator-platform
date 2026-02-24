import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { jobsService, trendsService } from '@/services/api'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Pagination } from '@/components/Pagination'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate, formatNumber } from '@/lib/utils'
import {
  Search,
  Filter,
  Copy,
  Check,
  Briefcase,
  TrendingUp,
  AlertCircle,
  Clock,
  ListTodo,
} from 'lucide-react'
import { useState } from 'react'

const PERIOD_OPTIONS = [
  { value: 'all', label: 'Все время', hours: null as number | null },
  { value: '24', label: 'За 24 ч', hours: 24 },
  { value: '168', label: 'За 7 д', hours: 168 },
  { value: '720', label: 'За 30 д', hours: 720 },
]

const PAGE_SIZES = [20, 50, 100]

type JobItem = {
  job_id: string
  telegram_id?: string
  trend_id: string
  trend_name?: string
  trend_emoji?: string
  status: string
  reserved_tokens: number
  error_code?: string
  created_at: string
}

function getStatusBadge(status: string) {
  const variants: Record<string, 'info' | 'warning' | 'success' | 'error' | 'default'> = {
    CREATED: 'info',
    RUNNING: 'warning',
    SUCCEEDED: 'success',
    FAILED: 'error',
    ERROR: 'error',
  }
  return variants[status] || 'default'
}

function copyToClipboard(text: string, setCopied: (id: string | null) => void) {
  navigator.clipboard.writeText(text).then(() => {
    setCopied(text)
    setTimeout(() => setCopied(null), 2000)
  })
}

export function JobsPage() {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [period, setPeriod] = useState('all')
  const [trendId, setTrendId] = useState('')
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [errorDetailJob, setErrorDetailJob] = useState<JobItem | null>(null)

  const hours = PERIOD_OPTIONS.find((p) => p.value === period)?.hours ?? null

  const { data, isLoading } = useQuery({
    queryKey: ['jobs', page, pageSize, status, search, trendId, hours],
    queryFn: () =>
      jobsService.list({
        page,
        page_size: pageSize,
        status: status || undefined,
        telegram_id: search || undefined,
        trend_id: trendId || undefined,
        hours: hours ?? undefined,
      }),
  })

  const { data: stats } = useQuery({
    queryKey: ['jobs-stats', hours],
    queryFn: () => jobsService.stats(hours ?? 24),
    enabled: hours != null,
  })

  const { data: trendsData } = useQuery({
    queryKey: ['trends-list-for-jobs'],
    queryFn: () => trendsService.list(),
  })

  const handleStatusChange = (value: string) => {
    setStatus(value === 'all' ? '' : value)
    setPage(1)
  }

  const total = data?.total ?? 0
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)
  const items = (data?.items ?? []) as JobItem[]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Задачи</h1>
        <p className="mt-2 text-muted-foreground">
          Мониторинг задач генерации изображений
        </p>
      </div>

      {hours != null && stats && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <span className="text-sm font-medium text-muted-foreground">
                Всего за период
              </span>
              <Briefcase className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatNumber(stats.total)}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <span className="text-sm font-medium text-muted-foreground">
                Успешно
              </span>
              <TrendingUp className="h-4 w-4 text-emerald-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-emerald-600">
                {formatNumber(stats.succeeded)}
              </div>
              <p className="text-xs text-muted-foreground">
                {stats.total > 0
                  ? `${Math.round((stats.succeeded / stats.total) * 100)}% от периода`
                  : '—'}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <span className="text-sm font-medium text-muted-foreground">
                Ошибки
              </span>
              <AlertCircle className="h-4 w-4 text-red-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-red-600">
                {formatNumber(stats.failed)}
              </div>
              <p className="text-xs text-muted-foreground">
                {stats.total > 0
                  ? `${Math.round((stats.failed / stats.total) * 100)}% от периода`
                  : '—'}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <span className="text-sm font-medium text-muted-foreground">
                В очереди
              </span>
              <ListTodo className="h-4 w-4 text-amber-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatNumber(stats.in_queue)}</div>
            </CardContent>
          </Card>
        </div>
      )}

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <Select value={status || 'all'} onValueChange={handleStatusChange}>
              <SelectTrigger className="w-44">
                <Filter className="mr-2 h-4 w-4" />
                <SelectValue placeholder="Все статусы" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все статусы</SelectItem>
                <SelectItem value="CREATED">Создана</SelectItem>
                <SelectItem value="RUNNING">Выполняется</SelectItem>
                <SelectItem value="SUCCEEDED">Успешно</SelectItem>
                <SelectItem value="FAILED">Ошибка</SelectItem>
                <SelectItem value="ERROR">Ошибка (ERROR)</SelectItem>
              </SelectContent>
            </Select>

            <Select value={period} onValueChange={(v) => { setPeriod(v); setPage(1) }}>
              <SelectTrigger className="w-36">
                <Clock className="mr-2 h-4 w-4" />
                <SelectValue placeholder="Период" />
              </SelectTrigger>
              <SelectContent>
                {PERIOD_OPTIONS.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={trendId || 'all'} onValueChange={(v) => { setTrendId(v === 'all' ? '' : v); setPage(1) }}>
              <SelectTrigger className="w-48">
                <SelectValue placeholder="Тренд" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все тренды</SelectItem>
                {(Array.isArray(trendsData) ? trendsData : []).map((t: { id: string; name: string; emoji?: string }) => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.emoji ? `${t.emoji} ` : ''}{t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="relative flex-1 min-w-[200px] max-w-sm">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Поиск по Telegram ID..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && setPage(1)}
                className="pl-8"
              />
            </div>

            <Select
              value={String(pageSize)}
              onValueChange={(v) => { setPageSize(Number(v)); setPage(1) }}
            >
              <SelectTrigger className="w-24">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PAGE_SIZES.map((n) => (
                  <SelectItem key={n} value={String(n)}>{n}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : !items.length ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <Briefcase className="h-12 w-12 text-muted-foreground/50" />
              <p className="mt-2 font-medium text-foreground">Нет задач</p>
              <p className="text-sm text-muted-foreground">
                Измените фильтры или период
              </p>
            </div>
          ) : (
            <>
              <p className="mb-3 text-xs text-muted-foreground">
                Показано {formatNumber(from)}–{formatNumber(to)} из {formatNumber(total)}
              </p>
              <div className="overflow-x-auto rounded-lg border border-border">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="w-10"> </TableHead>
                      <TableHead className="font-mono">ID</TableHead>
                      <TableHead>Telegram ID</TableHead>
                      <TableHead>Тренд</TableHead>
                      <TableHead>Статус</TableHead>
                      <TableHead>Токены</TableHead>
                      <TableHead>Ошибка</TableHead>
                      <TableHead>Создана</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((job) => (
                      <TableRow key={job.job_id} className="hover:bg-muted/40">
                        <TableCell className="w-10">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => copyToClipboard(job.job_id, setCopiedId)}
                            title="Копировать ID"
                          >
                            {copiedId === job.job_id ? (
                              <Check className="h-4 w-4 text-emerald-600" />
                            ) : (
                              <Copy className="h-4 w-4" />
                            )}
                          </Button>
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {job.job_id.substring(0, 8)}…
                        </TableCell>
                        <TableCell className="font-mono">{job.telegram_id || '—'}</TableCell>
                        <TableCell>
                          <Link
                            to="/trends"
                            className="text-primary hover:underline"
                            title={job.trend_name ?? job.trend_id}
                          >
                            {job.trend_emoji ? `${job.trend_emoji} ` : ''}
                            {job.trend_name || job.trend_id.substring(0, 8)}
                          </Link>
                        </TableCell>
                        <TableCell>
                          <Badge variant={getStatusBadge(job.status)}>
                            {job.status}
                          </Badge>
                        </TableCell>
                        <TableCell>{job.reserved_tokens}</TableCell>
                        <TableCell className="text-muted-foreground">
                          {job.error_code ? (
                            <Button
                              variant="link"
                              className="h-auto p-0 text-red-600 hover:text-red-700"
                              onClick={() => setErrorDetailJob(job)}
                            >
                              {job.error_code}
                            </Button>
                          ) : (
                            '—'
                          )}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm">
                          {formatDate(job.created_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              <Pagination
                currentPage={page}
                totalPages={data?.pages ?? 1}
                onPageChange={setPage}
              />
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!errorDetailJob} onOpenChange={() => setErrorDetailJob(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Детали ошибки</DialogTitle>
          </DialogHeader>
          {errorDetailJob && (
            <div className="space-y-2 text-sm">
              <p><span className="font-medium">Job ID:</span>{' '}
                <code className="rounded bg-muted px-1">{errorDetailJob.job_id}</code>
              </p>
              <p><span className="font-medium">Код:</span> {errorDetailJob.error_code}</p>
              <p><span className="font-medium">Создана:</span> {formatDate(errorDetailJob.created_at)}</p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => copyToClipboard(errorDetailJob.job_id, () => {})}
              >
                <Copy className="mr-2 h-4 w-4" />
                Копировать ID
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
