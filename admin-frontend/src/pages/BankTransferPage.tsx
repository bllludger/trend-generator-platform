import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { bankTransferService, type BankTransferSettings, type BankTransferReceiptLogEntry } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { CreditCard, Package, TrendingUp, Save, FileText, MessageSquare, ListChecks, ImageIcon, ChevronLeft, ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

export function BankTransferPage() {
  const queryClient = useQueryClient()
  const { data: settings, isLoading } = useQuery<BankTransferSettings>({
    queryKey: ['bank-transfer-settings'],
    queryFn: () => bankTransferService.getSettings(),
  })

  const [enabled, setEnabled] = useState(false)
  const [cardNumber, setCardNumber] = useState('')
  const [comment, setComment] = useState('')
  const [receiptSystemPrompt, setReceiptSystemPrompt] = useState('')
  const [receiptUserPrompt, setReceiptUserPrompt] = useState('')
  const [receiptVisionModel, setReceiptVisionModel] = useState('gpt-4o')
  const [amountToleranceAbs, setAmountToleranceAbs] = useState(1)
  const [amountTolerancePct, setAmountTolerancePct] = useState(0.02)
  const [step1Description, setStep1Description] = useState('')
  const [step2Requisites, setStep2Requisites] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [amountMismatchMessage, setAmountMismatchMessage] = useState('')

  const [receiptLogPage, setReceiptLogPage] = useState(1)
  const [receiptLogPageSize] = useState(20)
  const [receiptLogMatchFilter, setReceiptLogMatchFilter] = useState<boolean | ''>('')
  const [receiptLogTelegramFilter, setReceiptLogTelegramFilter] = useState('')

  const { data: receiptLogsData, isLoading: receiptLogsLoading } = useQuery({
    queryKey: ['bank-transfer-receipt-logs', receiptLogPage, receiptLogPageSize, receiptLogMatchFilter, receiptLogTelegramFilter],
    queryFn: () =>
      bankTransferService.getReceiptLogs({
        page: receiptLogPage,
        page_size: receiptLogPageSize,
        ...(receiptLogMatchFilter !== '' ? { match_success: receiptLogMatchFilter as boolean } : {}),
        ...(receiptLogTelegramFilter.trim() ? { telegram_user_id: receiptLogTelegramFilter.trim() } : {}),
      }),
  })

  const handleOpenReceiptFile = async (logId: string) => {
    try {
      const blob = await bankTransferService.getReceiptLogFile(logId)
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank', 'noopener')
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch (e: unknown) {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Не удалось загрузить файл')
    }
  }

  useEffect(() => {
    if (!settings) return
    setEnabled(settings.enabled)
    setCardNumber('')
    setComment(settings.comment ?? '')
    setReceiptSystemPrompt(settings.receipt_system_prompt ?? '')
    setReceiptUserPrompt(settings.receipt_user_prompt ?? '')
    setReceiptVisionModel(settings.receipt_vision_model ?? 'gpt-4o')
    setAmountToleranceAbs(settings.amount_tolerance_abs ?? 1)
    setAmountTolerancePct(settings.amount_tolerance_pct ?? 0.02)
    setStep1Description(settings.step1_description ?? '')
    setStep2Requisites(settings.step2_requisites ?? '')
    setSuccessMessage(settings.success_message ?? '')
    setAmountMismatchMessage(settings.amount_mismatch_message ?? '')
  }, [settings])

  const updateMutation = useMutation({
    mutationFn: (payload: Parameters<typeof bankTransferService.updateSettings>[0]) =>
      bankTransferService.updateSettings(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bank-transfer-settings'] })
      toast.success('Настройки сохранены')
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail ?? 'Ошибка сохранения')
    },
  })

  const handleSave = () => {
    const payload: Parameters<typeof bankTransferService.updateSettings>[0] = {
      enabled,
      comment,
      receipt_system_prompt: receiptSystemPrompt,
      receipt_user_prompt: receiptUserPrompt,
      receipt_vision_model: receiptVisionModel,
      amount_tolerance_abs: amountToleranceAbs,
      amount_tolerance_pct: amountTolerancePct,
      step1_description: step1Description,
      step2_requisites: step2Requisites,
      success_message: successMessage,
      amount_mismatch_message: amountMismatchMessage,
    }
    if (cardNumber.trim() !== '') payload.card_number = cardNumber.trim()
    updateMutation.mutate(payload)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-muted-foreground">Загрузка...</div>
      </div>
    )
  }

  const rate = settings?.star_to_rub ?? 1.3

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">💳 Оплата переводом</h1>
          <p className="text-muted-foreground mt-2">
            Главная страница управления оплатой переводом: реквизиты, промпты Vision (сумма, карта, дата, комментарий), допуски, тексты в боте и лог чеков. Всё настраивается здесь; ниже отображаются текущие эффективные значения (при пустом поле в БД подставляется встроенный дефолт).
          </p>
        </div>
        <Button onClick={handleSave} disabled={updateMutation.isPending}>
          <Save className="h-4 w-4 mr-2" />
          {updateMutation.isPending ? 'Сохранение…' : 'Сохранить'}
        </Button>
      </div>

      {/* Реквизиты и включение */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CreditCard className="h-5 w-5" />
            Реквизиты и включение
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Если способ включён и указана карта — в магазине бота показывается кнопка «Не знаю как купить Stars».
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <input
              id="enabled"
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            <Label htmlFor="enabled">Включить оплату переводом</Label>
          </div>
          <div>
            <Label>Номер карты</Label>
            <Input
              type="text"
              placeholder={settings?.card_masked ? `Текущая: ${settings.card_masked}. Введите новый номер, чтобы изменить` : 'Номер карты Озон Банка'}
              value={cardNumber}
              onChange={(e) => setCardNumber(e.target.value)}
              className="font-mono mt-1"
            />
            <p className="text-xs text-muted-foreground mt-1">Оставьте пустым, чтобы не менять текущий номер.</p>
          </div>
          <div>
            <Label>Комментарий к переводу</Label>
            <Textarea
              placeholder="Опционально — показывается пользователю при оплате"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={2}
              className="mt-1"
            />
          </div>
        </CardContent>
      </Card>

      {/* Распознавание чека (Vision) */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            Распознавание чека (Vision)
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Промпты задают, что извлекать из чека. Ответ модели должен быть в формате JSON с ключами: amount_rub, card_number, date_time, comment. Для отсутствующих полей — NOT_FOUND. Бэкенд парсит JSON и проверяет каждое поле регулярками по правилам заявки (сумма, карта, дата, комментарий). Редактируйте здесь — это единственный источник промптов для проверки чеков.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label>Модель Vision</Label>
            <Input
              value={receiptVisionModel}
              onChange={(e) => setReceiptVisionModel(e.target.value)}
              placeholder="gpt-4o"
              className="mt-1"
            />
          </div>
          <div>
            <Label>System prompt (роль модели)</Label>
            <Textarea
              value={receiptSystemPrompt}
              onChange={(e) => setReceiptSystemPrompt(e.target.value)}
              rows={4}
              className="mt-1 font-mono text-sm"
            />
          </div>
          <div>
            <Label>User prompt (запрос к изображению)</Label>
            <Textarea
              value={receiptUserPrompt}
              onChange={(e) => setReceiptUserPrompt(e.target.value)}
              rows={4}
              className="mt-1 font-mono text-sm"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Допуск суммы, руб (абсолютный)</Label>
              <Input
                type="number"
                step={0.5}
                min={0}
                value={amountToleranceAbs}
                onChange={(e) => setAmountToleranceAbs(Number(e.target.value))}
                className="mt-1"
              />
            </div>
            <div>
              <Label>Допуск суммы, % (относительный)</Label>
              <Input
                type="number"
                step={0.01}
                min={0}
                value={amountTolerancePct}
                onChange={(e) => setAmountTolerancePct(Number(e.target.value))}
                className="mt-1"
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Сумма на чеке считается совпавшей, если разница не больше указанного руб или процента от ожидаемой.
          </p>
          <p className="text-xs text-muted-foreground border-t pt-3 mt-2">
            Регулярки извлечения (сумма, карта, дата) и параметры безопасности (макс. возраст чека 48 ч, лимит 10 попыток/час, TTL отпечатка 72 ч) задаются в коде бота; при необходимости их можно вынести в настройки.
          </p>
        </CardContent>
      </Card>

      {/* Тексты в боте */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5" />
            Тексты в боте
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Тексты, которые видит пользователь в боте. Шаг 1 — описание способа оплаты и выбор тарифа. Шаг 2 — реквизиты; обязательно используйте плейсхолдер {'{receipt_code}'} (уникальный код «оплата № N»), иначе проверка комментария на чеке не сработает. Остальные плейсхолдеры: {'{pack_name}'}, {'{tokens}'}, {'{expected_rub}'}, {'{card}'}, {'{comment_line}'}. Сообщение при успехе: {'{pack_name}'}, {'{tokens}'}, {'{balance}'}. Сообщение при ошибке показывается при несовпадении суммы, карты, комментария или даты.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label>Шаг 1 — описание (выбор тарифа)</Label>
            <Textarea
              value={step1Description}
              onChange={(e) => setStep1Description(e.target.value)}
              rows={5}
              className="mt-1"
            />
          </div>
          <div>
            <Label>Шаг 2 — реквизиты (плейсхолдеры: pack_name, tokens, expected_rub, card, comment_line, receipt_code)</Label>
            <Textarea
              value={step2Requisites}
              onChange={(e) => setStep2Requisites(e.target.value)}
              rows={8}
              className="mt-1 font-mono text-sm"
            />
          </div>
          <div>
            <Label>Сообщение при успехе (pack_name, tokens, balance)</Label>
            <Textarea
              value={successMessage}
              onChange={(e) => setSuccessMessage(e.target.value)}
              rows={5}
              className="mt-1"
            />
          </div>
          <div>
            <Label>Сообщение при несовпадении (сумма, карта, комментарий или дата) / ошибке распознавания</Label>
            <Textarea
              value={amountMismatchMessage}
              onChange={(e) => setAmountMismatchMessage(e.target.value)}
              rows={4}
              className="mt-1"
            />
          </div>
        </CardContent>
      </Card>

      {/* Тарифы и курс (только просмотр) */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Package className="h-5 w-5" />
            Тарифы в боте (3 кнопки)
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Первые 3 пакета по order_index. Меняются на странице <Link to="/packs" className="text-primary hover:underline">Пакеты (цены)</Link>.
          </p>
        </CardHeader>
        <CardContent>
          {settings?.packs_for_buttons?.length ? (
            <div className="space-y-2">
              {settings.packs_for_buttons.map((pack) => {
                const rub = Math.round(pack.stars_price * rate)
                return (
                  <div key={pack.id} className="flex items-center justify-between rounded-lg border p-3">
                    <span className="text-xl">{pack.emoji}</span>
                    <span className="font-medium">{pack.name}</span>
                    <span className="text-muted-foreground">{pack.tokens} генераций · {pack.stars_price}⭐ (~{rub} ₽)</span>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-muted-foreground py-4">Нет активных пакетов.</div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5" />
            Курс Stars → рубли
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">1⭐ = {rate} ₽</div>
          <p className="text-sm text-muted-foreground mt-2">
            Задаётся в .env (<code className="font-mono text-xs bg-muted px-1 py-0.5 rounded">STAR_TO_RUB</code>), используется для расчёта суммы перевода.
          </p>
        </CardContent>
      </Card>

      {/* Лог проверки чеков */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ListChecks className="h-5 w-5" />
            Лог проверки чеков
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            След каждой попытки распознавания чека: ответ Vision, регулярка, извлечённая и ожидаемая сумма. Кнопка «Скрин» открывает изображение чека.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <Label className="text-muted-foreground whitespace-nowrap">Совпадение:</Label>
              <select
                value={receiptLogMatchFilter === '' ? 'all' : receiptLogMatchFilter ? 'yes' : 'no'}
                onChange={(e) =>
                  setReceiptLogMatchFilter(e.target.value === 'all' ? '' : e.target.value === 'yes')
                }
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="all">Все</option>
                <option value="yes">Да</option>
                <option value="no">Нет</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <Label className="text-muted-foreground whitespace-nowrap">Telegram ID:</Label>
              <Input
                placeholder="Фильтр по user_id"
                value={receiptLogTelegramFilter}
                onChange={(e) => setReceiptLogTelegramFilter(e.target.value)}
                className="w-40"
              />
            </div>
          </div>

          {receiptLogsLoading ? (
            <div className="text-muted-foreground py-8">Загрузка лога…</div>
          ) : !receiptLogsData?.items?.length ? (
            <div className="text-muted-foreground py-8">Записей пока нет.</div>
          ) : (
            <>
              <div className="overflow-x-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Дата</TableHead>
                      <TableHead>Пользователь</TableHead>
                      <TableHead>Ответ Vision (raw)</TableHead>
                      <TableHead className="text-right">Сумма</TableHead>
                      <TableHead className="text-right">Ожид.</TableHead>
                      <TableHead>Сумма ОК</TableHead>
                      <TableHead>Карта</TableHead>
                      <TableHead>Карта ОК</TableHead>
                      <TableHead>Коммент. ОК</TableHead>
                      <TableHead>Дата чека</TableHead>
                      <TableHead>Причина отказа</TableHead>
                      <TableHead>Пакет</TableHead>
                      <TableHead>Платёж</TableHead>
                      <TableHead>Ошибка</TableHead>
                      <TableHead></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {receiptLogsData.items.map((log: BankTransferReceiptLogEntry) => (
                      <TableRow key={log.id}>
                        <TableCell className="whitespace-nowrap text-muted-foreground">
                          {log.created_at
                            ? new Date(log.created_at).toLocaleString('ru-RU', {
                                dateStyle: 'short',
                                timeStyle: 'short',
                              })
                            : '—'}
                        </TableCell>
                        <TableCell>
                          {log.username ? `@${log.username}` : log.telegram_user_id}
                        </TableCell>
                        <TableCell className="max-w-[220px]">
                          <span
                            className="block truncate font-mono text-xs"
                            title={String(log.raw_vision_response ?? '')}
                          >
                            {String(log.raw_vision_response ?? '') || '—'}
                          </span>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {log.extracted_amount_rub != null ? `${log.extracted_amount_rub} ₽` : '—'}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {log.expected_rub != null ? `${log.expected_rub} ₽` : '—'}
                        </TableCell>
                        <TableCell>{log.match_success ? '✅' : '❌'}</TableCell>
                        <TableCell className="font-mono text-xs whitespace-nowrap">
                          {log.extracted_card_first4 && log.extracted_card_last4
                            ? `${log.extracted_card_first4}****${log.extracted_card_last4}`
                            : '—'}
                        </TableCell>
                        <TableCell>{log.card_match_success == null ? '—' : log.card_match_success ? '✅' : '❌'}</TableCell>
                        <TableCell>
                          {log.comment_match_success == null ? '—' : log.comment_match_success ? '✅' : '❌'}
                          {log.extracted_comment && (
                            <span className="block truncate text-xs text-muted-foreground max-w-[100px]" title={String(log.extracted_comment ?? '')}>
                              {String(log.extracted_comment ?? '')}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                          {log.extracted_receipt_dt
                            ? new Date(String(log.extracted_receipt_dt)).toLocaleString('ru-RU', {
                                dateStyle: 'short',
                                timeStyle: 'short',
                              })
                            : '—'}
                        </TableCell>
                        <TableCell className="max-w-[130px]">
                          {log.rejection_reason ? (
                            <span className="text-destructive text-xs font-medium">{log.rejection_reason}</span>
                          ) : '—'}
                        </TableCell>
                        <TableCell className="font-mono text-xs">{log.pack_id || '—'}</TableCell>
                        <TableCell>
                          {log.payment_id ? (
                            <Link
                              to="/payments"
                              className="text-primary hover:underline font-mono text-xs"
                            >
                              {(log.payment_id ?? '').slice(0, 8)}…
                            </Link>
                          ) : (
                            '—'
                          )}
                        </TableCell>
                        <TableCell className="max-w-[180px]">
                          <span
                            className="block truncate text-destructive text-xs"
                            title={String(log.error_message ?? '')}
                          >
                            {String(log.error_message ?? '') || '—'}
                          </span>
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleOpenReceiptFile(log.id)}
                            title="Открыть скрин чека"
                          >
                            <ImageIcon className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {(receiptLogsData.pages ?? Math.ceil(receiptLogsData.total / 20)) > 1 && (
                <div className="flex items-center justify-between">
                  <p className="text-sm text-muted-foreground">
                    Всего {receiptLogsData.total}, стр. {receiptLogPage} из {receiptLogsData.pages ?? Math.ceil(receiptLogsData.total / 20)}
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={receiptLogPage <= 1}
                      onClick={() => setReceiptLogPage((p) => p - 1)}
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={receiptLogPage >= (receiptLogsData.pages ?? Math.ceil(receiptLogsData.total / 20))}
                      onClick={() => setReceiptLogPage((p) => p + 1)}
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
