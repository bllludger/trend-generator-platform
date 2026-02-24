/**
 * Admin API services and types.
 * Uses axios instance from @/lib/api (baseURL, auth, interceptors).
 */
import api from '@/lib/api'
import type { Theme, Trend } from '@/types'

// ─── Auth ─────────────────────────────────────────────────────────────────
export const authService = {
  login: (username: string, password: string) =>
    api.post<{ access_token: string; user: { id: string; username: string } }>('/admin/auth/login', { username, password }).then((r) => r.data),
  logout: () => api.post('/admin/auth/logout'),
}

// ─── Security ──────────────────────────────────────────────────────────────
export interface SecuritySettings {
  free_generations_per_user?: number
  rate_limit_per_hour?: number
  subscriber_rate_limit_per_hour?: number
  abuse_suspend_hours?: number
  abuse_suspend_after_failures?: number
  vip_bypass_rate_limit?: boolean
  updated_at?: string | null
  // UI / legacy names (optional for compatibility)
  copy_generations_per_user?: number
  free_requests_per_day?: number
  new_user_first_day_limit?: number
  default_rate_limit_per_hour?: number
  max_failures_before_auto_suspend?: number
  auto_suspend_hours?: number
  cooldown_minutes_after_failures?: number
}

export interface SecurityOverview {
  banned_count: number
  suspended_count: number
  rate_limited_count: number
  moderators_count: number
  total_users: number
}

export const securityService = {
  getSettings: () => api.get<SecuritySettings>('/admin/security/settings').then((r) => r.data),
  updateSettings: (payload: Partial<SecuritySettings>) =>
    api.put<SecuritySettings>('/admin/security/settings', payload).then((r) => r.data),
  getOverview: () => api.get<SecurityOverview>('/admin/security/overview').then((r) => r.data),
  getUsers: (params: { page?: number; page_size?: number; filter_status?: string; telegram_id?: string }) =>
    api.get<{ items: unknown[]; total: number; page?: number; pages?: number }>('/admin/security/users', { params }).then((r) => r.data),
  banUser: (userId: string, reason?: string) => api.post(`/admin/security/users/${userId}/ban`, { reason }).then((r) => r.data),
  unbanUser: (userId: string) => api.post(`/admin/security/users/${userId}/unban`).then((r) => r.data),
  suspendUser: (userId: string, hours: number, reason?: string) =>
    api.post(`/admin/security/users/${userId}/suspend`, { hours, reason }).then((r) => r.data),
  resumeUser: (userId: string) => api.post(`/admin/security/users/${userId}/resume`).then((r) => r.data),
  setRateLimit: (userId: string, limit: number | null) =>
    api.post(`/admin/security/users/${userId}/rate-limit`, { limit }).then((r) => r.data),
  resetLimits: () => api.post<{ users_updated?: number }>('/admin/security/reset-limits').then((r) => r.data),
  setModerator: (userId: string, isModerator: boolean) =>
    api.post(`/admin/security/users/${userId}/moderator`, { is_moderator: isModerator }).then((r) => r.data),
}

// ─── Transfer policy (global + trends) ─────────────────────────────────────
export interface TransferPolicySettings {
  identity_lock_level?: string
  identity_rules_text?: string
  composition_rules_text?: string
  subject_reference_name?: string
  avoid_default_items?: string
  updated_at?: string | null
}

export interface TransferPolicyBoth {
  global: TransferPolicySettings
  trends: TransferPolicySettings
}

export const transferPolicyService = {
  getSettings: () =>
    api.get<TransferPolicyBoth>('/admin/settings/transfer-policy').then((r) => r.data),
  updateSettings: (payload: { global?: Partial<TransferPolicySettings>; trends?: Partial<TransferPolicySettings> }) =>
    api.put<TransferPolicyBoth>('/admin/settings/transfer-policy', payload).then((r) => r.data),
}

// ─── Master prompt (Generation Prompt Settings: INPUT, TASK, IDENTITY, SAFETY + defaults) ─
export interface MasterPromptSettings {
  prompt_input?: string
  prompt_input_enabled?: boolean
  prompt_task?: string
  prompt_task_enabled?: boolean
  prompt_identity_transfer?: string
  prompt_identity_transfer_enabled?: boolean
  safety_constraints?: string
  safety_constraints_enabled?: boolean
  default_model?: string
  default_size?: string
  default_format?: string
  default_temperature?: number
  default_image_size_tier?: string
  default_aspect_ratio?: string
  updated_at?: string | null
}

export const masterPromptService = {
  getSettings: () =>
    api.get<MasterPromptSettings>('/admin/settings/master-prompt').then((r) => r.data),
  updateSettings: (payload: Partial<MasterPromptSettings>) =>
    api.put<MasterPromptSettings>('/admin/settings/master-prompt', payload).then((r) => r.data),
}

// ─── Env / App settings ─────────────────────────────────────────────────────
export interface EnvItem {
  key: string
  value: string
  category: string
  description?: string
  raw_type?: string
}

export interface AppSettings {
  use_nano_banana_pro?: boolean
  updated_at?: string | null
}

export const envSettingsService = {
  getEnv: () =>
    api.get<{ items: EnvItem[]; source?: string }>('/admin/settings/env').then((r) => r.data),
}

export const appSettingsService = {
  getSettings: () => api.get<AppSettings>('/admin/settings/app').then((r) => r.data),
  updateSettings: (payload: Partial<AppSettings>) =>
    api.put<AppSettings>('/admin/settings/app', payload).then((r) => r.data),
}

// ─── Users ────────────────────────────────────────────────────────────────
export const usersService = {
  list: (params: { page?: number; page_size?: number; search?: string; [key: string]: unknown }) =>
    api.get('/admin/users', { params }).then((r) => r.data),
  getAnalytics: (timeWindow?: string) =>
    api.get('/admin/users/analytics', { params: { time_window: timeWindow } }).then((r) => r.data),
}

// ─── Telegram messages ─────────────────────────────────────────────────────
export interface TelegramMessageTemplate {
  key: string
  category: string
  description?: string
  value: string
}

export const telegramMessagesService = {
  list: () =>
    api.get<{ items: TelegramMessageTemplate[] }>('/admin/telegram-messages').then((r) => r.data),
  bulkUpdate: (items: { key: string; value: string }[]) =>
    api.post<{ updated: number }>('/admin/telegram-messages/bulk', { items }).then((r) => r.data),
  resetDefaults: () =>
    api.post<{ reset: number }>('/admin/telegram-messages/reset').then((r) => r.data),
}

// ─── Telemetry ─────────────────────────────────────────────────────────────
export const telemetryService = {
  getDashboard: (windowHours?: number) =>
    api.get('/admin/telemetry', { params: { window_hours: windowHours } }).then((r) => r.data),
  getTrendAnalytics: (windowHours?: number) =>
    api.get('/admin/telemetry/trends', { params: { window_hours: windowHours } }).then((r) => r.data),
  get: (windowHours?: number) =>
    api.get('/admin/telemetry', { params: { window_hours: windowHours } }).then((r) => r.data),
  getHistory: (windowDays?: number) =>
    api.get('/admin/telemetry/history', { params: { window_days: windowDays } }).then((r) => r.data),
  getProductMetrics: (windowDays?: number) =>
    api.get('/admin/telemetry/product-metrics', { params: { window_days: windowDays } }).then((r) => r.data),
}

// ─── Bank transfer ─────────────────────────────────────────────────────────
export interface PackForButton {
  id: string
  name: string
  emoji: string
  tokens: number
  stars_price: number
  [key: string]: unknown
}

export interface BankTransferSettings {
  enabled: boolean
  card_number?: string
  card_masked?: string
  comment?: string
  star_to_rub?: number
  receipt_system_prompt?: string
  receipt_user_prompt?: string
  receipt_vision_model?: string
  amount_tolerance_abs?: number
  amount_tolerance_pct?: number
  step1_description?: string
  step2_requisites?: string
  success_message?: string
  amount_mismatch_message?: string
  packs_for_buttons?: PackForButton[]
  updated_at?: string | null
}

export interface BankTransferReceiptLogEntry {
  id: string
  telegram_user_id?: string
  username?: string
  match_success?: boolean
  created_at?: string
  raw_vision_response?: string
  extracted_amount_rub?: number | null
  expected_rub?: number | null
  extracted_card_first4?: string | null
  extracted_card_last4?: string | null
  card_match_success?: boolean | null
  comment_match_success?: boolean | null
  extracted_comment?: string | null
  extracted_receipt_dt?: string | null
  rejection_reason?: string | null
  pack_id?: string | null
  payment_id?: string | null
  error_message?: string | null
  [key: string]: unknown
}

export const bankTransferService = {
  getSettings: () => api.get<BankTransferSettings>('/admin/bank-transfer/settings').then((r) => r.data),
  updateSettings: (payload: Partial<BankTransferSettings>) =>
    api.put<BankTransferSettings>('/admin/bank-transfer/settings', payload).then((r) => r.data),
  getReceiptLogs: (params: { page?: number; page_size?: number; match_success?: boolean; telegram_user_id?: string }) =>
    api.get<{ items: BankTransferReceiptLogEntry[]; total: number; page?: number; pages?: number }>('/admin/bank-transfer/receipt-logs', { params }).then((r) => r.data),
  getReceiptLogFile: (logId: string) =>
    api.get(`/admin/bank-transfer/receipt-logs/${logId}/file`, { responseType: 'blob' }).then((r) => r.data as Blob),
}

// ─── Payments / Packs ─────────────────────────────────────────────────────
export interface Pack {
  id: string
  name: string
  emoji: string
  tokens: number
  stars_price: number
  enabled: boolean
  order_index?: number
  [key: string]: unknown
}

export const paymentsService = {
  list: (params: { page?: number; page_size?: number; payment_method?: string }) =>
    api.get('/admin/payments', { params }).then((r) => r.data),
  getStats: (days: number) => api.get('/admin/payments/stats', { params: { days } }).then((r) => r.data),
  refund: (paymentId: string) => api.post(`/admin/payments/${paymentId}/refund`).then((r) => r.data),
}

export const packsService = {
  list: () => api.get<Pack[]>('/admin/packs').then((r) => r.data),
  update: (id: string, payload: Partial<Pack>) => api.put<Pack>(`/admin/packs/${id}`, payload).then((r) => r.data),
  create: (payload: Partial<Pack>) => api.post<Pack>('/admin/packs', payload).then((r) => r.data),
  delete: (id: string) => api.delete(`/admin/packs/${id}`).then((r) => r.data),
}

// ─── Themes ────────────────────────────────────────────────────────────────
export const themesService = {
  list: () => api.get<Theme[]>('/admin/themes').then((r) => r.data),
  get: (id: string) => api.get<Theme>(`/admin/themes/${id}`).then((r) => r.data),
  create: (data: Partial<Pick<Theme, 'name' | 'emoji' | 'order_index' | 'enabled'>>) =>
    api.post<Theme>('/admin/themes', data).then((r) => r.data),
  update: (id: string, data: Partial<Pick<Theme, 'name' | 'emoji' | 'order_index' | 'enabled'>>) =>
    api.put<Theme>(`/admin/themes/${id}`, data).then((r) => r.data),
  delete: (id: string) => api.delete(`/admin/themes/${id}`).then((r) => r.data),
  moveOrder: (id: string, direction: 'up' | 'down') =>
    api.patch<Theme>(`/admin/themes/${id}/order`, { direction }).then((r) => r.data),
}

// ─── Trends ───────────────────────────────────────────────────────────────
export type TrendUpdatePayload = Partial<{
  name: string
  emoji: string
  description: string
  system_prompt: string
  scene_prompt: string | null
  subject_prompt: string | null
  negative_prompt: string
  negative_scene: string | null
  subject_mode: string
  framing_hint: string
  style_preset: Record<string, unknown>
  max_images: number
  enabled: boolean
  order_index: number
  theme_id: string | null
  prompt_sections: unknown[] | null
  prompt_model: string | null
  prompt_size: string | null
  prompt_format: string | null
  prompt_temperature: number | null
}>

export const trendsService = {
  list: () => api.get<Trend[]>('/admin/trends').then((r) => r.data),
  get: (id: string) => api.get<Trend>(`/admin/trends/${id}`).then((r) => r.data),
  update: (id: string, data: TrendUpdatePayload) =>
    api.put<Trend>(`/admin/trends/${id}`, data).then((r) => r.data),
  create: (data: TrendUpdatePayload) => api.post<Trend>('/admin/trends', data).then((r) => r.data),
  getExampleBlobUrl: async (id: string): Promise<string> => {
    const r = await api.get(`/admin/trends/${id}/example`, { responseType: 'blob' })
    return URL.createObjectURL(r.data as Blob)
  },
  getStyleReferenceBlobUrl: async (id: string): Promise<string> => {
    const r = await api.get(`/admin/trends/${id}/style-reference`, { responseType: 'blob' })
    return URL.createObjectURL(r.data as Blob)
  },
  uploadExample: (id: string, file: File, onProgress?: (p: number) => void) => {
    const form = new FormData()
    form.append('file', file)
    return api
      .post<Trend>(`/admin/trends/${id}/example`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: onProgress ? (e) => onProgress(e.total ? Math.round((e.loaded / e.total) * 100) : 0) : undefined,
      })
      .then((r) => r.data)
  },
  uploadStyleReference: (id: string, file: File, onProgress?: (p: number) => void) => {
    const form = new FormData()
    form.append('file', file)
    return api
      .post<Trend>(`/admin/trends/${id}/style-reference`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: onProgress ? (e) => onProgress(e.total ? Math.round((e.loaded / e.total) * 100) : 0) : undefined,
      })
      .then((r) => r.data)
  },
  deleteExample: (id: string) => api.delete<Trend>(`/admin/trends/${id}/example`).then((r) => r.data),
  deleteStyleReference: (id: string) => api.delete<Trend>(`/admin/trends/${id}/style-reference`).then((r) => r.data),
  getPromptPreview: (id: string) =>
    api.get<{ prompt: string; model?: string; size?: string; format?: string }>(`/admin/trends/${id}/prompt-preview`).then((r) => r.data),
  moveOrder: (id: string, direction: 'up' | 'down') =>
    api.patch<Trend>(`/admin/trends/${id}/order`, { direction }).then((r) => r.data),
}

// ─── Audit ─────────────────────────────────────────────────────────────────
export interface AuditStats {
  total: number
  by_actor_type?: Record<string, number>
}

export const auditService = {
  list: (params: { action?: string; page?: number; page_size?: number; [key: string]: unknown }) =>
    api.get<{ items: unknown[]; total: number; page?: number; pages?: number }>('/admin/audit', { params }).then((r) => r.data),
  getStats: (windowHours: number) =>
    api.get<AuditStats>('/admin/audit/stats', { params: { window_hours: windowHours } }).then((r) => r.data),
}

// ─── Broadcast ─────────────────────────────────────────────────────────────
export const broadcastService = {
  getPreview: (includeBlocked?: boolean) =>
    api.get<{ recipients: number; total_users: number; excluded: number }>('/admin/broadcast/preview', {
      params: { include_blocked: includeBlocked },
    }).then((r) => r.data),
  send: (message: string, includeBlocked?: boolean) =>
    api.post('/admin/broadcast/send', { message, include_blocked: includeBlocked }).then((r) => r.data),
}

// ─── Jobs ──────────────────────────────────────────────────────────────────
export interface JobsListParams {
  page?: number
  page_size?: number
  status?: string
  telegram_id?: string
  trend_id?: string
  hours?: number
}

export interface JobsStats {
  total: number
  succeeded: number
  failed: number
  in_queue: number
  hours: number
}

export const jobsService = {
  list: (params: JobsListParams) =>
    api.get('/admin/jobs', { params }).then((r) => r.data),
  stats: (hours: number) =>
    api.get<JobsStats>('/admin/jobs/stats', { params: { hours } }).then((r) => r.data),
  get: (jobId: string) => api.get(`/admin/jobs/${jobId}`).then((r) => r.data),
}

// ─── Copy style ────────────────────────────────────────────────────────────
export interface CopyStyleSettings {
  [key: string]: unknown
}

export const copyStyleService = {
  getSettings: () => api.get<CopyStyleSettings>('/admin/settings/copy-style').then((r) => r.data),
  updateSettings: (payload: Partial<CopyStyleSettings>) =>
    api.put<CopyStyleSettings>('/admin/settings/copy-style', payload).then((r) => r.data),
}

// ─── Referrals ────────────────────────────────────────────────────────────
export const referralsService = {
  stats: () => api.get('/admin/referrals/stats').then((r) => r.data),
  bonuses: (params: { status?: string; limit?: number; offset?: number }) =>
    api.get('/admin/referrals/bonuses', { params }).then((r) => r.data),
  freezeBonus: (bonusId: string) =>
    api.post(`/admin/referrals/bonuses/${bonusId}/freeze`).then((r) => r.data),
}

// ─── Cleanup ───────────────────────────────────────────────────────────────
export const cleanupService = {
  getPreview: (olderThanHours: number) =>
    api.get<{ jobs_count: number; files_count: number; older_than_hours: number }>('/admin/cleanup/preview', {
      params: { older_than_hours: olderThanHours },
    }).then((r) => r.data),
  run: (olderThanHours: number) =>
    api.post('/admin/cleanup/run', {}, { params: { older_than_hours: olderThanHours } }).then((r) => r.data),
}
