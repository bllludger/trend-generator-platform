import { useQuery } from '@tanstack/react-query'
import { envSettingsService, type EnvItem } from '@/services/api'
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
import { Settings, Lock, FileCode } from 'lucide-react'
import { Link } from 'react-router-dom'

export function SettingsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['env-settings'],
    queryFn: () => envSettingsService.getEnv(),
  })

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

      <p className="text-sm text-muted-foreground">
        Глобальный выбор модели и дефолты генерации — в разделе <Link to="/master-prompt" className="underline text-primary">Мастер промпт</Link> (блок «Глобальная конфигурация модели»).
      </p>

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
                              <Lock className="h-3.5 w-3.5 ml-1 text-warning" aria-hidden />
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

      <Card className="border-warning/50 bg-warning/5">
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
