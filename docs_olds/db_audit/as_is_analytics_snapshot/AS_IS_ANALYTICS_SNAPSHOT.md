# AS IS Analytics Snapshot

Снимок собран из живых контейнеров `ai_slop_2-api-1` и `ai_slop_2-db-1`: **2026-03-15 19:18:13 UTC**.

## Артефакты

- Полная таблица метрик: `docs/data/as_is_analytics_snapshot/all_metrics_flat.csv`
- Полная таблица пользователей: `docs/data/as_is_analytics_snapshot/users_full.csv`
- Raw JSON endpoints: `docs/data/as_is_analytics_snapshot/*.json`

## 1. Raw DB Footprint

| table_name | row_count |
| --- | --- |
| audit_logs | 5227 |
| bank_transfer_receipt_log | 23 |
| favorites | 78 |
| jobs | 277 |
| pack_orders | 1 |
| payments | 34 |
| referral_bonuses | 0 |
| sessions | 240 |
| takes | 253 |
| users | 557 |

## 2. Users Analytics 30d

| metric | value |
| --- | --- |
| total_users | 557 |
| active_subscribers | 0 |
| conversion_rate | 0.0 |
| users_with_jobs | 42 |
| avg_jobs_per_user | 3.5 |

### Рост пользователей по дням

| date | new_users |
| --- | --- |
| 2026-03-02 | 1 |
| 2026-03-03 | 0 |
| 2026-03-04 | 1 |
| 2026-03-05 | 3 |
| 2026-03-06 | 0 |
| 2026-03-07 | 297 |
| 2026-03-08 | 112 |
| 2026-03-09 | 11 |
| 2026-03-10 | 9 |
| 2026-03-11 | 4 |
| 2026-03-12 | 2 |
| 2026-03-13 | 4 |
| 2026-03-14 | 3 |
| 2026-03-15 | 3 |

### Активность пользователей

| segment | users |
| --- | --- |
| Без задач | 515 |
| 1–5 задач | 39 |
| 6–20 задач | 2 |
| 21+ задач | 1 |

### Распределение баланса

| range | count |
| --- | --- |
| 0 | 553 |
| 1–100 | 4 |
| 101–500 | 0 |
| 501–1000 | 0 |
| 1001+ | 0 |

### Топ пользователей по jobs за 30 дней

| telegram_id | user_display_name | jobs_count | succeeded | failed | token_balance |
| --- | --- | --- | --- | --- | --- |
| 5277758770 | @Ksyun00 | 28 | 27 | 1 | 11 |
| 5138660668 | @Ani_Zolotareva | 18 | 18 | 0 | 0 |
| 764132428 | @Red_Army_SPT | 8 | 6 | 2 | 2 |
| 1709024359 | Гузель | 4 | 4 | 0 | 0 |
| 181620034 | @d_222bb | 4 | 3 | 0 | 45 |
| 734078871 | Евгения | 4 | 4 | 0 | 0 |
| 6465447151 | @stiil_me1991 | 3 | 2 | 1 | 0 |
| 5996024911 | @FannaRaim | 3 | 2 | 1 | 0 |
| 1404372253 | @OlgaShraer | 3 | 2 | 1 | 0 |
| 5156616414 | Наташа | 3 | 3 | 0 | 0 |

Всего строк в полном per-user export: **557**.

## 3. Telemetry Dashboard 24h

| metric | value |
| --- | --- |
| window_hours | 24 |
| users_total | 557 |
| users_subscribed | 0 |
| jobs_total | 277 |
| jobs_window | 0 |
| takes_window | 2 |
| takes_succeeded | 1 |
| takes_failed | 1 |
| take_avg_generation_sec | 45.7 |
| queue_length | 0 |
| succeeded | 0 |

### Jobs по статусам за 24 часа

_Нет данных_

### Top trends за 24 часа

| trend_id | name | jobs_window | takes_window | takes_succeeded_window | takes_failed_window | chosen_window |
| --- | --- | --- | --- | --- | --- | --- |
| 636ab87d-e3d2-4308-989c-2ab090ee22d3 | Розовая Нежность 🌸✨ | 0 | 1 | 1 | 0 | 0 |
| 0082ca59-5e91-4718-8897-91745df6f441 | Домашний портрет со вспышкой | 0 | 1 | 0 | 1 | 0 |
| 1c044ec9-b085-4f32-a5c1-780b47b92ebb | Стальная Уверенность ⚡ | 0 | 0 | 0 | 0 | 0 |
| f3174529-97bd-476f-8cbe-4fece2042936 | Солнечный Заяц 🐰 | 0 | 0 | 0 | 0 | 0 |
| e29ae296-96c9-4ae2-a148-ecb5e6cc45ec | Любимой маме 🌷 | 0 | 0 | 0 | 0 | 0 |
| bfa2059a-b1ce-4565-b650-2eb22d60a66d | Царский Завтрак 👑 | 0 | 0 | 0 | 0 | 0 |
| c6d9ed5f-0cf8-4a7a-a9e8-3d8a15b52fec | Ретро Поездка 🏎️ | 0 | 0 | 0 | 0 | 0 |
| 5e07ceee-2cdf-4ea2-aad2-ce2666deadf5 | Пламенная Нереида 🔥 | 0 | 0 | 0 | 0 | 0 |
| 6cd989f0-c3c4-4bff-b503-52787474b3ed | Белый Апокалипсис ☁️ | 0 | 0 | 0 | 0 | 0 |
| 3e6c11e9-540e-4ee8-95de-077aec3546cd | Зимний Ангел 👼 | 0 | 0 | 0 | 0 | 0 |
| 7a012b0c-dc68-4a73-b290-6afa87dd5145 | У зеркала | 0 | 0 | 0 | 0 | 0 |
| ad5579e3-ea37-44be-8fc7-aa109bbdd5d3 | Римские Каникулы 🇮🇹 | 0 | 0 | 0 | 0 | 0 |
| 1ede0d2e-b4e5-4d2c-9186-cf665789c31d | Синяя Элегантность 💙 | 0 | 0 | 0 | 0 | 0 |
| 0bb82da0-4e0c-4557-a38b-a57c48505ff7 | Золотой Сад 🌼 | 0 | 0 | 0 | 0 | 0 |
| 1172096d-ca95-495a-8f5c-25b4d404bf90 | Розовый Гламур 🎀💎 | 0 | 0 | 0 | 0 | 0 |
| fae6db84-6618-4d79-8cda-d98e19c0cfc2 | Снежная Икона 🏔️ | 0 | 0 | 0 | 0 | 0 |
| 202abf31-9c74-440a-af87-2b39921d5f8a | Лимонный Позитано 🍋 | 0 | 0 | 0 | 0 | 0 |
| 5b1a0826-beaf-412f-bd11-f3f0b5bb0bad | Роковая Леди 🔥 | 0 | 0 | 0 | 0 | 0 |
| 23daeb3e-c66f-4c8d-8fec-385aca843f5c | Красная Икона 🔥 | 0 | 0 | 0 | 0 | 0 |
| f68ad019-4f8e-4fc3-bd2b-ba77ff773240 | Ангел Роскоши 👑 | 0 | 0 | 0 | 0 | 0 |

## 4. Product Metrics

### Legacy product metrics 30d

| metric | value |
| --- | --- |
| window_days | 30 |
| dau | 1 |
| wau | 22 |
| mau | 226 |
| stickiness_pct | 0 |
| share_trial_purchases | 40.0 |
| avg_stars_per_pay_success | 0.0 |
| trial_purchases_count | 2 |
| total_pay_success_count | 5 |

### Product metrics v2 7d

| metric | value |
| --- | --- |
| window_days | 7 |
| preview_to_pay_pct | 50.0 |
| hit_rate_pct | 0.0 |
| aov_stars | 0.0 |
| total_stars | 0 |
| pay_success_count | 1 |
| take_preview_ready_count | 2 |
| sessions_with_preview | 2 |
| sessions_with_favorite | 0 |
| likeness_score_pct | 0.0 |
| total_likeness_feedback | 0 |
| repeat_purchase_rate_pct | 0.0 |
| paying_users | 1 |
| users_started | 6 |
| avg_time_start_to_result_sec | None |
| avg_steps_start_to_result | None |

### Product metrics v2 data quality 7d

| metric | value |
| --- | --- |
| pay_success_valid_price_events | 0 |
| pay_success_events | 1 |
| pay_success_valid_price_pct | 0.0 |

## 5. Funnel / Health / Revenue 7d

### Funnel counts

| step | legacy | shadow | diff |
| --- | --- | --- | --- |
| bot_started | 6 | 0 | -6 |
| photo_uploaded | 2 | 1 | -1 |
| take_preview_ready | 2 | 2 | 0 |
| favorite_selected | 0 | 0 | 0 |
| paywall_viewed | 0 | 0 | 0 |
| pack_selected | 0 | 0 | 0 |
| pay_initiated | 0 | 0 | 0 |
| pay_success | 0 | 0 | 0 |
| hd_delivered | 0 | 0 | 0 |

### Health data quality

| metric | value |
| --- | --- |
| total_events | 412 |
| funnel_events | 13 |
| funnel_missing_session_events | 10 |
| funnel_session_coverage_pct | 23.1 |
| button_click_events | 15 |
| button_missing_id_events | 0 |
| button_unknown_id_events | 0 |
| button_id_coverage_pct | 100.0 |
| pay_success_events | 1 |
| pay_success_valid_price_events | 0 |
| pay_success_valid_price_pct | 0.0 |
| unknown_events | 0 |
| unknown_events_pct | 0.0 |
| deprecated_schema_events | 412 |
| deprecated_schema_pct | 100.0 |

### Revenue 7d

| metric | value |
| --- | --- |
| window_days | 7 |
| total_stars | 0 |
| revenue_rub_approx | 0.0 |

### Revenue by pack 7d

| pack_id | value |
| --- | --- |
| neo_start | 0 |

### Revenue by source 7d

| source | value |
| --- | --- |
| organic | 0 |

### Revenue data quality 7d

| metric | value |
| --- | --- |
| pay_success_events | 1 |
| valid_price_events | 0 |
| invalid_price_events | 1 |
| valid_price_pct | 0.0 |

## 6. Buttons / Path 7d

### Button clicks

| button_id | clicks |
| --- | --- |
| menu_copy_style | 2 |
| menu_create_photo | 10 |
| menu_merge_photos | 1 |
| menu_profile | 1 |
| take_more | 1 |

### Unknown button clicks

_Нет данных_

### Path transitions

| from | to | sessions | median_minutes | avg_minutes |
| --- | --- | --- | --- | --- |
| bot_started | bot_started | 1 | 0.5 | 0.5 |
| bot_started | photo_uploaded | 2 | 4.1 | 4.1 |

### Path drop-off

| from | to | sessions | median_minutes | avg_minutes |
| --- | --- | --- | --- | --- |
| bot_started | None | 4 |  |  |
| photo_uploaded | None | 3 |  |  |
| take_preview_ready | None | 2 |  |  |

### Path sequences

| steps | sessions | median_minutes_to_pay | median_minutes_to_last | pct_reached_pay |
| --- | --- | --- | --- | --- |
| bot_started | 4 | None | 0.0 | 0.0 |
| take_preview_ready | 2 | None | 0.0 | 0.0 |
| photo_uploaded | 1 | None | 0.0 | 0.0 |
| bot_started -> bot_started -> photo_uploaded | 1 | None | 8.0 | 0.0 |
| bot_started -> photo_uploaded | 1 | None | 0.8 | 0.0 |

## 7. Payments / Audit / Errors

### Payments stats 30d

| metric | value |
| --- | --- |
| days | 30 |
| total_stars | 417 |
| total_rub_yoomoney | 855.0 |
| total_payments | 23 |
| refunds | 0 |
| unique_buyers | 15 |
| revenue_usd_approx | 5.42 |
| revenue_rub_approx | 1596.0 |
| revenue_rub_stars | 542.0 |
| star_to_rub | 1.3 |
| conversion_rate_pct | 0 |

### Payments by pack 30d

| pack_id | count | stars | rub |
| --- | --- | --- | --- |
| neo_pro | 1 | 0 | 0.0 |
| neo_start | 5 | 0 | 796.0 |
| neo_unlimited | 1 | 0 | 0.0 |
| plus | 1 | 115 | 0.0 |
| pro | 1 | 175 | 0.0 |
| standard | 1 | 65 | 0.0 |
| starter | 2 | 50 | 0.0 |
| trial | 3 | 0 | 258.0 |
| unlock | 6 | 12 | 0.0 |
| unlock_tokens | 2 | 0 | 0.0 |

### Audit stats 24h

| metric | value |
| --- | --- |
| total | 43 |
| window_hours | 24 |

### Audit by actor type 24h

| actor_type | count |
| --- | --- |
| system | 1 |
| user | 42 |

### Audit actions all time

| action | count |
| --- | --- |
| choose_best_variant | 88 |
| job_created | 277 |
| button_click | 15 |
| input_photo_analyzed | 3 |
| trend_take_started | 3 |
| photo_merge_count_selected | 47 |
| user_moderator_set | 2 |
| job_failed | 20 |
| paywall_variant_shown | 122 |
| payment_unlock | 12 |
| create | 24 |
| traffic_start | 472 |
| photo_merge_completed | 29 |
| take_preview_ready | 2 |
| referral_invite_view | 3 |
| generation_fallback_used | 2 |
| generation_started | 3 |
| bot_started | 7 |
| pay_success | 5 |
| start | 1130 |
| take_started | 252 |
| job_succeeded | 15 |
| photo_uploaded | 3 |
| audience_selected | 658 |
| telegram_message_bulk_update | 2 |
| copy_flow_reference_analyzed | 59 |
| generation_failed | 1 |
| unlock_with_tokens | 2 |
| paywall_shown | 2 |
| trend_viewed | 3 |
| generation_response | 244 |
| favorites_auto_add | 88 |
| hd_delivered | 32 |
| update | 97 |
| generation_request | 264 |
| photo_merge_photo_uploaded | 63 |
| generation_completed | 2 |
| pay_click | 35 |
| take_previews_ready | 239 |
| theme_selected | 3 |
| payment_pack | 7 |
| photo_merge_started | 72 |
| collection_started | 3 |
| favorites_opened | 22 |
| job_started | 35 |
| traffic_attribution | 4 |
| trend_preview_ready | 2 |
| trend_selected | 752 |

### Errors 30d combined

| error_code | count |
| --- | --- |
| provider_error | 17 |
| trend_missing | 1 |
| all_variants_failed | 10 |
| copy_prompt_missing | 1 |
