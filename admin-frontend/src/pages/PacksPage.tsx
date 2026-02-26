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
      takes_limit: pack.takes_limit ?? undefined,
      hd_amount: pack.hd_amount ?? undefined,
      is_trial: pack.is_trial ?? false,
      pack_type: pack.pack_type ?? 'legacy',
      pack_subtype: pack.pack_subtype ?? 'standalone',
      playlist: pack.playlist ?? undefined,
      favorites_cap: pack.favorites_cap ?? undefined,
      collection_label: pack.collection_label != null ? String(pack.collection_label) : undefined,
      upsell_pack_ids: pack.upsell_pack_ids ?? undefined,
      hd_sla_minutes: pack.hd_sla_minutes ?? 10,
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
        takes_limit: form.takes_limit,
        hd_amount: form.hd_amount,
        is_trial: form.is_trial,
        pack_type: form.pack_type,
        pack_subtype: form.pack_subtype,
        playlist: form.playlist,
        favorites_cap: form.favorites_cap,
        collection_label: form.collection_label,
        upsell_pack_ids: form.upsell_pack_ids,
        hd_sla_minutes: form.hd_sla_minutes,
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
      ...(form.pack_subtype && { pack_subtype: form.pack_subtype }),
      ...(form.playlist && { playlist: form.playlist }),
      ...(form.favorites_cap != null && { favorites_cap: form.favorites_cap }),
      ...(form.collection_label && { collection_label: form.collection_label }),
      ...(form.upsell_pack_ids && { upsell_pack_ids: form.upsell_pack_ids }),
      ...(form.hd_sla_minutes != null && { hd_sla_minutes: form.hd_sla_minutes }),
      ...(form.takes_limit != null && { takes_limit: form.takes_limit }),
      ...(form.hd_amount != null && { hd_amount: form.hd_amount }),
      ...(form.pack_type && { pack_type: form.pack_type }),
      ...(form.is_trial != null && { is_trial: form.is_trial }),
    } as any)
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
                  <TableHead>Тип / Подтип</TableHead>
                  <TableHead>Снимки</TableHead>
                  <TableHead>HD</TableHead>
                  <TableHead>Цена (Stars)</TableHead>
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
                    <TableCell>
                      <Badge variant={p.pack_type === 'session' ? 'default' : 'secondary'}>
                        {p.pack_type || 'legacy'}{p.is_trial ? ' (trial)' : ''}
                      </Badge>
                      {p.pack_subtype === 'collection' && (
                        <Badge variant="outline" className="ml-1">collection</Badge>
                      )}
                    </TableCell>
                    <TableCell>{p.takes_limit ?? p.tokens}</TableCell>
                    <TableCell>{p.hd_amount ?? '—'}</TableCell>
                    <TableCell>{p.stars_price}⭐</TableCell>
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
                <Label>Снимков (takes_limit)</Label>
                <Input
                  type="number"
                  min={0}
                  value={form.takes_limit != null ? Number(form.takes_limit) : ''}
                  onChange={(e) => setForm((f) => ({ ...f, takes_limit: e.target.value ? parseInt(e.target.value) : undefined }))}
                  placeholder="Пусто = legacy"
                />
              </div>
              <div>
                <Label>HD при покупке</Label>
                <Input
                  type="number"
                  min={0}
                  value={form.hd_amount != null ? Number(form.hd_amount) : ''}
                  onChange={(e) => setForm((f) => ({ ...f, hd_amount: e.target.value ? parseInt(e.target.value) : undefined }))}
                  placeholder="Пусто = 0"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Тип пакета</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={String(form.pack_type ?? 'legacy')}
                  onChange={(e) => setForm((f) => ({ ...f, pack_type: e.target.value }))}
                >
                  <option value="legacy">legacy</option>
                  <option value="session">session</option>
                </select>
              </div>
              <div>
                <Label>Подтип (subtype)</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={String(form.pack_subtype ?? 'standalone')}
                  onChange={(e) => setForm((f) => ({ ...f, pack_subtype: e.target.value }))}
                >
                  <option value="standalone">standalone</option>
                  <option value="collection">collection</option>
                </select>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="is_trial"
                checked={!!form.is_trial}
                onChange={(e) => setForm((f) => ({ ...f, is_trial: e.target.checked }))}
                className="h-4 w-4 rounded"
              />
              <Label htmlFor="is_trial">Trial (1 раз на аккаунт)</Label>
            </div>

            {form.pack_subtype === 'collection' && (
              <>
                <div className="border rounded-md p-3 space-y-3 bg-muted/30">
                  <p className="text-sm font-medium">Настройки коллекции</p>
                  <div>
                    <Label>Playlist (trend_id через запятую)</Label>
                    <Input
                      value={Array.isArray(form.playlist) ? form.playlist.join(', ') : ''}
                      onChange={(e) => {
                        const val = e.target.value
                        const ids = val.split(',').map(s => s.trim()).filter(Boolean)
                        setForm((f) => ({ ...f, playlist: ids.length > 0 ? ids : undefined }))
                      }}
                      placeholder="trend_1, trend_2, trend_3"
                    />
                  </div>
                  <div>
                    <Label>Метка коллекции (collection_label)</Label>
                    <Input
                      value={String(form.collection_label ?? '')}
                      onChange={(e) => setForm((f) => ({ ...f, collection_label: e.target.value || undefined }))}
                      placeholder="Dating Pack — 6 образов"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <Label>Favorites cap</Label>
                      <Input
                        type="number"
                        min={0}
                        value={form.favorites_cap != null ? Number(form.favorites_cap) : ''}
                        onChange={(e) => setForm((f) => ({ ...f, favorites_cap: e.target.value ? parseInt(e.target.value) : undefined }))}
                        placeholder="Авто = hd_limit * 2"
                      />
                    </div>
                    <div>
                      <Label>HD SLA (мин)</Label>
                      <Input
                        type="number"
                        min={1}
                        value={Number(form.hd_sla_minutes ?? 10)}
                        onChange={(e) => setForm((f) => ({ ...f, hd_sla_minutes: parseInt(e.target.value) || 10 }))}
                      />
                    </div>
                  </div>
                  <div>
                    <Label>Upsell pack IDs (через запятую)</Label>
                    <Input
                      value={Array.isArray(form.upsell_pack_ids) ? form.upsell_pack_ids.join(', ') : ''}
                      onChange={(e) => {
                        const val = e.target.value
                        const ids = val.split(',').map(s => s.trim()).filter(Boolean)
                        setForm((f) => ({ ...f, upsell_pack_ids: ids.length > 0 ? ids : undefined }))
                      }}
                      placeholder="dating_pack_2, avatar_pack_2"
                    />
                  </div>
                </div>
              </>
            )}

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
                <Label>Тип пакета</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={String(form.pack_type ?? 'session')}
                  onChange={(e) => setForm((f) => ({ ...f, pack_type: e.target.value }))}
                >
                  <option value="legacy">legacy</option>
                  <option value="session">session</option>
                </select>
              </div>
              <div>
                <Label>Подтип</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={String(form.pack_subtype ?? 'standalone')}
                  onChange={(e) => setForm((f) => ({ ...f, pack_subtype: e.target.value }))}
                >
                  <option value="standalone">standalone</option>
                  <option value="collection">collection</option>
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Снимков (takes_limit)</Label>
                <Input
                  type="number"
                  min={0}
                  value={form.takes_limit != null ? Number(form.takes_limit) : ''}
                  onChange={(e) => setForm((f) => ({ ...f, takes_limit: e.target.value ? parseInt(e.target.value) : undefined }))}
                  placeholder="Кол-во снимков"
                />
              </div>
              <div>
                <Label>HD при покупке</Label>
                <Input
                  type="number"
                  min={0}
                  value={form.hd_amount != null ? Number(form.hd_amount) : ''}
                  onChange={(e) => setForm((f) => ({ ...f, hd_amount: e.target.value ? parseInt(e.target.value) : undefined }))}
                  placeholder="0"
                />
              </div>
            </div>
            {form.pack_subtype === 'collection' && (
              <div className="border rounded-md p-3 space-y-3 bg-muted/30">
                <p className="text-sm font-medium">Настройки коллекции</p>
                <div>
                  <Label>Playlist (trend_id через запятую)</Label>
                  <Input
                    value={Array.isArray(form.playlist) ? form.playlist.join(', ') : ''}
                    onChange={(e) => {
                      const ids = e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                      setForm((f) => ({ ...f, playlist: ids.length > 0 ? ids : undefined }))
                    }}
                    placeholder="trend_1, trend_2, trend_3"
                  />
                </div>
                <div>
                  <Label>Метка коллекции</Label>
                  <Input
                    value={String(form.collection_label ?? '')}
                    onChange={(e) => setForm((f) => ({ ...f, collection_label: e.target.value || undefined }))}
                    placeholder="Dating Pack — 6 образов"
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label>Favorites cap</Label>
                    <Input
                      type="number"
                      min={0}
                      value={form.favorites_cap != null ? Number(form.favorites_cap) : ''}
                      onChange={(e) => setForm((f) => ({ ...f, favorites_cap: e.target.value ? parseInt(e.target.value) : undefined }))}
                      placeholder="Авто"
                    />
                  </div>
                  <div>
                    <Label>HD SLA (мин)</Label>
                    <Input
                      type="number"
                      min={1}
                      value={Number(form.hd_sla_minutes ?? 10)}
                      onChange={(e) => setForm((f) => ({ ...f, hd_sla_minutes: parseInt(e.target.value) || 10 }))}
                    />
                  </div>
                </div>
                <div>
                  <Label>Upsell pack IDs (через запятую)</Label>
                  <Input
                    value={Array.isArray(form.upsell_pack_ids) ? form.upsell_pack_ids.join(', ') : ''}
                    onChange={(e) => {
                      const ids = e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                      setForm((f) => ({ ...f, upsell_pack_ids: ids.length > 0 ? ids : undefined }))
                    }}
                    placeholder="dating_pack_2"
                  />
                </div>
              </div>
            )}
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
