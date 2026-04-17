/**
 * Admin API services and types.
 * Uses axios instance from @/lib/api (baseURL, auth, interceptors).
 */
import api from '@/lib/api'
import type { ProductMetricsV2, Theme, Trend } from '@/types'

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
  hardDeleteUser: (userId: string) =>
    api.post<{ ok: boolean; deleted?: Record<string, number> }>(`/admin/security/users/${userId}/hard-delete`).then((r) => r.data),
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
  default_temperature_a?: number | null
  default_temperature_b?: number | null
  default_temperature_c?: number | null
  default_image_size_tier?: string
  default_aspect_ratio?: string
  default_top_p?: number | null
  default_top_p_a?: number | null
  default_top_p_b?: number | null
  default_top_p_c?: number | null
  default_seed?: number | null
  default_candidate_count?: number
  default_media_resolution?: 'LOW' | 'MEDIUM' | 'HIGH' | null
  default_thinking_config?: {
    thinking_level?: 'MINIMAL' | 'LOW' | 'MEDIUM' | 'HIGH'
    thinking_budget?: number
    include_thoughts?: boolean
  } | null
  updated_at?: string | null
}

/** Ответ GET /admin/settings/master-prompt: два профиля + вотермарк и превью (редактируемые в админке). */
export interface MasterPromptSettingsResponse {
  preview: MasterPromptSettings
  release: MasterPromptSettings
  use_nano_banana_pro?: boolean
  /** Текст из БД; пусто = использовать .env WATERMARK_TEXT */
  watermark_text?: string | null
  /** Эффективный текст для отображения (БД или .env) */
  watermark_text_effective?: string
  watermark_opacity?: number
  watermark_tile_spacing?: number
  /** Макс. сторона превью для 3 вариантов Take (даунскейл перед вотермарком); больше = выше качество превью */
  take_preview_max_dim?: number
}

/** Payload для PUT: либо по профилям, либо плоский; вотермарк и превью — отдельные ключи. */
export type MasterPromptUpdatePayload =
  | {
      preview?: Partial<MasterPromptSettings>
      release?: Partial<MasterPromptSettings>
      use_nano_banana_pro?: boolean
      watermark_text?: string | null
      watermark_opacity?: number
      watermark_tile_spacing?: number
      take_preview_max_dim?: number
    }
  | Partial<MasterPromptSettings>

export interface MasterPromptPayloadPreviewResponse {
  profile: 'preview' | 'release'
  sent_request: Record<string, unknown>
  diagnostics: Array<{
    field: string
    status: 'info' | 'omitted' | 'normalized' | 'forced'
    reason: string
    requested?: unknown
    applied?: unknown
  }>
  effective_settings: {
    preview: MasterPromptSettings
    release: MasterPromptSettings
  }
}

export const masterPromptService = {
  getSettings: () =>
    api.get<MasterPromptSettingsResponse>('/admin/settings/master-prompt').then((r) => r.data),
  updateSettings: (payload: MasterPromptUpdatePayload) =>
    api.put<MasterPromptSettingsResponse>('/admin/settings/master-prompt', payload).then((r) => r.data),
  previewPayload: (payload: {
    profile: 'preview' | 'release'
    preview?: Partial<MasterPromptSettings>
    release?: Partial<MasterPromptSettings>
    prompt_text?: string
    input_files?: Array<{ mime_type?: string; mimeType?: string; size_bytes?: number; sizeBytes?: number }>
  }, signal?: AbortSignal) =>
    api.post<MasterPromptPayloadPreviewResponse>('/admin/settings/master-prompt/payload-preview', payload, signal ? { signal } : undefined).then((r) => r.data),
}

// ─── Preview policy (единый раздел превью и вотермарка) ─────────────────────
export interface PreviewPolicySettings {
  preview_format?: 'webp' | 'jpeg'
  preview_quality?: number
  take_preview_max_dim?: number
  job_preview_max_dim?: number
  watermark_text?: string | null
  watermark_text_effective?: string
  watermark_opacity?: number
  watermark_tile_spacing?: number
  watermark_use_contrast?: boolean
  updated_at?: string | null
}

export const previewPolicyService = {
  getSettings: () =>
    api.get<PreviewPolicySettings>('/admin/settings/preview-policy').then((r) => r.data),
  updateSettings: (payload: Partial<PreviewPolicySettings>) =>
    api.put<PreviewPolicySettings>('/admin/settings/preview-policy', payload).then((r) => r.data),
}

// ─── Face ID ───────────────────────────────────────────────────────────────
export interface FaceIdSettings {
  enabled: boolean
  min_detection_confidence: number
  model_selection: 0 | 1
  crop_pad_left: number
  crop_pad_right: number
  crop_pad_top: number
  crop_pad_bottom: number
  max_faces_allowed: number
  no_face_policy: 'fallback_original'
  multi_face_policy: 'fail_generation' | 'fallback_original'
  callback_timeout_seconds: number
  callback_max_retries: number
  callback_backoff_seconds: number
  updated_at?: string | null
}

export interface FaceIdAsset {
  id: string
  user_id: string
  session_id?: string | null
  chat_id?: string | null
  flow: string
  status: 'pending' | 'ready' | 'ready_fallback' | 'failed_multi_face' | 'failed_error'
  faces_detected?: number | null
  reason_code?: string | null
  source_path: string
  processed_path?: string | null
  selected_path?: string | null
  request_id?: string | null
  last_event_id?: string | null
  latency_ms?: number | null
  primary_face_bbox?: Record<string, unknown> | null
  crop_bbox?: Record<string, unknown> | null
  detector_meta?: Record<string, unknown> | null
  created_at?: string | null
  updated_at?: string | null
}

export const faceIdService = {
  getSettings: () =>
    api.get<FaceIdSettings>('/admin/settings/face-id').then((r) => r.data),
  updateSettings: (payload: Partial<FaceIdSettings>) =>
    api.put<FaceIdSettings>('/admin/settings/face-id', payload).then((r) => r.data),
  listAssets: (params?: { limit?: number; status?: string }) =>
    api.get<{ items: FaceIdAsset[]; limit: number; pending_takes: number }>('/admin/face-id/assets', { params }).then((r) => r.data),
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
export interface UserActiveSession {
  pack_id: string
  pack_name: string
  takes_limit: number
  takes_used: number
  takes_remaining: number
  hd_limit: number
  hd_used: number
  hd_remaining: number
}

export interface UserListItem {
  id: string
  telegram_id: string
  telegram_username: string | null
  telegram_first_name: string | null
  telegram_last_name: string | null
  token_balance: number
  subscription_active: boolean
  free_generations_used: number
  free_generations_limit: number
  copy_generations_used: number
  copy_generations_limit: number
  created_at: string | null
  jobs_count: number
  succeeded: number
  failed: number
  last_active: string | null
  trial_purchased?: boolean
  free_takes_used?: number
  trial_v2_eligible?: boolean
  payments_count?: number
  active_session?: UserActiveSession | null
}

export interface UserDetailSession {
  id: string
  pack_id: string
  pack_name: string
  status: string
  takes_limit: number | null
  takes_used: number | null
  hd_limit: number | null
  hd_used: number | null
  created_at: string | null
  takes_remaining?: number
  hd_remaining?: number
}

export interface UserDetailPayment {
  id: string
  pack_id: string
  status: string
  stars_amount: number
  amount_kopecks: number | null
  tokens_granted: number
  session_id: string | null
  created_at: string | null
}

export interface UserDetail {
  id: string
  telegram_id: string
  telegram_username: string | null
  telegram_first_name: string | null
  telegram_last_name: string | null
  token_balance: number
  subscription_active: boolean
  free_generations_used: number
  free_generations_limit: number
  copy_generations_used: number
  copy_generations_limit: number
  trial_purchased: boolean
  free_takes_used?: number
  hd_paid_balance: number
  hd_promo_balance: number
  admin_notes: string | null
  is_banned: boolean
  is_suspended: boolean
  suspended_until: string | null
  rate_limit_per_hour: number | null
  is_moderator: boolean
  trial_v2_eligible?: boolean
  trial_first_preview_completed?: boolean
  trial_first_preview_completed_at?: string | null
  trial_v2?: {
    trend_slots_used: number
    trend_slots_total: number
    rerolls_used: number
    rerolls_total: number
    takes_used: number
    takes_total: number
    reward_earned_total: number
    reward_claimed_total: number
    reward_available: number
    reward_reserved: number
  }
  created_at: string | null
  updated_at: string | null
  last_active?: string | null
  active_session: (UserDetailSession & { takes_remaining: number; hd_remaining: number }) | null
  sessions: UserDetailSession[]
  payments: UserDetailPayment[]
}

export interface UsersGrowthAllTimeResponse {
  total_users: number
  start_date: string | null
  end_date: string
  generated_at: string
  series: Array<{
    date: string
    new_users: number
    total_users: number
  }>
}

export interface UsersAudienceSelectionStatsResponse {
  window_days: number | null
  total_clicks: number
  generated_at: string
  items: Array<{
    key: 'women' | 'men' | 'couples' | 'unknown'
    label: string
    clicks: number
    unique_users: number
    pct: number
  }>
}

export const usersService = {
  list: (params: { page?: number; page_size?: number; search?: string; [key: string]: unknown }) =>
    api.get<{ items: UserListItem[]; total: number; page: number; pages: number }>('/admin/users', { params }).then((r) => r.data),
  getAnalytics: (timeWindow?: string) =>
    api.get('/admin/users/analytics', { params: { time_window: timeWindow } }).then((r) => r.data),
  getGrowthAllTime: () =>
    api.get<UsersGrowthAllTimeResponse>('/admin/users/growth-all-time').then((r) => r.data),
  getAudienceSelectionStats: (windowDays?: number) =>
    api
      .get<UsersAudienceSelectionStatsResponse>('/admin/users/audience-selection-stats', {
        params: { window_days: windowDays },
      })
      .then((r) => r.data),
  getDetail: (userId: string) =>
    api.get<UserDetail>(`/admin/users/${encodeURIComponent(userId)}`).then((r) => r.data),
  grantPack: (
    userId: string,
    body: { pack_id: string; activation_message?: string | null },
    idempotencyKey?: string
  ) =>
    api
      .post<{ ok: boolean; message: string; session_id: string | null; payment_id: string | null }>(
        `/admin/users/${encodeURIComponent(userId)}/grant-pack`,
        body,
        idempotencyKey ? { headers: { 'Idempotency-Key': idempotencyKey } } : undefined
      )
      .then((r) => r.data),
  resetLimits: (userId: string) =>
    api
      .post<{ ok: boolean; updated?: boolean }>(`/admin/users/${encodeURIComponent(userId)}/reset-limits`)
      .then((r) => r.data),
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
export interface TelemetryErrorsByDay {
  date: string
  jobs_failed: number
  takes_failed: number
  total: number
}
export interface TelemetryErrorsResponse {
  window_days: number
  jobs_failed_by_error: Record<string, number>
  takes_failed_by_error: Record<string, number>
  combined: Record<string, number>
  errors_by_day?: TelemetryErrorsByDay[]
}

export interface TelemetryQualityMap {
  [key: string]: number | string | boolean | Record<string, number> | undefined
}

export interface TelemetryHealthResponse {
  window_days: number
  all_time?: boolean
  status: 'ok' | 'degraded'
  data_quality: TelemetryQualityMap
  metrics?: TelemetryQualityMap
  quality_warnings?: string[]
}

export interface TelemetryProductFunnelResponse {
  window_days: number
  all_time?: boolean
  funnel_counts: Record<string, number>
  shadow_funnel_counts?: Record<string, number>
  diff_funnel_counts?: Record<string, number>
  data_quality?: TelemetryQualityMap
  quality_warnings?: string[]
}

export interface TelemetryProductFunnelDiffResponse {
  window_days: number
  all_time?: boolean
  legacy_funnel_counts: Record<string, number>
  shadow_funnel_counts: Record<string, number>
  diff_funnel_counts: Record<string, number>
  data_quality?: TelemetryQualityMap
  quality_warnings?: string[]
}

export interface TelemetryProductFunnelHistoryResponse {
  window_days: number
  all_time?: boolean
  history: Array<{ date: string } & Record<string, number>>
  data_quality?: TelemetryQualityMap
  quality_warnings?: string[]
}

export interface TelemetryButtonClicksResponse {
  window_days: number
  all_time?: boolean
  by_button_id: Record<string, number>
  by_button_id_users?: Record<string, number>
  unknown_by_button_id?: Record<string, number>
  data_quality?: TelemetryQualityMap
  quality_warnings?: string[]
}

export interface TelemetryRevenueResponse {
  window_days: number
  all_time?: boolean
  total_stars: number
  revenue_rub_approx: number
  by_pack: Record<string, number>
  by_source: Record<string, number>
  data_quality?: TelemetryQualityMap
  quality_warnings?: string[]
}

export interface OverviewV3Kpi {
  value: number | null
  numerator: number | null
  denominator: number | null
  delta_vs_prev_pct: number | null
  trust_label: 'Trusted' | 'Partial' | 'Directional' | 'Broken'
  reason?: string | null
}

export interface TelemetryOverviewV3Response {
  window: '24h' | '7d' | '30d' | '90d' | 'all'
  window_days: number
  source?: string | null
  campaign?: string | null
  entry_type?: string | null
  flow_mode: 'canonical_only' | 'all_flows'
  trust_mode: 'trusted_only' | 'all_data'
  last_updated_at: string
  trust: {
    status: 'Good' | 'Caution' | 'Degraded' | 'Broken'
    session_coverage_pct: number
    payment_validity_pct: number
    canonical_coverage_pct: number
    reconciliation_pct: number
    reconciliation_session_pct?: number
    reconciliation_fallback_pct?: number
    reconciliation_matched_events?: number
    audit_pay_success_events?: number
    payments_completed_events?: number
    legacy_share_pct: number
    warnings: string[]
  }
  kpis: Record<string, OverviewV3Kpi>
  trend_flow: Array<{
    date: string
    started_users: number
    photo_uploaded: number
    preview_ready: number
    favorite_selected: number
    pay_success: number
  }>
  trend_revenue: Array<{
    date: string
    orders: number
    paid_users: number
    revenue: number
    revenue_per_started_user: number | null
  }>
  bottlenecks: {
    steps: Array<{
      key: string
      label: string
      conversion_pct: number | null
      numerator: number
      denominator: number
      delta_vs_prev_pct: number | null
      state: 'OK' | 'Watch' | 'Broken'
      reason?: string | null
    }>
    biggest_drop_step?: string | null
    biggest_negative_delta?: string | null
  }
  experience_health: {
    preview_success_rate: OverviewV3Kpi
    all_variants_failed_rate: OverviewV3Kpi
    median_time_to_first_preview_sec: OverviewV3Kpi
    p95_time_to_first_preview_sec: OverviewV3Kpi
    value_delivery_success_rate: OverviewV3Kpi
    latency_trend: Array<{
      date: string
      median_time_to_preview_sec: number | null
      p95_time_to_preview_sec: number | null
    }>
  }
  summary: {
    what_is_happening: string
    main_problem: string
    change_vs_prev: string
  }
}

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
  getErrors: (windowDays?: number) =>
    api
      .get('/admin/telemetry/errors', { params: { window_days: windowDays } })
      .then((r) => r.data as TelemetryErrorsResponse),
  getHealth: (windowDays?: number, allTime = false) =>
    api.get<TelemetryHealthResponse>('/admin/telemetry/health', {
      params: {
        ...(windowDays != null && { window_days: windowDays }),
        ...(allTime ? { all_time: true } : {}),
      },
    }).then((r) => r.data),
  getProductFunnel: (windowDays?: number, allTime = false) =>
    api.get<TelemetryProductFunnelResponse>('/admin/telemetry/product-funnel', {
      params: {
        ...(windowDays != null && { window_days: windowDays }),
        ...(allTime ? { all_time: true } : {}),
      },
    }).then((r) => r.data),
  getProductFunnelDiff: (windowDays?: number, allTime = false) =>
    api
      .get<TelemetryProductFunnelDiffResponse>('/admin/telemetry/product-funnel-diff', {
        params: {
          ...(windowDays != null && { window_days: windowDays }),
          ...(allTime ? { all_time: true } : {}),
        },
      })
      .then((r) => r.data),
  getProductFunnelHistory: (windowDays?: number, allTime = false) =>
    api
      .get<TelemetryProductFunnelHistoryResponse>(
        '/admin/telemetry/product-funnel-history',
        {
          params: {
            ...(windowDays != null && { window_days: windowDays }),
            ...(allTime ? { all_time: true } : {}),
          },
        }
      )
      .then((r) => r.data),
  getButtonClicks: (windowDays?: number, allTime = false) =>
    api.get<TelemetryButtonClicksResponse>('/admin/telemetry/button-clicks', {
      params: {
        ...(windowDays != null && { window_days: windowDays }),
        ...(allTime ? { all_time: true } : {}),
      },
    }).then((r) => r.data),
  getProductMetricsV2: (windowDays?: number, allTime = false) =>
    api.get<ProductMetricsV2>('/admin/telemetry/product-metrics-v2', {
      params: {
        ...(windowDays != null && { window_days: windowDays }),
        ...(allTime ? { all_time: true } : {}),
      },
    }).then((r) => r.data),
  getRevenue: (windowDays?: number, allTime = false) =>
    api.get<TelemetryRevenueResponse>('/admin/telemetry/revenue', {
      params: {
        ...(windowDays != null && { window_days: windowDays }),
        ...(allTime ? { all_time: true } : {}),
      },
    }).then((r) => r.data),
  getPathTransitions: (windowDays?: number, allTime = false) =>
    api
      .get<PathTransitionsResponse>('/admin/telemetry/path-transitions', {
        params: {
          ...(windowDays != null && { window_days: windowDays }),
          ...(allTime ? { all_time: true } : {}),
        },
      })
      .then((r) => r.data),
  getPathSequences: (windowDays?: number, limit?: number, allTime = false) =>
    api
      .get<PathSequencesResponse>('/admin/telemetry/path-sequences', {
        params: {
          ...(windowDays != null && { window_days: windowDays }),
          ...(limit != null && { limit }),
          ...(allTime ? { all_time: true } : {}),
        },
      })
      .then((r) => r.data),
  /** Single call for Path tab: transitions + drop_off + paths (avoids double heavy aggregation). */
  getPath: (windowDays?: number, limit?: number, allTime = false) =>
    api.get<PathTransitionsResponse & { paths: PathSequenceItem[] }>('/admin/telemetry/path', {
      params: {
        ...(windowDays != null && { window_days: windowDays }),
        ...(limit != null && { limit }),
        ...(allTime ? { all_time: true } : {}),
      },
    }).then((r) => r.data),
  getOverviewV3: (params?: {
    window?: '24h' | '7d' | '30d' | '90d' | 'all'
    source?: string
    campaign?: string
    entry_type?: string
    flow_mode?: 'canonical_only' | 'all_flows'
    trust_mode?: 'trusted_only' | 'all_data'
  }) =>
    api
      .get<TelemetryOverviewV3Response>('/admin/telemetry/overview-v3', {
        params,
        // overview-v3 can be significantly heavier than regular telemetry widgets
        timeout: 120000,
      })
      .then((r) => r.data),
}

export interface PathTransitionItem {
  from: string
  to: string | null
  sessions: number
  median_minutes: number | null
  avg_minutes: number | null
}
export interface PathTransitionsResponse {
  window_days: number
  all_time?: boolean
  transitions: PathTransitionItem[]
  drop_off: PathTransitionItem[]
  /** True if audit_logs row limit was hit; data may be partial. */
  truncated?: boolean
  shadow?: {
    transitions?: PathTransitionItem[]
    drop_off?: PathTransitionItem[]
    paths?: PathSequenceItem[]
    truncated?: boolean
  }
  data_quality?: TelemetryQualityMap
}

export interface PathSequenceItem {
  steps: string[]
  sessions: number
  median_minutes_to_pay: number | null
  median_minutes_to_last: number | null
  pct_reached_pay: number
}
export interface PathSequencesResponse {
  window_days: number
  all_time?: boolean
  paths: PathSequenceItem[]
  shadow_paths?: PathSequenceItem[]
  shadow_truncated?: boolean
  data_quality?: TelemetryQualityMap
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

export interface BankTransferPayInitiatedEntry {
  id: string
  user_id: string
  telegram_id?: string | null
  telegram_username?: string | null
  timestamp?: string | null
  pack_id?: string | null
  price_rub?: number | null
}

export const bankTransferService = {
  getSettings: () => api.get<BankTransferSettings>('/admin/bank-transfer/settings').then((r) => r.data),
  updateSettings: (payload: Partial<BankTransferSettings>) =>
    api.put<BankTransferSettings>('/admin/bank-transfer/settings', payload).then((r) => r.data),
  getPayInitiated: (params: {
    page?: number
    page_size?: number
    date_from?: string
    date_to?: string
    price_rub?: number
    telegram_user_id?: string
  }) =>
    api
      .get<{ items: BankTransferPayInitiatedEntry[]; total: number; page?: number; pages?: number }>(
        '/admin/bank-transfer/pay-initiated',
        { params }
      )
      .then((r) => r.data),
  getReceiptLogs: (params: {
    page?: number
    page_size?: number
    match_success?: boolean
    telegram_user_id?: string
    expected_rub?: number
    date_from?: string
    date_to?: string
  }) =>
    api.get<{ items: BankTransferReceiptLogEntry[]; total: number; page?: number; pages?: number }>(
      '/admin/bank-transfer/receipt-logs',
      { params }
    ).then((r) => r.data),
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
  takes_limit?: number | null
  hd_amount?: number | null
  is_trial?: boolean
  pack_type?: string
  upgrade_target_pack_ids?: string[] | null
  description?: string
  pack_subtype?: string
  playlist?: string[] | null
  favorites_cap?: number | null
  collection_label?: string | null
  upsell_pack_ids?: string[] | null
  hd_sla_minutes?: number
  [key: string]: unknown
}

export interface SessionItem {
  id: string
  user_id: string
  pack_id: string
  takes_limit: number
  takes_used: number
  status: string
  upgraded_from_session_id?: string | null
  upgrade_credit_stars: number
  created_at: string
  updated_at: string
}

export const sessionsService = {
  list: (params: { user_id?: string; status?: string; pack_id?: string; limit?: number; offset?: number }) =>
    api.get('/admin/sessions', { params }).then((r) => r.data),
}

export type PaymentHistoryPoint = {
  date: string
  revenue_rub: number
  revenue_stars: number
  transactions_count: number
  unique_buyers: number
  by_pack?: Array<{ pack_id: string; count: number; revenue_rub: number }>
}

export const paymentsService = {
  list: (params: {
    page?: number
    page_size?: number
    payment_method?: string
    date_from?: string
    date_to?: string
  }) => api.get('/admin/payments', { params }).then((r) => r.data),
  getStats: (params?: { days?: number; allTime?: boolean }) =>
    api
      .get('/admin/payments/stats', {
        params: {
          ...(params?.days != null ? { days: params.days } : {}),
          ...(params?.allTime ? { all_time: true } : {}),
        },
      })
      .then((r) => r.data),
  getHistory: (params: {
    date_from?: string
    date_to?: string
    granularity?: 'day' | 'week'
    pack_id?: string
  }) =>
    api
      .get<{ series: PaymentHistoryPoint[] }>('/admin/payments/history', { params })
      .then((r) => r.data),
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
  create: (data: Partial<Pick<Theme, 'name' | 'emoji' | 'order_index' | 'enabled' | 'target_audiences'>>) =>
    api.post<Theme>('/admin/themes', data).then((r) => r.data),
  update: (id: string, data: Partial<Pick<Theme, 'name' | 'emoji' | 'order_index' | 'enabled' | 'target_audiences'>>) =>
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
  prompt_aspect_ratio: string | null
  prompt_temperature: number | null
  prompt_seed: number | null
  prompt_image_size_tier: string | null
  prompt_top_p: number | null
  prompt_candidate_count: number | null
  prompt_media_resolution: 'LOW' | 'MEDIUM' | 'HIGH' | null
  prompt_thinking_config: {
    thinking_level?: 'MINIMAL' | 'LOW' | 'MEDIUM' | 'HIGH'
    thinking_budget?: number
    include_thoughts?: boolean
  } | null
  target_audiences: string[]
}>

export interface TrendAnalyticsItem {
  trend_id: string
  name: string
  emoji: string
  theme_id: string | null
  jobs_total: number
  jobs_succeeded: number
  jobs_failed: number
  takes_total: number
  takes_succeeded: number
  takes_failed: number
  generated_total?: number
  succeeded_total?: number
  failed_total?: number
  success_rate_pct?: number
  users_total?: number
  chosen_total?: number
  chosen_users?: number
  chosen_rate_pct?: number
}

export interface TrendAnalyticsResponse {
  window_days: number | null
  all_time?: boolean
  generated_at?: string
  summary?: {
    trends_total: number
    trends_with_activity: number
    generated_total: number
    succeeded_total: number
    failed_total: number
    success_rate_pct: number
    users_total: number
    chosen_total: number
    chosen_users: number
  }
  items: TrendAnalyticsItem[]
}

export const trendsService = {
  list: () => api.get<Trend[]>('/admin/trends').then((r) => r.data),
  getAnalytics: (windowDays?: number, allTime = false) =>
    api
      .get<TrendAnalyticsResponse>('/admin/trends/analytics', {
        params: {
          ...(windowDays != null && { window_days: windowDays }),
          ...(allTime ? { all_time: true } : {}),
        },
      })
      .then((r) => r.data),
  get: (id: string) => api.get<Trend>(`/admin/trends/${id}`).then((r) => r.data),
  update: (id: string, data: TrendUpdatePayload) =>
    api.put<Trend>(`/admin/trends/${id}`, data).then((r) => r.data),
  create: (data: TrendUpdatePayload) => api.post<Trend>('/admin/trends', data).then((r) => r.data),
  getExampleBlobUrl: async (id: string): Promise<string> => {
    const r = await api.get(`/admin/trends/${id}/example`, { responseType: 'blob' })
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
  deleteExample: (id: string) => api.delete<Trend>(`/admin/trends/${id}/example`).then((r) => r.data),
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

export interface AuditAnalytics {
  events_by_day: Array<{ date: string | null; count: number }>
  by_action: Record<string, number>
  by_actor_type: Record<string, number>
  top_actors: Array<{ actor_id: string; actor_display_name: string; count: number }>
}

export interface AuditFiltersResponse {
  actions: string[]
  entity_types: string[]
  window_days: number
}

export const auditService = {
  list: (params: {
    action?: string
    page?: number
    page_size?: number
    user_id?: string
    session_id?: string
    [key: string]: unknown
  }) =>
    api.get<{ items: unknown[]; total: number; page?: number; pages?: number }>('/admin/audit', { params }).then((r) => r.data),
  getFilters: (params?: { window_days?: number }) =>
    api.get<AuditFiltersResponse>('/admin/audit/filters', { params: params ?? { window_days: 90 } }).then((r) => r.data),
  getStats: (windowHours: number) =>
    api.get<AuditStats>('/admin/audit/stats', { params: { window_hours: windowHours } }).then((r) => r.data),
  getAnalytics: (params: {
    date_from?: string
    date_to?: string
    action?: string
    actor_type?: string
    entity_type?: string
    audience?: string
    user_id?: string
    session_id?: string
  }) =>
    api.get<AuditAnalytics>('/admin/audit/analytics', { params }).then((r) => r.data),
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

// ─── Trend poster (автопостер трендов в канал) ──────────────────────────────
export interface TrendPostItem {
  id: string
  trend_id: string
  trend_name: string | null
  trend_emoji: string | null
  channel_id: string
  caption: string | null
  telegram_message_id: number | null
  status: string
  sent_at: string | null
  created_at: string | null
  updated_at: string | null
  deeplink: string | null
}

export interface UnpublishedTrend {
  id: string
  name: string | null
  emoji: string | null
  description: string
  has_example: boolean
  deeplink: string | null
  theme_id: string | null
  theme_name: string
  theme_emoji: string
  theme_order_index: number
}

export interface PosterSettingsRes {
  poster_channel_id: string
  poster_bot_username: string
  poster_default_template: string
  poster_button_text: string
}

export const trendPosterService = {
  getPosts: (status?: string) =>
    api.get<{ items: TrendPostItem[] }>('/admin/trend-posts', { params: { status } }).then((r) => r.data),
  getUnpublished: () =>
    api.get<{ items: UnpublishedTrend[] }>('/admin/trend-posts/unpublished').then((r) => r.data),
  preview: (trendId: string, caption?: string) =>
    api
      .post<{ trend_id: string; caption: string; has_example: boolean; deeplink: string }>(
        '/admin/trend-posts/preview',
        { trend_id: trendId, caption }
      )
      .then((r) => r.data),
  publish: (trendId: string, caption: string) =>
    api
      .post<{ id: string; trend_id: string; status: string; telegram_message_id: number | null; sent_at: string | null }>(
        '/admin/trend-posts/publish',
        { trend_id: trendId, caption }
      )
      .then((r) => r.data),
  deletePost: (postId: string) =>
    api.delete<{ id: string; status: string }>(`/admin/trend-posts/${postId}`).then((r) => r.data),
  getSettings: () =>
    api.get<PosterSettingsRes>('/admin/trend-posts/settings').then((r) => r.data),
  updateSettings: (payload: { poster_default_template?: string; poster_button_text?: string; poster_channel_id?: string; poster_bot_username?: string }) =>
    api.put<PosterSettingsRes>('/admin/trend-posts/settings', payload).then((r) => r.data),
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

export interface JobsListItem {
  job_id: string
  task_type?: 'job' | 'take'
  telegram_id?: string
  user_display_name?: string
  trend_id?: string | null
  trend_name?: string
  trend_emoji?: string
  status: string
  is_preview?: boolean
  reserved_tokens: number
  error_code?: string
  input_photo_url?: string | null
  has_three_variants?: boolean | null
  variants_ready_count?: number | null
  variant_photo_urls?: Array<string | null> | null
  started_at?: string | null
  received_at?: string | null
  time_to_receive_sec?: number | null
  created_at: string
}

export interface JobsListResponse {
  items: JobsListItem[]
  total: number
  page: number
  pages: number
}

export interface JobsStats {
  total: number
  succeeded: number
  failed: number
  in_queue: number
  hours: number
}

export interface JobsAnalytics {
  jobs_by_day: Array<{ date: string | null; count: number }>
  by_status: Record<string, number>
  by_trend: Array<{ trend_id: string; trend_name: string; trend_emoji?: string; count: number }>
  top_users: Array<{ user_id: string; telegram_id?: string; user_display_name: string; count: number }>
}

export const jobsService = {
  list: (params: JobsListParams) =>
    api.get<JobsListResponse>('/admin/jobs', { params }).then((r) => r.data),
  stats: (hours: number) =>
    api.get<JobsStats>('/admin/jobs/stats', { params: { hours } }).then((r) => r.data),
  getAnalytics: (params: { hours?: number; date_from?: string; date_to?: string; trend_id?: string; status?: string }) =>
    api.get<JobsAnalytics>('/admin/jobs/analytics', { params }).then((r) => r.data),
  get: (jobId: string) => api.get(`/admin/jobs/${jobId}`).then((r) => r.data),
}

// ─── Copy style ────────────────────────────────────────────────────────────
export interface CopyStyleSettings {
  model?: string
  system_prompt?: string
  user_prompt?: string
  max_tokens?: number
  prompt_suffix?: string
  prompt_instruction_3_images?: string
  prompt_instruction_2_images?: string
  generation_system_prompt_prefix?: string
  generation_negative_prompt?: string
  generation_safety_constraints?: string
  generation_image_constraints_template?: string
  generation_default_size?: string
  generation_default_format?: string
  generation_default_model?: string
  updated_at?: string
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

// ─── Traffic sources & ad campaigns ────────────────────────────────────────
export interface TrafficSourceItem {
  id: string
  slug: string
  name: string
  url: string | null
  platform: string
  is_active: boolean
  created_at: string | null
  updated_at: string | null
}

export interface TrafficSourceStatsItem {
  source_id: string
  slug: string
  name: string
  platform: string
  clicks: number
  new_users: number
  buyers: number
  revenue_stars: number
  revenue_rub: number
  conversion_rate_pct: number
}

export interface TrafficOverview {
  total_clicks: number
  new_users: number
  buyers: number
  revenue_stars: number
  revenue_rub: number
  conversion_rate_pct: number
  daily_clicks: Array<{ date: string; clicks: number }>
  daily_purchases: Array<{ date: string; payments: number; stars: number }>
  date_from: string | null
  date_to: string | null
}

export interface TrafficFunnelStep {
  name: string
  label: string
  count: number
  pct: number
}

export interface AdCampaignItem {
  id: string
  source_id: string
  source: { id: string; slug: string; name: string }
  name: string
  slug: string | null
  budget_rub: number
  date_from: string | null
  date_to: string | null
  is_active: boolean
  created_at: string | null
  notes: string | null
}

export interface CampaignRoi {
  campaign_id: string
  source_slug: string
  name: string
  budget_rub: number
  date_from: string
  date_to: string
  new_users: number
  buyers: number
  revenue_stars: number
  revenue_rub: number
  cpa_rub: number | null
  cpp_rub: number | null
  roas: number | null
}

export const trafficService = {
  getBotInfo: () => api.get<{ username: string | null }>('/admin/bot-info').then((r) => r.data),
  listSources: (params?: { active_only?: boolean }) =>
    api.get<TrafficSourceItem[]>('/admin/traffic-sources', { params }).then((r) => r.data),
  createSource: (body: { slug: string; name: string; url?: string; platform?: string }) =>
    api.post<TrafficSourceItem>('/admin/traffic-sources', body).then((r) => r.data),
  updateSource: (id: string, body: { name?: string; url?: string; is_active?: boolean }) =>
    api.patch<TrafficSourceItem>(`/admin/traffic-sources/${id}`, body).then((r) => r.data),
  deleteSource: (id: string) => api.delete(`/admin/traffic-sources/${id}`).then((r) => r.data),
  getStats: (params?: { date_from?: string; date_to?: string }) =>
    api.get<{ sources: TrafficSourceStatsItem[]; date_from?: string; date_to?: string }>('/admin/traffic-sources/stats', { params }).then((r) => r.data),
  getOverview: (params?: { date_from?: string; date_to?: string }) =>
    api.get<TrafficOverview>('/admin/traffic-sources/overview', { params }).then((r) => r.data),
  getFunnel: (slug: string, params?: { date_from?: string; date_to?: string }) =>
    api.get<{ slug: string; steps: TrafficFunnelStep[]; date_from?: string; date_to?: string }>(`/admin/traffic-sources/${slug}/funnel`, { params }).then((r) => r.data),
  getSourceUsers: (slug: string, params?: { limit?: number; offset?: number }) =>
    api.get<{ items: Array<{ id: string; telegram_id: string; username: string | null; first_name: string | null; created_at: string | null; has_purchased: boolean }>; total: number }>(`/admin/traffic-sources/${slug}/users`, { params }).then((r) => r.data),
  listCampaigns: () => api.get<AdCampaignItem[]>('/admin/ad-campaigns').then((r) => r.data),
  createCampaign: (body: { source_id: string; name: string; budget_rub: number; date_from: string; date_to: string; notes?: string }) =>
    api.post<AdCampaignItem>('/admin/ad-campaigns', body).then((r) => r.data),
  updateCampaign: (id: string, body: { name?: string; budget_rub?: number; date_from?: string; date_to?: string; is_active?: boolean; notes?: string }) =>
    api.patch<AdCampaignItem>(`/admin/ad-campaigns/${id}`, body).then((r) => r.data),
  getCampaignRoi: (id: string) => api.get<CampaignRoi>(`/admin/ad-campaigns/${id}/roi`).then((r) => r.data),
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

// ─── Photo Merge ──────────────────────────────────────────────────────────
export interface PhotoMergeJob {
  id: string
  user_id: string
  user_display_name: string
  status: 'pending' | 'processing' | 'succeeded' | 'failed'
  input_count: number
  output_format: string
  input_bytes: number | null
  output_bytes: number | null
  duration_ms: number | null
  error_code: string | null
  created_at: string
  updated_at: string
}

export interface PhotoMergeJobsResponse {
  total: number
  items: PhotoMergeJob[]
}

export interface PhotoMergeStatsByDay {
  date: string
  total: number
  succeeded: number
  failed: number
}

export interface PhotoMergeStats {
  window_days: number
  total: number
  succeeded: number
  failed: number
  processing: number
  success_rate: number
  avg_duration_ms: number | null
  p50_duration_ms: number | null
  p95_duration_ms: number | null
  total_input_bytes: number
  total_output_bytes: number
  top_users: Array<{ user_id: string; display_name: string; count: number }>
  by_day: PhotoMergeStatsByDay[]
}

export interface PhotoMergeSettings {
  output_format: 'png' | 'jpeg'
  jpeg_quality: number
  max_output_side_px: number
  max_input_file_mb: number
  background_color: string
  enabled: boolean
  updated_at: string | null
}

export interface PhotoMergeJobsListParams {
  limit?: number
  offset?: number
  status?: string
  user_id?: string
  date_from?: string
  date_to?: string
}

export const photoMergeService = {
  listJobs: (params: PhotoMergeJobsListParams) =>
    api.get<PhotoMergeJobsResponse>('/admin/photo-merge/jobs', { params }).then((r) => r.data),
  getStats: (windowDays = 30) =>
    api.get<PhotoMergeStats>('/admin/photo-merge/stats', { params: { window_days: windowDays } }).then((r) => r.data),
  getSettings: () => api.get<PhotoMergeSettings>('/admin/photo-merge/settings').then((r) => r.data),
  updateSettings: (payload: Partial<PhotoMergeSettings>) =>
    api.put<PhotoMergeSettings>('/admin/photo-merge/settings', payload).then((r) => r.data),
}
