import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { envSettingsService, appSettingsService, type EnvItem } from '@/services/api'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Label } from '@/components/ui/label'
import { Settings, Lock, FileCode, Zap } from 'lucide-react'
import { toast } from 'sonner'

export function SettingsPage() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['env-settings'],
    queryFn: () => envSettingsService.getEnv(),
  })
  const { data: appSettings, isLoading: appSettingsLoading } = useQuery({
    queryKey: ['app-settings'],
    queryFn: () => appSettingsService.getSettings(),
  })
  const updateAppMutation = useMutation({
    mutationFn: (payload: { use_nano_banana_pro: boolean }) => appSettingsService.updateSettings(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['app-settings'] })
      toast.success('Настройки сохранены')
    },
    onError: () => toast.error('Ошибка при сохранении'),
  })
  const handleNanoBananaToggle = (checked: boolean) => {
    updateAppMutation.mutate({ use_nano_banana_pro: checked })
  }

  const items: EnvItem[] = data?.items ?? []
  const byCategory = items.reduce<Record<string, EnvItem[]>>((acc: Record<string, EnvItem[]>, it: EnvItem) => {
    if (!acc[it.category]) acc[it.category] = []
    acc[it.category].push(it)
    return acc
  }, {})
  const categories = Object.keys(byCategory).sort()

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-violet-600 to-purple-600 bg-clip-text text-transparent">
          Настройки (.env)
        </h1>
        <p className="text-muted-foreground mt-2">
          Все гиперпараметры и ограничения из переменных окружения — только чтение. Секреты замаскированы.
        </p>
      </div>

      {data?.source && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <FileCode className="h-4 w-4" />
          <span>{data.source}</span>
        </div>
      )}

      {/* Глобальные переключатели из админки */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-muted-foreground" />
            <h2 className="text-lg font-semibold">Глобальные правила генерации</h2>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Переключатели применяются ко всем генерациям без перезапуска сервисов.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          {appSettingsLoading ? (
            <Skeleton className="h-10 w-48" />
          ) : (
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                id="use_nano_banana_pro"
                checked={appSettings?.use_nano_banana_pro ?? false}
                onChange={(e) => handleNanoBananaToggle(e.target.checked)}
                disabled={updateAppMutation.isPending}
                className="h-4 w-4 rounded border-input"
              />
              <Label htmlFor="use_nano_banana_pro" className="cursor-pointer font-medium">
                Использовать Nano Banana Pro (Gemini)
              </Label>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            Включено: все запросы идут в провайдер Gemini (Nano Banana). Выключено: используется провайдер из .env (<code className="rounded bg-muted px-1">image_provider</code>).
          </p>
          {appSettings?.updated_at && (
            <p className="text-xs text-muted-foreground">
              Обновлено: {new Date(appSettings.updated_at).toLocaleString('ru-RU')}
            </p>
          )}
        </CardContent>
      </Card>

      {isLoading ? (
        <Card>
          <CardContent className="p-6">
            <Skeleton className="h-64 w-full" />
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {categories.map((category) => (
            <Card key={category}>
              <CardHeader className="pb-2">
                <div className="flex items-center gap-2">
                  <Settings className="h-5 w-5 text-muted-foreground" />
                  <h2 className="text-lg font-semibold">{category}</h2>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[200px] font-mono text-xs">Переменная</TableHead>
                      <TableHead className="min-w-[180px]">Значение</TableHead>
                      <TableHead className="text-muted-foreground">Описание / ограничение</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {byCategory[category].map((it: EnvItem) => (
                      <TableRow key={it.key}>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {it.key}
                        </TableCell>
                        <TableCell>
                          <span className="font-mono text-sm">
                            {it.value}
                          </span>
                          {(it.value.startsWith('••••') || it.value.endsWith('••••')) && (
                            <span title="Секрет" className="inline-flex align-middle">
                              <Lock className="h-3.5 w-3.5 ml-1 text-amber-500" aria-hidden />
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm max-w-md">
                          {it.description}
                          {it.raw_type && it.raw_type !== 'str' && (
                            <Badge variant="secondary" className="ml-2 text-xs">
                              {it.raw_type}
                            </Badge>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Card className="border-amber-500/50 bg-amber-500/5">
        <CardContent className="p-4">
          <p className="text-sm text-muted-foreground">
            <strong>Ограничения:</strong> изменение значений возможно только через файл <code className="rounded bg-muted px-1">.env</code> на сервере и перезапуск сервисов. 
            Лимиты загрузки (<code>max_file_size_mb</code>), форматы (<code>allowed_image_extensions</code>), таймауты и лимиты входа задаются здесь.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
