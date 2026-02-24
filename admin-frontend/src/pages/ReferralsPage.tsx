import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { referralsService } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Users, Gift, Clock, AlertTriangle } from 'lucide-react'

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  available: 'bg-green-100 text-green-800',
  spent: 'bg-blue-100 text-blue-800',
  revoked: 'bg-red-100 text-red-800',
}

export default function ReferralsPage() {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [page, setPage] = useState(0)
  const limit = 30

  const { data: stats } = useQuery({
    queryKey: ['referrals-stats'],
    queryFn: () => referralsService.stats(),
  })

  const { data: bonusesData } = useQuery({
    queryKey: ['referrals-bonuses', statusFilter, page],
    queryFn: () =>
      referralsService.bonuses({
        status: statusFilter === 'all' ? undefined : statusFilter,
        limit,
        offset: page * limit,
      }),
  })

  const freezeMutation = useMutation({
    mutationFn: (bonusId: string) => referralsService.freezeBonus(bonusId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['referrals-bonuses'] })
      queryClient.invalidateQueries({ queryKey: ['referrals-stats'] })
    },
  })

  const bonuses = bonusesData?.items || []
  const total = bonusesData?.total || 0

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Реферальная программа</h1>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Атрибутировано</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.total_attributed ?? '—'}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Бонусы</CardTitle>
            <Gift className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.total_bonuses ?? '—'}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">В ожидании</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.by_status?.pending ?? '—'}</div>
            <p className="text-xs text-muted-foreground">
              {stats?.credits?.pending ?? 0} HD credits
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Потрачено</CardTitle>
            <AlertTriangle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.by_status?.spent ?? '—'}</div>
            <p className="text-xs text-muted-foreground">
              {stats?.credits?.spent ?? 0} HD credits
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Бонусы</CardTitle>
            <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setPage(0) }}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="Фильтр" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
                <SelectItem value="available">Available</SelectItem>
                <SelectItem value="spent">Spent</SelectItem>
                <SelectItem value="revoked">Revoked</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Реферер</TableHead>
                <TableHead>Реферал</TableHead>
                <TableHead>Stars</TableHead>
                <TableHead>HD Credits</TableHead>
                <TableHead>Статус</TableHead>
                <TableHead>Создано</TableHead>
                <TableHead>Действия</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {bonuses.map((b: any) => (
                <TableRow key={b.id}>
                  <TableCell className="font-mono text-xs">
                    {b.referrer_name || b.referrer_user_id?.slice(0, 8)}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {b.referral_name || b.referral_user_id?.slice(0, 8)}
                  </TableCell>
                  <TableCell>{b.pack_stars}</TableCell>
                  <TableCell>{b.hd_credits_amount}</TableCell>
                  <TableCell>
                    <Badge className={STATUS_COLORS[b.status] || ''}>
                      {b.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs">
                    {b.created_at ? new Date(b.created_at).toLocaleString() : '—'}
                  </TableCell>
                  <TableCell>
                    {(b.status === 'pending' || b.status === 'available') && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => freezeMutation.mutate(b.id)}
                        disabled={freezeMutation.isPending}
                      >
                        Заморозить
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {bonuses.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-muted-foreground">
                    Нет бонусов
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>

          {total > limit && (
            <div className="flex justify-center gap-2 mt-4">
              <Button
                size="sm"
                variant="outline"
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
              >
                Назад
              </Button>
              <span className="text-sm self-center">
                {page + 1} / {Math.ceil(total / limit)}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={(page + 1) * limit >= total}
                onClick={() => setPage((p) => p + 1)}
              >
                Далее
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
