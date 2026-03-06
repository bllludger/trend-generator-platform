import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { photoMergeService, PhotoMergeSettings } from '../services/api'

const STATUS_LABELS: Record<string, string> = {
  pending: 'В очереди',
  processing: 'Обработка',
  succeeded: 'Успешно',
  failed: 'Ошибка',
}

const STATUS_COLORS: Record<string, string> = {
  pending: '#94a3b8',
  processing: '#f59e0b',
  succeeded: '#22c55e',
  failed: '#ef4444',
}

function bytesToMb(b: number | null): string {
  if (!b) return '—'
  return (b / 1024 / 1024).toFixed(2) + ' МБ'
}

function msToSec(ms: number | null): string {
  if (!ms) return '—'
  return (ms / 1000).toFixed(1) + 'с'
}

export default function PhotoMergePage() {
  const [activeTab, setActiveTab] = useState<'jobs' | 'analytics' | 'settings'>('jobs')
  const [windowDays, setWindowDays] = useState(30)
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(0)
  const pageSize = 50
  const qClient = useQueryClient()

  const { data: jobs, isLoading: jobsLoading } = useQuery({
    queryKey: ['photo-merge-jobs', statusFilter, page],
    queryFn: () => photoMergeService.listJobs({ limit: pageSize, offset: page * pageSize, status: statusFilter || undefined }),
    enabled: activeTab === 'jobs',
    refetchInterval: 15_000,
  })

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['photo-merge-stats', windowDays],
    queryFn: () => photoMergeService.getStats(windowDays),
    enabled: activeTab === 'analytics',
  })

  const { data: settings, isLoading: settingsLoading } = useQuery({
    queryKey: ['photo-merge-settings'],
    queryFn: () => photoMergeService.getSettings(),
    enabled: activeTab === 'settings',
  })

  const [editedSettings, setEditedSettings] = useState<Partial<PhotoMergeSettings>>({})

  const saveMutation = useMutation({
    mutationFn: (payload: Partial<PhotoMergeSettings>) => photoMergeService.updateSettings(payload),
    onSuccess: () => {
      qClient.invalidateQueries({ queryKey: ['photo-merge-settings'] })
      setEditedSettings({})
      alert('Настройки сохранены')
    },
  })

  const tabs = [
    { key: 'jobs' as const, label: 'Журнал' },
    { key: 'analytics' as const, label: 'Аналитика' },
    { key: 'settings' as const, label: 'Настройки' },
  ]

  const current = settings ? { ...settings, ...editedSettings } : null

  return (
    <div style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
      <h1 style={{ fontSize: '24px', fontWeight: 700, marginBottom: '8px' }}>🧩 Соединить фото</h1>
      <p style={{ color: '#6b7280', marginBottom: '24px' }}>Журнал операций склейки, аналитика и настройки сервиса.</p>

      <div style={{ display: 'flex', gap: '4px', marginBottom: '24px', borderBottom: '1px solid #e5e7eb' }}>
        {tabs.map((tab) => (
          <button key={tab.key} onClick={() => setActiveTab(tab.key)} style={{
            padding: '8px 20px', border: 'none',
            borderBottom: activeTab === tab.key ? '2px solid #6366f1' : '2px solid transparent',
            background: 'none', cursor: 'pointer',
            fontWeight: activeTab === tab.key ? 600 : 400,
            color: activeTab === tab.key ? '#6366f1' : '#374151',
          }}>{tab.label}</button>
        ))}
      </div>

      {activeTab === 'jobs' && (
        <div>
          <div style={{ display: 'flex', gap: '12px', marginBottom: '16px', alignItems: 'center' }}>
            <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(0) }}
              style={{ padding: '6px 12px', border: '1px solid #d1d5db', borderRadius: '6px' }}>
              <option value="">Все статусы</option>
              {Object.entries(STATUS_LABELS).map(([v, l]) => (<option key={v} value={v}>{l}</option>))}
            </select>
            <span style={{ color: '#6b7280', fontSize: '14px' }}>Обновление каждые 15 сек</span>
          </div>
          {jobsLoading ? <p>Загрузка...</p> : (
            <>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                  <thead>
                    <tr style={{ background: '#f9fafb' }}>
                      {['Пользователь', 'Статус', 'Фото', 'Формат', 'Вход', 'Выход', 'Время', 'Ошибка', 'Создан'].map((h) => (
                        <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontWeight: 600, borderBottom: '1px solid #e5e7eb', whiteSpace: 'nowrap' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {jobs?.items.map((job) => (
                      <tr key={job.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
                        <td style={{ padding: '10px 12px' }}>{job.user_display_name}</td>
                        <td style={{ padding: '10px 12px' }}>
                          <span style={{ padding: '2px 8px', borderRadius: '12px', fontSize: '12px', fontWeight: 500,
                            background: STATUS_COLORS[job.status] + '22', color: STATUS_COLORS[job.status] }}>
                            {STATUS_LABELS[job.status] || job.status}
                          </span>
                        </td>
                        <td style={{ padding: '10px 12px', textAlign: 'center' }}>{job.input_count}</td>
                        <td style={{ padding: '10px 12px' }}>{job.output_format.toUpperCase()}</td>
                        <td style={{ padding: '10px 12px' }}>{bytesToMb(job.input_bytes)}</td>
                        <td style={{ padding: '10px 12px' }}>{bytesToMb(job.output_bytes)}</td>
                        <td style={{ padding: '10px 12px' }}>{msToSec(job.duration_ms)}</td>
                        <td style={{ padding: '10px 12px', color: '#ef4444' }}>{job.error_code || '—'}</td>
                        <td style={{ padding: '10px 12px', color: '#6b7280', whiteSpace: 'nowrap' }}>
                          {new Date(job.created_at).toLocaleString('ru')}
                        </td>
                      </tr>
                    ))}
                    {!jobs?.items.length && (
                      <tr><td colSpan={9} style={{ padding: '24px', textAlign: 'center', color: '#6b7280' }}>Нет данных</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div style={{ display: 'flex', gap: '8px', marginTop: '16px', alignItems: 'center' }}>
                <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}
                  style={{ padding: '6px 12px', border: '1px solid #d1d5db', borderRadius: '6px', cursor: page === 0 ? 'not-allowed' : 'pointer' }}>
                  Назад
                </button>
                <span style={{ fontSize: '14px', color: '#374151' }}>Стр. {page + 1} · Всего {jobs?.total ?? 0}</span>
                <button onClick={() => setPage((p) => p + 1)} disabled={!jobs || (page + 1) * pageSize >= jobs.total}
                  style={{ padding: '6px 12px', border: '1px solid #d1d5db', borderRadius: '6px', cursor: 'pointer' }}>
                  Далее
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {activeTab === 'analytics' && (
        <div>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '24px' }}>
            <label style={{ fontWeight: 500 }}>Период:</label>
            {[7, 14, 30, 90].map((d) => (
              <button key={d} onClick={() => setWindowDays(d)} style={{
                padding: '6px 14px', border: '1px solid', borderColor: windowDays === d ? '#6366f1' : '#d1d5db',
                borderRadius: '6px', background: windowDays === d ? '#6366f1' : '#fff',
                color: windowDays === d ? '#fff' : '#374151', cursor: 'pointer',
              }}>{d} дн.</button>
            ))}
          </div>
          {statsLoading ? <p>Загрузка...</p> : stats ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '16px', marginBottom: '32px' }}>
                {[
                  { label: 'Всего', value: stats.total, color: '#6366f1' },
                  { label: 'Успешно', value: stats.succeeded, color: '#22c55e' },
                  { label: 'Ошибок', value: stats.failed, color: '#ef4444' },
                  { label: 'Успех %', value: stats.success_rate + '%', color: '#6366f1' },
                  { label: 'Ср. время', value: msToSec(stats.avg_duration_ms), color: '#f59e0b' },
                  { label: 'p50', value: msToSec(stats.p50_duration_ms), color: '#94a3b8' },
                  { label: 'p95', value: msToSec(stats.p95_duration_ms), color: '#94a3b8' },
                  { label: 'Вход МБ', value: bytesToMb(stats.total_input_bytes), color: '#64748b' },
                  { label: 'Выход МБ', value: bytesToMb(stats.total_output_bytes), color: '#64748b' },
                ].map(({ label, value, color }) => (
                  <div key={label} style={{ background: '#f9fafb', borderRadius: '12px', padding: '16px', textAlign: 'center' }}>
                    <div style={{ fontSize: '22px', fontWeight: 700, color }}>{value}</div>
                    <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>{label}</div>
                  </div>
                ))}
              </div>
              <div style={{ background: '#fff', borderRadius: '12px', padding: '20px', border: '1px solid #e5e7eb', marginBottom: '24px' }}>
                <h3 style={{ fontWeight: 600, marginBottom: '16px' }}>Динамика за {windowDays} дн.</h3>
                <ResponsiveContainer width="100%" height={240}>
                  <AreaChart data={stats.by_day}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis allowDecimals={false} />
                    <Tooltip />
                    <Legend />
                    <Area type="monotone" dataKey="succeeded" name="Успешно" stroke="#22c55e" fill="#22c55e33" stackId="1" />
                    <Area type="monotone" dataKey="failed" name="Ошибок" stroke="#ef4444" fill="#ef444433" stackId="1" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              {stats.top_users.length > 0 && (
                <div style={{ background: '#fff', borderRadius: '12px', padding: '20px', border: '1px solid #e5e7eb' }}>
                  <h3 style={{ fontWeight: 600, marginBottom: '16px' }}>Топ пользователей</h3>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                    <thead>
                      <tr style={{ background: '#f9fafb' }}>
                        <th style={{ padding: '8px 12px', textAlign: 'left' }}>Пользователь</th>
                        <th style={{ padding: '8px 12px', textAlign: 'right' }}>Кол-во</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.top_users.map((u, i) => (
                        <tr key={u.user_id} style={{ borderBottom: '1px solid #f3f4f6' }}>
                          <td style={{ padding: '8px 12px' }}>#{i + 1} {u.display_name}</td>
                          <td style={{ padding: '8px 12px', textAlign: 'right', fontWeight: 600 }}>{u.count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : <p style={{ color: '#6b7280' }}>Нет данных за период.</p>}
        </div>
      )}

      {activeTab === 'settings' && (
        <div>
          {settingsLoading ? <p>Загрузка...</p> : current ? (
            <div style={{ maxWidth: '480px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  <label style={{ fontWeight: 500, width: '220px' }}>Сервис включён</label>
                  <input type="checkbox" checked={current.enabled}
                    onChange={(e) => setEditedSettings((p) => ({ ...p, enabled: e.target.checked }))}
                    style={{ width: '18px', height: '18px', cursor: 'pointer' }} />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  <label style={{ fontWeight: 500, width: '220px' }}>Формат вывода</label>
                  <select value={current.output_format}
                    onChange={(e) => setEditedSettings((p) => ({ ...p, output_format: e.target.value as 'png' | 'jpeg' }))}
                    style={{ padding: '6px 10px', border: '1px solid #d1d5db', borderRadius: '6px' }}>
                    <option value="png">PNG (без потерь)</option>
                    <option value="jpeg">JPEG (сжатие)</option>
                  </select>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  <label style={{ fontWeight: 500, width: '220px' }}>Качество JPEG (1–95)</label>
                  <input type="number" min={1} max={95} value={current.jpeg_quality}
                    onChange={(e) => setEditedSettings((p) => ({ ...p, jpeg_quality: Number(e.target.value) }))}
                    style={{ padding: '6px 10px', border: '1px solid #d1d5db', borderRadius: '6px', width: '80px' }} />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  <label style={{ fontWeight: 500, width: '220px' }}>Макс. сторона результата (px, 0 = без ограничения)</label>
                  <input type="number" min={0} value={current.max_output_side_px}
                    onChange={(e) => setEditedSettings((p) => ({ ...p, max_output_side_px: Number(e.target.value) }))}
                    style={{ padding: '6px 10px', border: '1px solid #d1d5db', borderRadius: '6px', width: '100px' }} />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  <label style={{ fontWeight: 500, width: '220px' }}>Макс. размер входного файла (МБ)</label>
                  <input type="number" min={1} max={100} value={current.max_input_file_mb}
                    onChange={(e) => setEditedSettings((p) => ({ ...p, max_input_file_mb: Number(e.target.value) }))}
                    style={{ padding: '6px 10px', border: '1px solid #d1d5db', borderRadius: '6px', width: '80px' }} />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  <label style={{ fontWeight: 500, width: '220px' }}>Цвет фона</label>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <input type="color" value={current.background_color}
                      onChange={(e) => setEditedSettings((p) => ({ ...p, background_color: e.target.value }))}
                      style={{ width: '40px', height: '36px', border: '1px solid #d1d5db', borderRadius: '6px', cursor: 'pointer' }} />
                    <span style={{ fontSize: '13px', color: '#6b7280' }}>{current.background_color}</span>
                  </div>
                </div>
                <button onClick={() => saveMutation.mutate(editedSettings)}
                  disabled={saveMutation.isPending || Object.keys(editedSettings).length === 0}
                  style={{
                    marginTop: '8px', padding: '10px 20px', background: '#6366f1', color: '#fff',
                    border: 'none', borderRadius: '8px', fontWeight: 600,
                    cursor: Object.keys(editedSettings).length === 0 ? 'not-allowed' : 'pointer',
                    opacity: Object.keys(editedSettings).length === 0 ? 0.5 : 1,
                  }}>
                  {saveMutation.isPending ? 'Сохранение…' : 'Сохранить настройки'}
                </button>
                {settings?.updated_at && (
                  <p style={{ fontSize: '12px', color: '#9ca3af' }}>
                    Обновлено: {new Date(settings.updated_at).toLocaleString('ru')}
                  </p>
                )}
              </div>
            </div>
          ) : <p style={{ color: '#6b7280' }}>Не удалось загрузить настройки.</p>}
        </div>
      )}
    </div>
  )
}
