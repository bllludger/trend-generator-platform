import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { broadcastService } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Send,
  Users,
  AlertTriangle,
  Loader2,
  Megaphone,
  CheckCircle2,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

const MAX_MESSAGE_LENGTH = 4096

export function BroadcastPage() {
  const queryClient = useQueryClient()
  const [message, setMessage] = useState('')
  const [includeBlocked, setIncludeBlocked] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const { data: preview, isLoading: previewLoading, refetch: refetchPreview } = useQuery({
    queryKey: ['broadcast-preview', includeBlocked],
    queryFn: () => broadcastService.getPreview(includeBlocked),
  })

  const sendMutation = useMutation({
    mutationFn: () => broadcastService.send(message.trim(), includeBlocked),
    onSuccess: () => {
      setConfirmOpen(false)
      setMessage('')
      queryClient.invalidateQueries({ queryKey: ['broadcast-preview'] })
      toast.success(
        `Рассылка запущена! Сообщение будет отправлено ${preview?.recipients ?? 0} пользователям.`,
        { duration: 5000 }
      )
      refetchPreview()
    },
    onError: (err: any) => {
      const msg = err.response?.data?.detail || 'Ошибка при отправке'
      toast.error(typeof msg === 'string' ? msg : 'Ошибка рассылки')
    },
  })

  const handleSend = () => {
    if (!message.trim()) {
      toast.error('Введите текст сообщения')
      return
    }
    if (message.length > MAX_MESSAGE_LENGTH) {
      toast.error(`Сообщение слишком длинное (макс. ${MAX_MESSAGE_LENGTH} символов)`)
      return
    }
    sendMutation.mutate()
  }

  const canSend = message.trim().length > 0 && (preview?.recipients ?? 0) > 0

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-violet-600 to-fuchsia-600 bg-clip-text text-transparent">
          Массовая рассылка
        </h1>
        <p className="text-muted-foreground mt-2">
          Отправка сообщений всем пользователям бота через Telegram
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Охват */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Users className="h-5 w-5" />
              Охват
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {previewLoading ? (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Загрузка...
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between p-3 rounded-lg bg-violet-500/10">
                  <span className="text-sm font-medium">Получателей</span>
                  <span className="text-2xl font-bold text-violet-600">
                    {preview?.recipients ?? 0}
                  </span>
                </div>
                <div className="text-xs text-muted-foreground space-y-1">
                  <p>Всего пользователей: {preview?.total_users ?? 0}</p>
                  {!includeBlocked && (preview?.excluded ?? 0) > 0 && (
                    <p>Исключено (бан/подвеска): {preview?.excluded}</p>
                  )}
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => refetchPreview()}
                  disabled={previewLoading}
                >
                  Обновить
                </Button>
              </>
            )}
          </CardContent>
        </Card>

        {/* Сообщение */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Megaphone className="h-5 w-5" />
              Текст сообщения
            </CardTitle>
            <p className="text-sm text-muted-foreground">
              Обычный текст. Поддерживаются переносы строк. Telegram: макс. 4096 символов.
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Textarea
                placeholder="Привет! У нас обновление..."
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={8}
                className="resize-none font-mono text-sm"
                maxLength={MAX_MESSAGE_LENGTH + 100}
              />
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  {message.length} / {MAX_MESSAGE_LENGTH}
                </span>
                {message.length > MAX_MESSAGE_LENGTH && (
                  <span className="text-destructive font-medium">Сократите сообщение</span>
                )}
              </div>
            </div>

            <label className="flex items-center gap-2 cursor-pointer text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={includeBlocked}
                onChange={(e) => setIncludeBlocked(e.target.checked)}
                className="rounded border-input"
              />
              Включить забаненных и приостановленных
            </label>

            <Button
              onClick={() => setConfirmOpen(true)}
              disabled={!canSend || message.length > MAX_MESSAGE_LENGTH || sendMutation.isPending}
              className="bg-violet-600 hover:bg-violet-700"
            >
              {sendMutation.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Send className="h-4 w-4 mr-2" />
              )}
              Отправить рассылку
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Подсказка */}
      <Card className="border-dashed">
        <CardContent className="pt-6">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="h-5 w-5 text-green-600 mt-0.5 shrink-0" />
            <div className="text-sm text-muted-foreground">
              <p className="font-medium text-foreground mb-1">Как это работает</p>
              <p>
                Сообщение отправляется в личку каждому пользователю бота. Рассылка выполняется
                асинхронно (Celery) с учётом лимитов Telegram. Забаненные и приостановленные
                пользователи по умолчанию не получают сообщения.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Confirm Dialog */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-violet-600">
              <AlertTriangle className="h-5 w-5" />
              Подтверждение рассылки
            </DialogTitle>
            <DialogDescription>
              Сообщение будет отправлено <strong>{preview?.recipients ?? 0}</strong> пользователям.
              Это действие нельзя отменить. Продолжить?
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-lg bg-muted p-3 font-mono text-sm max-h-32 overflow-y-auto">
            {message.trim() || '(пусто)'}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={handleSend}
              disabled={sendMutation.isPending}
              className="bg-violet-600 hover:bg-violet-700"
            >
              {sendMutation.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Send className="h-4 w-4 mr-2" />
              )}
              Отправить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
