import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { cleanupService, auditService } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatDate } from '@/lib/utils'
import {
  Trash2,
  Eye,
  History,
  FileX,
  AlertTriangle,
  CheckCircle2,
  Loader2,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

const PERIOD_PRESETS = [
  { hours: 6, label: '6 ч' },
  { hours: 12, label: '12 ч' },
  { hours: 24, label: '24 ч' },
  { hours: 48, label: '48 ч' },
  { hours: 168, label: '7 д' },
] as const

export function CleanupPage() {
  const queryClient = useQueryClient()
  const [periodHours, setPeriodHours] = useState(24)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const { data: preview, isLoading: previewLoading, refetch: refetchPreview } = useQuery({
    queryKey: ['cleanup-preview', periodHours],
    queryFn: () => cleanupService.getPreview(periodHours),
  })

  const { data: history } = useQuery({
    queryKey: ['audit-cleanup'],
    queryFn: () => auditService.list({
      action: 'cleanup',
      page: 1,
      page_size: 10,
    }),
  })

  const runMutation = useMutation({
    mutationFn: () => cleanupService.run(periodHours),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['cleanup-preview'] })
      queryClient.invalidateQueries({ queryKey: ['audit-cleanup'] })
      setConfirmOpen(false)
      toast.success(
        `Очищено: ${res.cleaned_jobs} jobs, ~${res.cleaned_jobs * 2} файлов`,
        { duration: 4000 }
      )
      refetchPreview()
    },
    onError: () => {
      toast.error('Ошибка при выполнении cleanup')
    },
  })

  const handleRun = () => {
    runMutation.mutate()
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-amber-600 to-orange-600 bg-clip-text text-transparent">
          Cleanup
        </h1>
        <p className="text-muted-foreground mt-2">
          Управление временными файлами и хранилищем
        </p>
      </div>

      <Tabs defaultValue="overview" className="space-y-6">
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="overview">Обзор</TabsTrigger>
          <TabsTrigger value="history">История</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          {/* Метрики */}
          <div className="grid gap-4 md:grid-cols-3">
            <Card className="overflow-hidden">
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-muted-foreground">
                      Jobs под очистку
                    </p>
                    <p className="text-3xl font-bold mt-1">
                      {previewLoading ? '—' : preview?.jobs_count ?? 0}
                    </p>
                  </div>
                  <div className="p-3 rounded-xl bg-amber-500/20">
                    <FileX className="h-6 w-6 text-amber-600" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="overflow-hidden">
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-muted-foreground">
                      Файлов к удалению
                    </p>
                    <p className="text-3xl font-bold mt-1">
                      {previewLoading ? '—' : preview?.files_count ?? 0}
                    </p>
                  </div>
                  <div className="p-3 rounded-xl bg-orange-500/20">
                    <Trash2 className="h-6 w-6 text-orange-600" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="overflow-hidden">
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-muted-foreground">
                      Период
                    </p>
                    <p className="text-lg font-bold mt-1">
                      &gt; {periodHours} ч
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Период */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Eye className="h-5 w-5" />
                Preview (dry-run)
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                Удаляются только temp input файлы (загруженные фото) у jobs со статусом SUCCEEDED/FAILED старше выбранного периода. Output изображения не затрагиваются.
              </p>
            </CardHeader>
            <CardContent className="space-y-6">
              <div>
                <p className="text-sm font-medium mb-3">Возраст файлов</p>
                <div className="flex flex-wrap gap-2">
                  {PERIOD_PRESETS.map((p) => (
                    <Button
                      key={p.hours}
                      variant={periodHours === p.hours ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setPeriodHours(p.hours)}
                    >
                      {p.label}
                    </Button>
                  ))}
                </div>
              </div>

              <div className="flex flex-wrap gap-3">
                <Button
                  variant="outline"
                  onClick={() => refetchPreview()}
                  disabled={previewLoading}
                >
                  {previewLoading ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Eye className="h-4 w-4 mr-2" />
                  )}
                  Обновить preview
                </Button>
                <Button
                  onClick={() => setConfirmOpen(true)}
                  disabled={!preview?.jobs_count || runMutation.isPending}
                  className="bg-amber-600 hover:bg-amber-700"
                >
                  {runMutation.isPending ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4 mr-2" />
                  )}
                  Запустить cleanup
                </Button>
              </div>

              {preview && preview.jobs_count === 0 && (
                <div className="flex items-center gap-2 p-4 rounded-lg bg-green-500/10 text-green-700 dark:text-green-400">
                  <CheckCircle2 className="h-5 w-5 shrink-0" />
                  <p className="text-sm">
                    Нет файлов для очистки — хранилище в порядке
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="history" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <History className="h-5 w-5" />
                История cleanup
              </CardTitle>
            </CardHeader>
            <CardContent>
              {history?.items?.length ? (
                <div className="space-y-3">
                  {history.items.map((entry: any) => (
                    <div
                      key={entry.id}
                      className="flex items-center justify-between p-3 border rounded-lg"
                    >
                      <div>
                        <p className="font-medium text-sm">
                          older_than_hours: {entry.payload?.older_than_hours ?? '—'}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {formatDate(entry.created_at)}
                        </p>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {entry.actor_type}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">
                  История пуста — cleanup ещё не выполнялся
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Confirm Dialog */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-amber-600">
              <AlertTriangle className="h-5 w-5" />
              Подтверждение
            </DialogTitle>
            <DialogDescription>
              Будет удалено <strong>{preview?.jobs_count ?? 0}</strong> temp input
              файлов (~{preview?.files_count ?? 0} файлов) старше{' '}
              <strong>{periodHours} ч</strong>. Это действие необратимо. Output
              изображения не затрагиваются.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={handleRun}
              disabled={runMutation.isPending}
              className="bg-amber-600 hover:bg-amber-700"
            >
              {runMutation.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4 mr-2" />
              )}
              Выполнить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
