# Каталог событий телеметрии

Единый справочник событий для полного покрытия: каждый вход, каждый клик, каждый значимый шаг на каждого пользователя. Используется при добавлении новых событий в бот, воркеры и админку.

---

## Единое хранилище событий: audit_logs

**Все** события (клики, воронка, платежи, действия админа и воркеров) пишутся в таблицу **audit_logs**. Отдельного хранилища «product_events» для метрик нет: телеметрия и отчёты строятся из audit_logs (агрегации по `action`, `user_id`, `session_id`, `payload`).

- Запись: бот и воркеры вызывают `ProductAnalyticsService.track(...)` — события попадают в **audit_logs** (маппинг: `event_name` → `action`, `properties` → `payload`, плюс столбцы `user_id`, `session_id`). Админка и воркеры пишут через `AuditService.log(...)`.
- Чтение: эндпоинты телеметрии (`/admin/telemetry/product-funnel`, `product-funnel-history`, `button-clicks`, `product-metrics-v2`, `revenue`, `bank-transfer/pay-initiated`) читают только из **audit_logs**; формат ответов API не меняется.

Конвенция для «продуктовых» событий в audit_logs:

- **action** — имя события (бывший `event_name`): `bot_started`, `button_click`, `take_preview_ready`, `pay_success`, `photo_uploaded`, `favorite_selected`, `paywall_viewed`, `pack_selected`, `pay_initiated`, `hd_delivered`, `generation_started`, `generation_completed`, `generation_failed` и т.д.
- **user_id** (столбец) — внутренний UUID пользователя, когда событие относится к пользователю.
- **session_id** (столбец) — при наличии, для воронки и метрик по сессиям.
- **payload** — всё остальное: `button_id`, `trend_id`, `pack_id`, `source`, `campaign_id`, `take_id`, `job_id`, `price`, `price_rub`, `method` и т.д.

---

## Обязательные поля при записи в audit_logs

### Продуктовые события (ProductAnalyticsService.track → AuditService.log)

- **user_id** (столбец) — всегда (id пользователя в БД).
- **action** — тип события (см. разделы ниже); для кликов часто `"button_click"`.
- **payload** — объект; для всех кликов обязательно **payload.button_id**. По контексту: **session_id**, **take_id**, **job_id**, **trend_id**, **pack_id** в payload или в столбцах.

### Операционные события (AuditService.log напрямую)

- **actor_type** — `user` | `admin` | `system`.
- **actor_id** — telegram_id пользователя, username админа из JWT, или null для system.
- **action** — тип действия (см. Admin audit events).
- **entity_type** / **entity_id** — сущность при наличии.
- **payload** — JSON; без PII/секретов.

---

## 1. Bot command events (audit_logs)

События при вызове команд. Все с **action = "button_click"** и **payload.button_id** = имя команды без слэша.

| button_id     | Описание           | Обязательные поля |
|---------------|--------------------|-------------------|
| help          | /help              | user_id           |
| trends        | /trends            | user_id           |
| cancel        | /cancel            | user_id           |
| terms         | /terms             | user_id           |
| paysupport    | /paysupport        | user_id           |
| deletemydata  | /deletemydata      | user_id           |

---

## 2. Bot button / callback events (audit_logs)

### 2.1 Кнопки главного меню (ReplyKeyboard)

| button_id    | Текст кнопки        | Обязательные поля |
|--------------|----------------------|-------------------|
| menu_create_photo | Создать фото     | user_id           |
| menu_copy_style   | Сделать такую же | user_id           |
| menu_merge_photos | Соединить фото   | user_id           |
| menu_shop        | Купить пакет     | user_id           |
| menu_profile     | Мой профиль     | user_id           |

### 2.2 Навигация (callback_data)

| button_id   | callback_data | Обязательные поля   |
|-------------|---------------|---------------------|
| nav_menu    | nav:menu      | user_id             |
| nav_profile | nav:profile   | user_id             |
| nav_trends  | nav:trends    | user_id             |
| nav_themes  | nav:themes    | user_id             |

### 2.3 Выбор тематики и тренда

| action          | Описание                    | payload / контекст                       |
|-----------------|-----------------------------|------------------------------------------|
| theme_selected  | Выбор тематики или страницы | theme_id, page (опционально)             |
| format_selected | Выбор формата (aspect ratio)| format (например "1:1", "16:9")         |
| trend_viewed    | Уже есть                    | trend_id                                 |
| trend_selected  | В audit                     | —                                        |

### 2.4 Реферал и профиль

| button_id           | callback_data           | Обязательные поля |
|---------------------|-------------------------|-------------------|
| referral_invite     | referral:invite         | user_id           |
| referral_status     | referral:status         | user_id           |
| referral_back_profile | referral:back_profile | user_id           |
| profile_payment     | profile:payment         | user_id           |
| profile_support     | profile:support         | user_id           |

### 2.5 Магазин и оплата

| button_id        | callback_data / контекст | Обязательные поля   |
|------------------|---------------------------|---------------------|
| shop_open        | shop:open                 | user_id             |
| shop_how_buy_stars | shop:how_buy_stars      | user_id             |
| bank_transfer    | bank_transfer:start       | user_id             |
| bank_pack_{id}   | bank_pack:{pack_id}       | user_id, pack_id    |
| bank_transfer_cancel | bank_transfer:cancel   | user_id             |
| bank_transfer_retry  | bank_transfer:retry    | user_id             |
| pay_other        | pay_method:other          | user_id             |
| pay_yoomoney, pay_yoomoney_link, pay_stars | pay_method:*   | user_id, pack_id    |
| pack_{pack_id}   | paywall:{pack_id}         | user_id, pack_id    |

### 2.6 Избранное и HD

| button_id            | callback_data        | Обязательные поля     |
|----------------------|----------------------|------------------------|
| open_favorites       | open_favorites       | user_id                |
| favorites_clear_all  | favorites_clear_all   | user_id                |
| remove_fav_{fav_id}  | remove_fav:{fav_id}   | user_id                |
| select_hd_{fav_id}   | select_hd:{fav_id}   | user_id                |
| deselect_hd_{fav_id} | deselect_hd:{fav_id} | user_id                |
| hd_problem_{fav_id}  | hd_problem:{fav_id}  | user_id                |
| session_status       | session_status       | user_id                |
| deliver_hd, deliver_hd_album, deliver_hd_one_{fav_id} | — | user_id, take_id при наличии |

### 2.7 Recovery и успех

| button_id              | callback_data              | Обязательные поля |
|------------------------|----------------------------|-------------------|
| error_replace_photo    | error_action:replace_photo | user_id           |
| error_choose_trend     | error_action:choose_trend:*| user_id, job_id   |
| success_menu           | success_action:menu        | user_id           |
| success_more           | success_action:more        | user_id           |
| unlock_check           | unlock_check:{order_id}    | user_id           |
| unlock_resend          | unlock_resend:{order_id}   | user_id           |
| pack_check             | pack_check:{order_id}      | user_id           |

### 2.8 Согласие и контент

| event_name             | Описание                        | properties / контекст     |
|------------------------|---------------------------------|----------------------------|
| consent_accepted       | Принятие согласия на обработку фото | user_id                |
| custom_prompt_submitted| Ввод текста «Своя идея»         | user_id, length (опц.)     |
| bank_receipt_uploaded  | Отправка чека (bank transfer)   | user_id (без PII в payload)|
| rescue_photo_uploaded   | Загрузка другого фото (rescue)  | user_id, take_id           |

### 2.9 Перегенерация

| button_id     | callback_data     | Обязательные поля |
|---------------|-------------------|-------------------|
| regenerate    | regenerate:{job_id}| user_id, job_id   |

---

## 3. Worker events

### 3.1 События воркеров в audit_logs

- take_preview_ready, collection_started, pay_success, hd_delivered, job_created, generation_started, generation_failed и др. (см. FUNNEL_EVENT_NAMES и код воркеров). Пишутся в audit_logs (через ProductAnalyticsService.track или AuditService.log).

### 3.2 audit_logs (действия системы)

| action                | entity_type    | Где писать              |
|-----------------------|----------------|-------------------------|
| job_started           | job            | generation_v2 (старт задачи) |
| job_succeeded         | job            | generation_v2 (успех)   |
| job_failed            | job            | generation_v2 (ошибка)  |
| generation_request   | job            | generation_v2 / runner  |
| generation_response   | job            | generation_v2 / runner  |
| take_previews_ready   | take           | generate_take (уже есть) |
| hd_delivered          | favorite       | deliver_hd (уже есть)   |
| collection_drop_step  | session        | watchdog (уже есть)     |
| photo_merge_completed | photo_merge_job| merge_photos (уже есть) |
| photo_merge_failed    | photo_merge_job| merge_photos (уже есть) |
| unlock_delivered      | payment / order| deliver_unlock          |
| unlock_delivery_failed| payment / order| deliver_unlock          |
| cleanup               | temp_files     | admin cleanup/run       |

Payload для generation_request/response — по контракту AuditPage: request_as_seen_by_provider, request_parts, response_summary, raw_gemini_response (sanitized).

---

## 4. Admin audit events (audit_logs)

Все мутирующие эндпоинты admin API пишут в audit с **actor_type="admin"**, **actor_id** из JWT текущего пользователя.

| action / группа      | entity_type | Пример эндпоинта                    |
|----------------------|-------------|--------------------------------------|
| user_banned          | user        | POST /security/users/{id}/ban        |
| user_unbanned        | user        | POST /security/users/{id}/unban      |
| user_suspended       | user        | POST /security/users/{id}/suspend    |
| user_resumed         | user        | POST /security/users/{id}/resume     |
| rate_limit_set       | user        | POST /security/users/{id}/rate-limit |
| security_reset_limits| user        | POST /security/reset-limits          |
| user_grant_pack      | user        | POST /users/{id}/grant-pack          |
| user_reset_limits    | user        | POST /users/{id}/reset-limits        |
| settings_updated     | settings    | PUT /settings/* (transfer-policy, app, preview-policy, master-prompt, bank-transfer, copy-style, photo-merge) |
| theme_created        | theme       | POST /themes                         |
| theme_updated        | theme       | PUT /themes/{id}                     |
| theme_deleted        | theme       | DELETE /themes/{id}                  |
| trend_created        | trend       | POST /trends                         |
| trend_updated        | trend       | PUT /trends/{id}                     |
| pack_created         | pack        | POST /packs                          |
| pack_updated         | pack        | PUT /packs/{id}                      |
| pack_deleted         | pack        | DELETE /packs/{id}                   |
| payment_refund       | payment     | POST /payments/{id}/refund            |
| broadcast_sent       | —           | POST /broadcast/send                 |
| cleanup_run          | temp_files  | POST /cleanup/run                    |
| traffic_source_*     | traffic_source | POST/PATCH/DELETE /traffic-sources, /ad-campaigns |
| telegram_messages_*  | —           | POST /telegram-messages/*             |

Payload: безопасный контекст (id сущности, имя настройки, без секретов). Для cleanup — количество удалённых записей, ttl.

---

## Именование button_id

- Один идентификатор на одно действие пользователя.
- Формат: `{область}_{конкретное_действие}` или `{callback_prefix}` (например nav_menu, shop_open, pack_trial).
- Для кнопок с сущностью: `remove_fav`, `select_hd`, `deselect_hd`, `hd_problem` — entity_id передаётся в properties или в callback_data, в отчётах можно группировать по префиксу.

---

## Надёжность и мониторинг качества телеметрии

Рекомендуемые метрики для алертов и дашбордов (реализация — по необходимости в Prometheus/Grafana или админке):

1. **audit_logs (продуктовые события)**
   - Доля событий без **user_id** (ожидается 0 для событий из бота/воркеров).
   - Доля событий с **action = "button_click"** без **payload.button_id** (ожидается 0).
   - Latency записи (время от вызова `track()` / `AuditService.log` до commit) — при росте объёма.

2. **audit_logs (индексы и объём)**
   - Индексы: `created_at`, `action`, `actor_type`, `entity_type` (миграция 006 и 067) — для быстрых фильтров в GET /admin/audit и аналитике.
   - При необходимости: sampling только для высокочастотных технических событий; бизнес-критичные (платежи, админские действия) не семплировать.
