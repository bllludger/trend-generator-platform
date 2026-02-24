import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { telegramMessagesService, type TelegramMessageTemplate } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

export function TelegramMessagesPage() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  const { data, isLoading } = useQuery<{ items: TelegramMessageTemplate[] }>({
    queryKey: ['telegram-messages'],
    queryFn: () => telegramMessagesService.list(),
  })

  const bulkMutation = useMutation<{ updated: number }, Error, void>({
    mutationFn: () => {
      const items = Object.entries(drafts).map(([key, value]) => ({ key, value }))
      return telegramMessagesService.bulkUpdate(items)
    },
    onSuccess: (result) => {
      toast.success(`Сохранено: ${result.updated}`)
      setDrafts({})
      queryClient.invalidateQueries({ queryKey: ['telegram-messages'] })
    },
    onError: () => toast.error('Не удалось сохранить изменения'),
  })

  const resetMutation = useMutation<{ reset: number }, Error, void>({
    mutationFn: () => telegramMessagesService.resetDefaults(),
    onSuccess: (result) => {
      toast.success(`Сброшено к дефолту: ${result.reset}`)
      setDrafts({})
      queryClient.invalidateQueries({ queryKey: ['telegram-messages'] })
    },
    onError: () => toast.error('Не удалось сбросить шаблоны'),
  })

  const items = useMemo(() => {
    const list: TelegramMessageTemplate[] = data?.items ?? []
    const q = search.trim().toLowerCase()
    if (!q) return list
    return list.filter((it) =>
      [it.key, it.category, it.description, it.value].join(' ').toLowerCase().includes(q)
    )
  }, [data?.items, search])

  const grouped = useMemo(() => {
    return items.reduce<Record<string, TelegramMessageTemplate[]>>((acc, it) => {
      if (!acc[it.category]) acc[it.category] = []
      acc[it.category].push(it)
      return acc
    }, {})
  }, [items])

  const categories = Object.keys(grouped).sort()

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Telegram Messages</h1>
          <p className="text-muted-foreground mt-2">
            Все тексты бота редактируются здесь и применяются в рантайме без перезапуска.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => resetMutation.mutate()} disabled={resetMutation.isPending}>
            Сбросить к дефолту
          </Button>
          <Button onClick={() => bulkMutation.mutate()} disabled={bulkMutation.isPending || Object.keys(drafts).length === 0}>
            Сохранить изменения ({Object.keys(drafts).length})
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="pt-6">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск по key / category / description / тексту"
          />
        </CardContent>
      </Card>

      {isLoading ? (
        <Card><CardContent className="pt-6">Загрузка...</CardContent></Card>
      ) : (
        categories.map((category) => (
          <Card key={category}>
            <CardHeader>
              <CardTitle>{category}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {grouped[category].map((item) => {
                const value = drafts[item.key] ?? item.value
                return (
                  <div key={item.key} className="space-y-2 border rounded-md p-3">
                    <div className="text-xs text-muted-foreground font-mono">{item.key}</div>
                    {item.description ? <div className="text-sm text-muted-foreground">{item.description}</div> : null}
                    <Textarea
                      value={value}
                      onChange={(e) => setDrafts((prev) => ({ ...prev, [item.key]: e.target.value }))}
                      rows={4}
                    />
                  </div>
                )
              })}
            </CardContent>
          </Card>
        ))
      )}
    </div>
  )
}
