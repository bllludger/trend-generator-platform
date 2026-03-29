export interface User {
  id: string
  telegram_id: string
  token_balance: number
  subscription_active: boolean
  free_generations_used?: number
  free_generations_limit?: number
  copy_generations_used?: number
  copy_generations_limit?: number
  created_at: string
  jobs_count?: number
  succeeded?: number
  failed?: number
  last_active?: string
}

/** Целевая аудитория: women | men | couples */
export const AUDIENCE_VALUES = ['women', 'men', 'couples'] as const
export type AudienceValue = (typeof AUDIENCE_VALUES)[number]

export interface Theme {
  id: string
  name: string
  emoji: string
  order_index: number
  enabled: boolean
  /** В каких ЦА показывать тематику (по умолчанию ['women']) */
  target_audiences?: string[]
  /** Ссылка для рассылки: t.me/bot?start=theme_{id}. null если не задан username бота */
  deeplink?: string | null
}

/** Секция промпта (Playground 1:1) */
export interface TrendPromptSection {
  id: string
  type: 'text' | 'variable'
  label: string
  content: string
  enabled: boolean
  order: number
}

export interface Trend {
  id: string
  theme_id?: string | null
  name: string
  emoji: string
  description: string
  scene_prompt: string
  /** JSON-объект или произвольная строка — в форме переключатель «Строка» / «JSON» */
  style_preset: Record<string, any> | string
  negative_scene?: string
  composition_prompt?: string | null
  subject_mode?: string // face | head_torso | full_body
  framing_hint?: string // close_up | portrait | half_body | full_body
  max_images: number
  enabled: boolean
  order_index: number
  has_example?: boolean
  /** @deprecated legacy, только если scene_prompt пуст */
  system_prompt?: string
  /** @deprecated перенос личности только через TransferPolicy */
  subject_prompt?: string
  /** @deprecated используйте negative_scene */
  negative_prompt?: string
  /** Playground 1:1 — секции промпта (когда заданы, воркер собирает промпт из них) */
  prompt_sections?: TrendPromptSection[] | null
  prompt_model?: string | null
  prompt_size?: string | null
  prompt_format?: string | null
  prompt_aspect_ratio?: string | null
  /** Источник конфига промпта: playground (секции) или scene (сценарный промпт) */
  prompt_config_source?: 'playground' | 'scene'
  prompt_temperature?: number | null
  prompt_top_p?: number | null
  prompt_candidate_count?: number | null
  prompt_media_resolution?: 'LOW' | 'MEDIUM' | 'HIGH' | null
  prompt_thinking_config?: {
    thinking_budget?: number
    thinking_level?: 'MINIMAL' | 'LOW' | 'MEDIUM' | 'HIGH'
  } | null
  /** В каких ЦА показывать тренд (по умолчанию ['women']) */
  target_audiences?: string[]
}

export interface Job {
  job_id: string
  user_id: string
  telegram_id?: string
  trend_id: string
  trend_name?: string
  status: 'CREATED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  reserved_tokens: number
  error_code?: string
  created_at: string
  updated_at: string
}

export interface AuditLog {
  id: string
  actor_type: string
  actor_id?: string
  actor_display_name?: string
  action: string
  entity_type: string
  entity_id?: string
  user_id?: string | null
  session_id?: string | null
  payload: Record<string, any>
  created_at: string
}

export interface TelemetryData {
  users_total: number
  users_subscribed: number
  jobs_total: number
  jobs_window: number
  queue_length: number
  jobs_by_status: Record<string, number>
  ledger_ops_window?: Record<string, number>
  audit_actions_window?: Record<string, number>
  audit_by_actor_window?: Record<string, number>
  jobs_failed_by_error?: Record<string, number>
  trend_analytics_window: Array<{
    trend_id: string
    name: string
    emoji: string
    jobs_window?: number
    succeeded_window?: number
    failed_window?: number
    selected_window?: number
  }>
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface AuthResponse {
  access_token: string
  token_type: string
  user: {
    username: string
  }
}

export interface ProductMetrics {
  dau: number
  wau: number
  mau: number
  stickiness_pct: number
  retention_d1_pct: number
  retention_weekly_pct: number
  retained_d1: number
  retained_weekly: number
  new_users_7d: number
  new_users_30d: number
  churned_users: number
  avg_jobs_per_active: number
  avg_session_sec: number
  avg_session_str: string
  ltv_jobs: number
  jobs_per_user_distribution: Record<string, number>
}

export interface ProductMetricsV2 {
  window_days: number
  preview_to_pay_pct?: number
  hit_rate_pct?: number
  aov_stars?: number
  total_stars?: number
  paying_users?: number
  users_started?: number
  repeat_purchase_rate_pct?: number
  avg_time_start_to_result_sec?: number | null
  avg_steps_start_to_result?: number | null
  data_quality?: Record<string, number | string | boolean>
}
