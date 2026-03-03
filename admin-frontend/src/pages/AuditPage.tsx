import { useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { auditService, type AuditAnalytics } from '@/services/api'
import type { AuditLog as AuditLogType } from '@/types'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Pagination } from '@/components/Pagination'
import { formatDate } from '@/lib/utils'
import {
  Filter,
  Search,
  Activity,
  User,
  Shield,
  Cpu,
  Copy,
  Check,
  FileJson,
  MessageSquare,
  Server,
  Eye,
  Radio,
  BarChart3,
  TrendingUp,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'

const ACTOR_TYPES = [
  { value: 'all', label: 'Все акторы' },
  { value: 'user', label: 'Пользователи' },
  { value: 'system', label: 'Система' },
  { value: 'admin', label: 'Админ' },
]

const ACTIONS = [
  'start', 'trends_shown', 'trend_selected', 'job_created', 'job_started',
  'generation_request', 'generation_response',
  'job_succeeded', 'job_failed', 'create', 'update', 'delete', 'cleanup',
  'user_banned', 'user_unbanned', 'user_suspended', 'user_resumed', 'rate_limit_set', 'bulk_action',
  'audience_selected', 'take_started',
]

const AUDIENCE_FILTER_OPTIONS = [
  { value: 'all', label: 'Все ЦА' },
  { value: 'women', label: 'Женщины' },
  { value: 'men', label: 'Мужчины' },
  { value: 'couples', label: 'Пары' },
]

const AUDIENCE_LABELS: Record<string, string> = {
  women: 'Женщины',
  men: 'Мужчины',
  couples: 'Пары',
}

const ENTITY_TYPES = ['session', 'trend', 'job', 'user', 'trend_prompt', 'temp_files']

const DATE_PRESETS = [
  { value: '24', label: '24 ч' },
  { value: '168', label: '7 д' },
  { value: '720', label: '30 д' },
]

const ACTION_LABELS: Record<string, string> = {
  start: 'Вход в бота',
  trends_shown: 'Показаны тренды',
  trend_selected: 'Выбран тренд',
  job_created: 'Создана задача',
  job_started: 'Задача запущена',
  generation_request: 'Запрос в Gemini',
  generation_response: 'Ответ от провайдера',
  job_succeeded: 'Задача выполнена',
  job_failed: 'Задача провалена',
  create: 'Создание',
  update: 'Обновление',
  delete: 'Удаление',
  cleanup: 'Очистка',
  user_banned: 'Пользователь забанен',
  user_unbanned: 'Пользователь разбанен',
  user_suspended: 'Пользователь приостановлен',
  user_resumed: 'Пользователь возобновлён',
  rate_limit_set: 'Установлен лимит',
  bulk_action: 'Массовое действие',
  audience_selected: 'Выбор ЦА',
  take_started: 'Запуск снимка (Take)',
}

const ENTITY_LABELS: Record<string, string> = {
  session: 'Сессия',
  trend: 'Тренд',
  job: 'Задача',
  user: 'Пользователь',
  trend_prompt: 'Промпт тренда',
  temp_files: 'Временные файлы',
}

function fallbackCopyText(text: string): boolean {
  try {
    const el = document.createElement('textarea')
    el.value = text
    el.setAttribute('readonly', '')
    el.style.position = 'fixed'
    el.style.left = '-9999px'
    el.style.top = '0'
    document.body.appendChild(el)
    el.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(el)
    return ok
  } catch {
    return false
  }
}

function useCopyToClipboard() {
  const [copied, setCopied] = useState(false)
  const copy = useCallback(async (text: string) => {
    const str = typeof text === 'string' ? text : JSON.stringify(text)
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(str)
      } else {
        if (!fallbackCopyText(str)) throw new Error('Clipboard not available')
      }
      setCopied(true)
      toast.success('Скопировано в буфер')
      setTimeout(() => setCopied(false), 2000)
    } catch {
      if (fallbackCopyText(str)) {
        setCopied(true)
        toast.success('Скопировано в буфер')
        setTimeout(() => setCopied(false), 2000)
      } else {
        toast.error('Не удалось скопировать (нужен HTTPS или разрешение)')
      }
    }
  }, [])
  return { copy, copied }
}

function PayloadPreview({
  payload,
  action,
  entityType,
  entityId,
}: {
  payload: Record<string, unknown>
  action: string
  entityType?: string
  entityId?: string
}) {
  const keys = Object.keys(payload ?? {})
  if (keys.length === 0) {
    if (entityId && entityType) {
      const label = entityType === 'trend' ? 'trend_id' : entityType === 'job' ? 'job_id' : 'entity_id'
      return (
        <span className="text-muted-foreground text-xs">
          {label}: {String(entityId).slice(0, 20)}{String(entityId).length > 20 ? '…' : ''}
        </span>
      )
    }
    return <span className="text-muted-foreground text-xs">—</span>
  }
  if (action === 'generation_request' && typeof payload?.request_as_seen_by_provider === 'string') {
    const text = payload.request_as_seen_by_provider as string
    return (
      <div className="max-w-[340px] space-y-0.5 text-xs">
        <div className="text-muted-foreground line-clamp-2">{text}</div>
        <span className="text-muted-foreground">откройте для деталей</span>
      </div>
    )
  }
  if (action === 'generation_response') {
    const summary = payload?.response_summary as Record<string, unknown> | undefined
    const asSeen = summary && typeof summary.response_as_seen_by_provider === 'string'
      ? summary.response_as_seen_by_provider as string
      : ''
    if (asSeen) {
      return (
        <div className="max-w-[340px] space-y-0.5 text-xs">
          <div className="text-muted-foreground line-clamp-2">{asSeen}</div>
          <span className="text-muted-foreground">откройте для деталей</span>
        </div>
      )
    }
  }
  const previewKeys =
    action === 'generation_request'
      ? ['prompt_length', 'model', 'trend_id']
      : action === 'generation_response'
        ? ['provider', 'model', 'finish_reason']
        : keys
  const showKeys = previewKeys.filter((k) => keys.includes(k)).slice(0, 4)
  return (
    <div className="max-w-[260px] space-y-0.5 text-xs">
      {showKeys.map((k) => (
        <div key={k} className="flex gap-2 truncate">
          <span className="shrink-0 font-medium text-muted-foreground">{k}:</span>
          <span className="truncate text-muted-foreground">
            {typeof payload[k] === 'object'
              ? JSON.stringify(payload[k])
              : String(payload[k])}
          </span>
        </div>
      ))}
      {keys.length > 4 && (
        <span className="text-muted-foreground">+{keys.length - 4} · откройте для деталей</span>
      )}
    </div>
  )
}

function CopyButton({ text, label = 'Копировать' }: { text: string; label?: string }) {
  const { copy, copied } = useCopyToClipboard()
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className="h-8 gap-1.5 text-xs"
      onClick={() => copy(text)}
    >
      {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? 'Скопировано' : label}
    </Button>
  )
}

function AuditDetailPanel({
  log,
  onClose,
}: {
  log: AuditLogType
  onClose: () => void
}) {
  const { action, payload } = log
  const isRequest = action === 'generation_request'
  const isResponse = action === 'generation_response'

  const promptText = isRequest && typeof payload?.prompt === 'string' ? payload.prompt : ''
  const meta = isRequest && payload ? { ...payload } : {}
  if (isRequest && 'prompt' in meta) delete meta.prompt
  const requestAsSeen = isRequest && typeof payload?.request_as_seen_by_provider === 'string' ? payload.request_as_seen_by_provider : ''
  const requestParts = (isRequest && Array.isArray(payload?.request_parts) ? payload.request_parts : []) as Array<{ type?: string; order?: number; description?: string; char_count?: number }>
  const responseSummary = isResponse && payload?.response_summary ? (payload.response_summary as Record<string, unknown>) : null
  const responseAsSeen = responseSummary && typeof responseSummary.response_as_seen_by_provider === 'string' ? responseSummary.response_as_seen_by_provider : ''
  const rawGeminiResponse = isResponse && payload?.raw_gemini_response != null ? payload.raw_gemini_response : null
  const rawJson = JSON.stringify(payload ?? {}, null, 2)

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="flex w-full flex-col sm:max-w-2xl">
        <SheetHeader className="shrink-0 space-y-2 border-b pb-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{ACTION_LABELS[action] ?? action}</Badge>
            <span className="text-muted-foreground text-sm">
              {formatDate(log.created_at)}
              {log.entity_id && ` · ${log.entity_type} ${log.entity_id}`}
            </span>
          </div>
          <SheetTitle className="sr-only">Детали записи аудита</SheetTitle>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-hidden pt-4">
          {isRequest ? (
            <Tabs defaultValue="gemini" className="flex h-full flex-col">
              <TabsList className="shrink-0">
                <TabsTrigger value="gemini" className="gap-1.5">
                  <Eye className="h-3.5 w-3.5" />
                  Как видит Gemini
                </TabsTrigger>
                <TabsTrigger value="prompt" className="gap-1.5">
                  <MessageSquare className="h-3.5 w-3.5" />
                  Промпт
                </TabsTrigger>
                <TabsTrigger value="meta" className="gap-1.5">
                  <FileJson className="h-3.5 w-3.5" />
                  Мета
                </TabsTrigger>
                <TabsTrigger value="raw">JSON</TabsTrigger>
              </TabsList>
              <TabsContent value="gemini" className="mt-3 min-h-0 flex-1 overflow-auto data-[state=inactive]:hidden">
                <div className="space-y-4">
                  <div>
                    <div className="flex items-center justify-between gap-2 pb-2">
                      <span className="text-muted-foreground text-sm font-medium">Запрос так, как его видит провайдер (картинки + текст)</span>
                      <CopyButton text={requestAsSeen} label="Копировать" />
                    </div>
                    <p className="rounded-lg border bg-muted/40 p-3 text-sm leading-relaxed">
                      {requestAsSeen || '—'}
                    </p>
                  </div>
                  {requestParts.length > 0 && (
                    <div>
                      <span className="text-muted-foreground text-sm font-medium">Части запроса (порядок отправки)</span>
                      <div className="mt-2 overflow-x-auto rounded-lg border">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="w-16">Порядок</TableHead>
                              <TableHead>Тип</TableHead>
                              <TableHead>Описание</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {requestParts.map((part, i) => (
                              <TableRow key={i}>
                                <TableCell className="font-mono text-xs">{part.order ?? i + 1}</TableCell>
                                <TableCell className="font-mono text-xs">{part.type ?? '—'}</TableCell>
                                <TableCell className="text-xs">
                                  {part.description ?? (part.char_count != null ? `${part.char_count} символов` : '—')}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </div>
                  )}
                </div>
              </TabsContent>
              <TabsContent value="prompt" className="mt-3 min-h-0 flex-1 overflow-auto data-[state=inactive]:hidden">
                <div className="flex items-center justify-between gap-2 pb-2">
                  <span className="text-muted-foreground text-sm">Полный текст, отправленный в Gemini</span>
                  <CopyButton text={promptText || ''} label="Копировать промпт" />
                </div>
                <pre className="rounded-lg border bg-muted/40 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words">
                  {promptText || '—'}
                </pre>
              </TabsContent>
              <TabsContent value="meta" className="mt-3 min-h-0 flex-1 overflow-auto data-[state=inactive]:hidden">
                <div className="flex items-center justify-between gap-2 pb-2">
                  <span className="text-muted-foreground text-sm">trend_id, model, size, format</span>
                  <CopyButton text={JSON.stringify(meta, null, 2)} label="Копировать" />
                </div>
                <pre className="rounded-lg border bg-muted/40 p-3 font-mono text-xs overflow-auto">
                  {JSON.stringify(meta, null, 2)}
                </pre>
              </TabsContent>
              <TabsContent value="raw" className="mt-3 min-h-0 flex-1 overflow-auto data-[state=inactive]:hidden">
                <div className="flex items-center justify-between gap-2 pb-2">
                  <span className="text-muted-foreground text-sm">Полный payload</span>
                  <CopyButton text={rawJson} />
                </div>
                <pre className="rounded-lg border bg-muted/40 p-3 font-mono text-xs overflow-auto whitespace-pre">
                  {rawJson}
                </pre>
              </TabsContent>
            </Tabs>
          ) : isResponse ? (
            <Tabs defaultValue="gemini" className="flex h-full flex-col">
              <TabsList className="shrink-0 flex-wrap gap-1">
                <TabsTrigger value="gemini" className="gap-1.5">
                  <Eye className="h-3.5 w-3.5" />
                  Как ответил Gemini
                </TabsTrigger>
                <TabsTrigger value="api" className="gap-1.5">
                  <Server className="h-3.5 w-3.5" />
                  Полный ответ API
                </TabsTrigger>
                <TabsTrigger value="response" className="gap-1.5">
                  <FileJson className="h-3.5 w-3.5" />
                  response_summary (JSON)
                </TabsTrigger>
                <TabsTrigger value="raw">Весь payload</TabsTrigger>
              </TabsList>
              <TabsContent value="gemini" className="mt-3 min-h-0 flex-1 overflow-auto data-[state=inactive]:hidden">
                <div className="space-y-4">
                  {responseAsSeen && (
                    <div>
                      <div className="flex items-center justify-between gap-2 pb-2">
                        <span className="text-muted-foreground text-sm font-medium">Ответ провайдера (как в логах)</span>
                        <CopyButton text={responseAsSeen} label="Копировать" />
                      </div>
                      <p className="rounded-lg border bg-muted/40 p-3 text-sm leading-relaxed">
                        {responseAsSeen}
                      </p>
                    </div>
                  )}
                  {responseSummary && (
                    <div>
                      <span className="text-muted-foreground text-sm font-medium">Детали ответа (response_summary)</span>
                      <div className="mt-2 space-y-1.5 rounded-lg border bg-muted/40 p-3 text-xs">
                        {responseSummary.finish_reason != null && (
                          <div className="flex gap-2"><span className="font-medium text-muted-foreground shrink-0">finish_reason:</span> <span className="font-mono">{String(responseSummary.finish_reason)}</span></div>
                        )}
                        {responseSummary.part_types != null && (
                          <div className="flex gap-2"><span className="font-medium text-muted-foreground shrink-0">part_types:</span> <span className="font-mono">{Array.isArray(responseSummary.part_types) ? responseSummary.part_types.join(', ') : String(responseSummary.part_types)}</span></div>
                        )}
                        {responseSummary.parts_count != null && (
                          <div className="flex gap-2"><span className="font-medium text-muted-foreground shrink-0">parts_count:</span> <span className="font-mono">{String(responseSummary.parts_count)}</span></div>
                        )}
                        {responseSummary.content_size_bytes != null && (
                          <div className="flex gap-2"><span className="font-medium text-muted-foreground shrink-0">content_size_bytes:</span> <span className="font-mono">{String(responseSummary.content_size_bytes)}</span></div>
                        )}
                        {responseSummary.text_preview != null && (
                          <div className="mt-2">
                            <span className="font-medium text-muted-foreground">text_preview (если модель вернула только текст):</span>
                            <pre className="mt-1 rounded border p-2 font-mono text-xs whitespace-pre-wrap break-words">{String(responseSummary.text_preview)}</pre>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </TabsContent>
              <TabsContent value="api" className="mt-3 min-h-0 flex-1 overflow-auto data-[state=inactive]:hidden">
                <div className="flex items-center justify-between gap-2 pb-2">
                  <span className="text-muted-foreground text-sm font-medium">Полный ответ API Gemini (raw_gemini_response, без base64)</span>
                  <CopyButton text={rawGeminiResponse != null ? JSON.stringify(rawGeminiResponse, null, 2) : rawJson} label="Копировать" />
                </div>
                <pre className="rounded-lg border bg-muted/40 p-3 font-mono text-xs overflow-auto whitespace-pre">
                  {rawGeminiResponse != null ? JSON.stringify(rawGeminiResponse, null, 2) : '— Нет данных (провайдер не Gemini или не передал raw_response_sanitized)'}
                </pre>
              </TabsContent>
              <TabsContent value="response" className="mt-3 min-h-0 flex-1 overflow-auto data-[state=inactive]:hidden">
                <div className="flex items-center justify-between gap-2 pb-2">
                  <span className="text-muted-foreground text-sm">response_summary — все поля (JSON)</span>
                  <CopyButton text={JSON.stringify(responseSummary ?? {}, null, 2)} />
                </div>
                <pre className="rounded-lg border bg-muted/40 p-3 font-mono text-xs overflow-auto whitespace-pre">
                  {JSON.stringify(responseSummary ?? {}, null, 2)}
                </pre>
              </TabsContent>
              <TabsContent value="raw" className="mt-3 min-h-0 flex-1 overflow-auto data-[state=inactive]:hidden">
                <div className="flex items-center justify-between gap-2 pb-2">
                  <span className="text-muted-foreground text-sm">Весь payload записи аудита</span>
                  <CopyButton text={rawJson} />
                </div>
                <pre className="rounded-lg border bg-muted/40 p-3 font-mono text-xs overflow-auto whitespace-pre">
                  {rawJson}
                </pre>
              </TabsContent>
            </Tabs>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground text-sm">Payload</span>
                <CopyButton text={rawJson} />
              </div>
              <pre className="max-h-[70vh] rounded-lg border bg-muted/40 p-3 font-mono text-xs overflow-auto whitespace-pre-wrap break-words">
                {rawJson}
              </pre>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function ActorIcon({ type }: { type: string }) {
  if (type === 'user') return <User className="h-3.5 w-3.5 text-blue-500" />
  if (type === 'admin') return <Shield className="h-3.5 w-3.5 text-amber-500" />
  return <Cpu className="h-3.5 w-3.5 text-muted-foreground" />
}

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 8 }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  )
}

const LIVE_REFETCH_INTERVAL_MS = 15_000

export function AuditPage() {
  const [page, setPage] = useState(1)
  const [actorType, setActorType] = useState('all')
  const [action, setAction] = useState('all')
  const [entityType, setEntityType] = useState('all')
  const [audienceFilter, setAudienceFilter] = useState('all')
  const [datePreset, setDatePreset] = useState('168')
  const [search, setSearch] = useState('')
  const [selectedLog, setSelectedLog] = useState<AuditLogType | null>(null)
  const [liveEnabled, setLiveEnabled] = useState(false)

  const dateTo = new Date()
  const dateFrom = new Date()
  dateFrom.setTime(dateFrom.getTime() - Number(datePreset) * 60 * 60 * 1000)

  const { data: stats } = useQuery({
    queryKey: ['audit-stats', datePreset],
    queryFn: () => auditService.getStats(Number(datePreset)),
    refetchInterval: liveEnabled ? LIVE_REFETCH_INTERVAL_MS : false,
  })

  const { data, isLoading } = useQuery({
    queryKey: ['audit', page, actorType, action, entityType, audienceFilter, datePreset, search],
    queryFn: () =>
      auditService.list({
        page,
        page_size: 30,
        actor_type: actorType !== 'all' ? actorType : undefined,
        action: action !== 'all' ? action : undefined,
        entity_type: entityType !== 'all' ? entityType : undefined,
        audience: audienceFilter !== 'all' ? audienceFilter : undefined,
        date_from: dateFrom.toISOString(),
        date_to: dateTo.toISOString(),
        search: search.trim() || undefined,
      }),
    refetchInterval: liveEnabled ? LIVE_REFETCH_INTERVAL_MS : false,
  })

  const { data: analytics } = useQuery<AuditAnalytics>({
    queryKey: ['audit-analytics', datePreset, actorType, action, entityType, audienceFilter],
    queryFn: () =>
      auditService.getAnalytics({
        date_from: dateFrom.toISOString(),
        date_to: dateTo.toISOString(),
        actor_type: actorType !== 'all' ? actorType : undefined,
        action: action !== 'all' ? action : undefined,
        entity_type: entityType !== 'all' ? entityType : undefined,
        audience: audienceFilter !== 'all' ? audienceFilter : undefined,
      }),
  })

  const items = (data?.items ?? []) as AuditLogType[]
  const isEmpty = !isLoading && items.length === 0

  const eventsByDayChart = (analytics?.events_by_day ?? []).map((d) => ({
    date: d.date ? d.date.slice(0, 10) : '',
    count: d.count,
    full: d.date,
  }))
  const byActionChart = Object.entries(analytics?.by_action ?? {}).map(([actionKey, count]) => ({
    name: ACTION_LABELS[actionKey] ?? actionKey,
    count,
  }))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-violet-600 to-purple-600 bg-clip-text text-transparent">
          Аудит
        </h1>
        <p className="text-muted-foreground mt-2">
          Журнал действий и запросов к генерации — удобный просмотр и отладка
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">
                  {datePreset === '24' ? '24 ч' : datePreset === '168' ? '7 д' : '30 д'}
                </p>
                <p className="text-2xl font-bold">{stats?.total ?? 0}</p>
              </div>
              <Activity className="h-8 w-8 text-violet-500/60" />
            </div>
          </CardContent>
        </Card>
        {stats?.by_actor_type &&
          Object.entries(stats.by_actor_type).map(([k, v]) => (
            <Card key={k}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-muted-foreground">
                      {k === 'user' ? 'Пользователи' : k === 'admin' ? 'Админ' : 'Система'}
                    </p>
                    <p className="text-2xl font-bold">{Number(v)}</p>
                  </div>
                  <ActorIcon type={k} />
                </div>
              </CardContent>
            </Card>
          ))}
      </div>

      <Tabs defaultValue="journal" className="space-y-4">
        <TabsList className="grid w-full max-w-[280px] grid-cols-2">
          <TabsTrigger value="journal">Журнал</TabsTrigger>
          <TabsTrigger value="analytics">Аналитика</TabsTrigger>
        </TabsList>

        <TabsContent value="journal" className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">Фильтры</span>
            </div>
            <Select value={datePreset} onValueChange={(v) => { setDatePreset(v); setPage(1) }}>
              <SelectTrigger className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DATE_PRESETS.map((p) => (
                  <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              type="button"
              variant={liveEnabled ? 'default' : 'outline'}
              size="sm"
              className="gap-1.5"
              onClick={() => setLiveEnabled((v) => !v)}
            >
              <Radio className={`h-4 w-4 ${liveEnabled ? 'animate-pulse' : ''}`} />
              Live
            </Button>
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Поиск по ID актора или сущности..."
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1) }}
                className="pl-8"
              />
            </div>
            <Select value={actorType} onValueChange={(v) => { setActorType(v); setPage(1) }}>
              <SelectTrigger className="w-36">
                <SelectValue placeholder="Актор" />
              </SelectTrigger>
              <SelectContent>
                {ACTOR_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={action} onValueChange={(v) => { setAction(v); setPage(1) }}>
              <SelectTrigger className="w-44">
                <SelectValue placeholder="Действие" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все действия</SelectItem>
                {ACTIONS.map((a) => (
                  <SelectItem key={a} value={a}>{ACTION_LABELS[a] ?? a}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={entityType} onValueChange={(v) => { setEntityType(v); setPage(1) }}>
              <SelectTrigger className="w-36">
                <SelectValue placeholder="Сущность" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все сущности</SelectItem>
                {ENTITY_TYPES.map((e) => (
                  <SelectItem key={e} value={e}>{ENTITY_LABELS[e] ?? e}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={audienceFilter} onValueChange={(v) => { setAudienceFilter(v); setPage(1) }}>
              <SelectTrigger className="w-32">
                <SelectValue placeholder="ЦА" />
              </SelectTrigger>
              <SelectContent>
                {AUDIENCE_FILTER_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <TableSkeleton />
          ) : isEmpty ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <p className="text-muted-foreground">Записей не найдено</p>
              <p className="text-muted-foreground text-sm mt-1">Измените фильтры или период</p>
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[140px]">Время</TableHead>
                    <TableHead className="min-w-[160px]">Актор</TableHead>
                    <TableHead className="min-w-[140px]">Действие</TableHead>
                    <TableHead className="w-24">ЦА</TableHead>
                    <TableHead>Сущность</TableHead>
                    <TableHead className="font-mono text-xs w-[80px]">ID</TableHead>
                    <TableHead className="min-w-[200px]">Детали</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((log) => (
                    <TableRow
                      key={log.id}
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() => setSelectedLog(log)}
                    >
                      <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                        {formatDate(log.created_at)}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <ActorIcon type={log.actor_type} />
                          {log.actor_display_name ? (
                            <span className="font-medium text-primary">{log.actor_display_name}</span>
                          ) : (
                            <>
                              <span className="font-medium">{log.actor_type}</span>
                              {log.actor_id && (
                                <span className="text-muted-foreground text-xs font-mono">
                                  {String(log.actor_id).slice(0, 12)}
                                  {String(log.actor_id).length > 12 ? '…' : ''}
                                </span>
                              )}
                            </>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="font-normal">
                          {ACTION_LABELS[log.action] ?? log.action}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {log.payload?.audience != null ? (AUDIENCE_LABELS[String(log.payload.audience)] ?? String(log.payload.audience)) : '—'}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {ENTITY_LABELS[log.entity_type] ?? log.entity_type}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {log.entity_id ? `${String(log.entity_id).slice(0, 8)}…` : '—'}
                      </TableCell>
                      <TableCell>
                        <PayloadPreview
                        payload={log.payload ?? {}}
                        action={log.action}
                        entityType={log.entity_type}
                        entityId={log.entity_id}
                      />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Pagination
                currentPage={data?.page ?? 1}
                totalPages={data?.pages ?? Math.max(1, Math.ceil((data?.total ?? 0) / 30))}
                onPageChange={setPage}
              />
            </>
          )}
        </CardContent>
      </Card>
        </TabsContent>

        <TabsContent value="analytics" className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5" />
                  События по дням
                </CardTitle>
                <CardDescription>Количество записей аудита за выбранный период</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-[280px]">
                  {eventsByDayChart.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={eventsByDayChart}>
                        <defs>
                          <linearGradient id="auditEventsGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.8} />
                            <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0.1} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                        <XAxis dataKey="date" tick={{ fontSize: 11 }} className="text-muted-foreground" />
                        <YAxis tick={{ fontSize: 11 }} className="text-muted-foreground" />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: 'hsl(var(--background))',
                            border: '1px solid hsl(var(--border))',
                            borderRadius: '8px',
                          }}
                          formatter={(value: number) => [value, 'Записей']}
                          labelFormatter={(label) => (label ? `Дата: ${label}` : '')}
                        />
                        <Area
                          type="monotone"
                          dataKey="count"
                          stroke="#8b5cf6"
                          fill="url(#auditEventsGrad)"
                          name="Записей"
                          strokeWidth={2}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="flex h-full items-center justify-center text-muted-foreground">Нет данных за период</div>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BarChart3 className="h-5 w-5" />
                  По действиям
                </CardTitle>
                <CardDescription>Разбивка по типу действия</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-[280px]">
                  {byActionChart.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={byActionChart} layout="vertical" margin={{ left: 4, right: 16 }}>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" horizontal={false} />
                        <XAxis type="number" tick={{ fontSize: 11 }} className="text-muted-foreground" />
                        <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 10 }} className="text-muted-foreground" />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: 'hsl(var(--background))',
                            border: '1px solid hsl(var(--border))',
                            borderRadius: '8px',
                          }}
                          formatter={(value: number) => [value, 'Записей']}
                        />
                        <Bar dataKey="count" fill="#8b5cf6" radius={[0, 4, 4, 0]} name="Записей" />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="flex h-full items-center justify-center text-muted-foreground">Нет данных за период</div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <User className="h-5 w-5" />
                Топ пользователей по действиям
              </CardTitle>
              <CardDescription>До 20 пользователей с наибольшим числом событий за период</CardDescription>
            </CardHeader>
            <CardContent>
              {(analytics?.top_actors?.length ?? 0) > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12">#</TableHead>
                      <TableHead>Пользователь</TableHead>
                      <TableHead className="font-mono text-xs w-24">ID</TableHead>
                      <TableHead className="text-right w-24">Действий</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {analytics!.top_actors.map((a, i) => (
                      <TableRow key={a.actor_id}>
                        <TableCell className="text-muted-foreground text-sm">{i + 1}</TableCell>
                        <TableCell className="font-medium">{a.actor_display_name || a.actor_id}</TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">{a.actor_id}</TableCell>
                        <TableCell className="text-right">{a.count}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <p className="text-muted-foreground py-8 text-center">Нет данных за период</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {selectedLog && (
        <AuditDetailPanel log={selectedLog} onClose={() => setSelectedLog(null)} />
      )}
    </div>
  )
}
