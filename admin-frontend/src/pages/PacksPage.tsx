import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { packsService, type Pack } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Package, Plus, Pencil, Info } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

const ECONOMY_HELP = `Как работает экономика:
• Бесплатно: N генераций с watermark и M раз «Сделать такую же» (настраивается в Security).
• Токены: 1 генерация = 1 токен (GENERATION_COST_TOKENS в .env). Пользователь покупает пакеты за Stars → получает токены.
• Пакеты: цены в Stars задаются здесь. В боте отображаются с примерным эквивалентом в рублях (STAR_TO_RUB).
• Разблокировка: снять watermark с одного фото — за Stars (UNLOCK_COST_STARS) или за токены (UNLOCK_COST_TOKENS).`

export function PacksPage() {
  const queryClient = useQueryClient()
  const [editingPack, setEditingPack] = useState<Pack | null>(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<Partial<Pack>>({})

  const { data: packs, isLoading } = useQuery({
    queryKey: ['packs'],
    queryFn: () => packsService.list(),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<Pack> }) =>
      packsService.update(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['packs'] })
      setEditingPack(null)
      setForm({})
      toast.success('Пакет обновлён')
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || 'Ошибка'),
  })

  const createMutation = useMutation({
    mutationFn: (payload: { name: string; tokens: number; stars_price: number; emoji?: string; description?: string; enabled?: boolean; order_index?: number }) =>
      packsService.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['packs'] })
      setCreating(false)
      setForm({})
      toast.success('Пакет создан')
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || 'Ошибка'),
  })

  const deleteMutation = useMutation({
    mutationFn: (packId: string) => packsService.delete(packId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['packs'] })
      toast.success('Пакет отключён (enabled=false)')
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || 'Ошибка'),
  })

  const openEdit = (pack: Pack) => {
    setEditingPack(pack)
    setForm({
      name: String(pack.name ?? ''),
      emoji: String(pack.emoji ?? ''),
      tokens: Number(pack.tokens ?? 0),
      stars_price: Number(pack.stars_price ?? 0),
      description: pack.description != null ? String(pack.description) : undefined,
      enabled: Boolean(pack.enabled),
      order_index: pack.order_index != null ? Number(pack.order_index) : undefined,
    })
  }

  const handleSaveEdit = () => {
    if (!editingPack) return
    updateMutation.mutate({
      id: editingPack.id,
      payload: {
        name: form.name,
        emoji: form.emoji,
        tokens: form.tokens,
        stars_price: form.stars_price,
        description: form.description,
        enabled: form.enabled,
        order_index: form.order_index,
      },
    })
  }

  const handleCreate = () => {
    if (!form.name || form.tokens == null || form.stars_price == null) {
      toast.error('Заполните название, токены и цену в Stars')
      return
    }
    createMutation.mutate({
      name: form.name!,
      tokens: Number(form.tokens),
      stars_price: Number(form.stars_price),
      emoji: typeof form.emoji === 'string' ? form.emoji : '',
      description: typeof form.description === 'string' ? form.description : '',
      enabled: form.enabled ?? true,
      order_index: form.order_index ?? (packs?.length ?? 0),
    })
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Пакеты генераций</h1>
        <p className="text-muted-foreground mt-2">
          Цены в Telegram Stars. Эти пакеты показываются в боте в разделе «Купить генерации». Изменения применяются сразу.
        </p>
      </div>

      {/* Как работает экономика */}
      <Card className="border-blue-500/30 bg-blue-500/5">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Info className="h-4 w-4" />
            Как работает экономика
          </CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-sans">{ECONOMY_HELP}</pre>
          <p className="text-xs text-muted-foreground mt-2">
            Параметры Unlock, курс Stars→₽ и стоимость генерации в токенах — в разделе «Настройки (.env)», категория «Экономика (Stars)» и «IMAGE COMMON». После смены .env нужен перезапуск.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Package className="h-5 w-5" />
            Список пакетов
          </CardTitle>
          <Button onClick={() => { setCreating(true); setForm({ name: '', emoji: '⭐', tokens: 5, stars_price: 25, description: '', enabled: true, order_index: packs?.length ?? 0 })} }>
            <Plus className="h-4 w-4 mr-2" />
            Добавить пакет
          </Button>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="text-muted-foreground py-8">Загрузка...</div>
          ) : !packs?.length ? (
            <div className="text-muted-foreground py-8">Пакетов нет. Нажмите «Добавить пакет».</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Порядок</TableHead>
                  <TableHead>ID</TableHead>
                  <TableHead>Название</TableHead>
                  <TableHead>Токены</TableHead>
                  <TableHead>Цена (Stars)</TableHead>
                  <TableHead>Описание</TableHead>
                  <TableHead>Статус</TableHead>
                  <TableHead className="w-[120px]">Действия</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {packs.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell>{p.order_index}</TableCell>
                    <TableCell className="font-mono text-xs">{p.id}</TableCell>
                    <TableCell>{p.emoji} {p.name}</TableCell>
                    <TableCell>{p.tokens}</TableCell>
                    <TableCell>{p.stars_price}⭐</TableCell>
                    <TableCell className="max-w-[200px] truncate text-muted-foreground">{String(p.description ?? '') || '—'}</TableCell>
                    <TableCell>
                      <Badge variant={p.enabled ? 'default' : 'secondary'}>{p.enabled ? 'Вкл' : 'Выкл'}</Badge>
                    </TableCell>
                    <TableCell>
                      <Button variant="ghost" size="sm" onClick={() => openEdit(p)}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      {p.enabled ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive"
                          onClick={() => deleteMutation.mutate(p.id)}
                          disabled={deleteMutation.isPending}
                        >
                          Выкл
                        </Button>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => updateMutation.mutate({ id: p.id, payload: { enabled: true } })}
                          disabled={updateMutation.isPending}
                        >
                          Вкл
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Редактирование */}
      <Dialog open={!!editingPack} onOpenChange={(open) => !open && setEditingPack(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Редактировать пакет</DialogTitle>
            <DialogDescription>Изменения сразу отобразятся в боте.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Название</Label>
                <Input
                  value={String(form.name ?? '')}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="Starter"
                />
              </div>
              <div>
                <Label>Emoji</Label>
                <Input
                  value={String(form.emoji ?? '')}
                  onChange={(e) => setForm((f) => ({ ...f, emoji: e.target.value }))}
                  placeholder="⭐"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Токены (генераций)</Label>
                <Input
                  type="number"
                  min={1}
                  value={Number(form.tokens ?? 0)}
                  onChange={(e) => setForm((f) => ({ ...f, tokens: parseInt(e.target.value) || 0 }))}
                />
              </div>
              <div>
                <Label>Цена (Stars)</Label>
                <Input
                  type="number"
                  min={1}
                  value={Number(form.stars_price ?? 0)}
                  onChange={(e) => setForm((f) => ({ ...f, stars_price: parseInt(e.target.value) || 0 }))}
                />
              </div>
            </div>
            <div>
              <Label>Описание</Label>
              <Input
                value={String(form.description ?? '')}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="5 фото без watermark"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Порядок (order_index)</Label>
                <Input
                  type="number"
                  min={0}
                  value={Number(form.order_index ?? 0)}
                  onChange={(e) => setForm((f) => ({ ...f, order_index: parseInt(e.target.value) || 0 }))}
                />
              </div>
              <div className="flex items-center gap-2 pt-8">
                <input
                  type="checkbox"
                  id="enabled"
                  checked={form.enabled ?? true}
                  onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
                  className="h-4 w-4 rounded"
                />
                <Label htmlFor="enabled">Включён (показывать в магазине)</Label>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingPack(null)}>Отмена</Button>
            <Button onClick={handleSaveEdit} disabled={updateMutation.isPending}>
              Сохранить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Создание */}
      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Новый пакет</DialogTitle>
            <DialogDescription>Обязательны: название, токены, цена в Stars.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Название *</Label>
                <Input
                  value={String(form.name ?? '')}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="Starter"
                />
              </div>
              <div>
                <Label>Emoji</Label>
                <Input
                  value={String(form.emoji ?? '')}
                  onChange={(e) => setForm((f) => ({ ...f, emoji: e.target.value }))}
                  placeholder="⭐"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Токены (генераций) *</Label>
                <Input
                  type="number"
                  min={1}
                  value={Number(form.tokens ?? 0)}
                  onChange={(e) => setForm((f) => ({ ...f, tokens: parseInt(e.target.value) || 0 }))}
                />
              </div>
              <div>
                <Label>Цена (Stars) *</Label>
                <Input
                  type="number"
                  min={1}
                  value={Number(form.stars_price ?? 0)}
                  onChange={(e) => setForm((f) => ({ ...f, stars_price: parseInt(e.target.value) || 0 }))}
                />
              </div>
            </div>
            <div>
              <Label>Описание</Label>
              <Input
                value={String(form.description ?? '')}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="5 фото без watermark"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Порядок</Label>
                <Input
                  type="number"
                  min={0}
                  value={Number(form.order_index ?? 0)}
                  onChange={(e) => setForm((f) => ({ ...f, order_index: parseInt(e.target.value) || 0 }))}
                />
              </div>
              <div className="flex items-center gap-2 pt-8">
                <input
                  type="checkbox"
                  id="create_enabled"
                  checked={form.enabled ?? true}
                  onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
                  className="h-4 w-4 rounded"
                />
                <Label htmlFor="create_enabled">Включён</Label>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreating(false)}>Отмена</Button>
            <Button onClick={handleCreate} disabled={createMutation.isPending}>
              Создать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
