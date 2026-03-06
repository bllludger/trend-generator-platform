# AS-IS: Метрики сервиса для бизнеса

**Документ:** обзор всех метрик и данных из БД, доступных для оценки текущего состояния продукта (Trend Generator / Nano Banana).

---

## Слайд 1 — Оглавление

1. Пользователи и аудитория  
2. Генерации: снимки (Take) и задачи (Job)  
3. Платежи и выручка  
4. Пакеты и монетизация  
5. Реферальная программа  
6. Дополнительные продукты (склейка фото, постер)  
7. Безопасность и модерация  
8. Источники данных (API)

---

## Слайд 2 — Пользователи (Users)

| Метрика | Описание | Где взять |
|--------|----------|-----------|
| **Всего пользователей** | Зарегистрированные в боте (telegram_id) | `GET /admin/users/analytics` → `overview.total_users` |
| **Активные подписчики** | subscription_active = true (ручное управление админом) | `overview.active_subscribers` |
| **Конверсия в подписку** | % подписчиков от всех пользователей | `overview.conversion_rate` |
| **Забанено** | is_banned = true | `GET /admin/security/overview` → `banned_count` |
| **Приостановлено** | is_suspended (временно) | `suspended_count` |
| **С кастомным rate-limit** | rate_limit_per_hour задан вручную | `rate_limited_count` |
| **Модераторы** | без лимитов | `moderators_count` |

**Из БД (users):**
- `token_balance` — баланс генераций (legacy)
- `free_generations_used`, `copy_generations_used` — использование бесплатных слотов
- `total_purchased` — всего куплено генераций за Stars
- `hd_paid_balance`, `hd_promo_balance` — баланс HD (4K)
- `free_takes_used`, `trial_purchased` — сессионный флоу
- `referral_code`, `referred_by_user_id` — реферальная программа
- `created_at`, `updated_at` — даты

---

## Слайд 3 — Активность: DAU / WAU / MAU и «липкость»

| Метрика | Описание | API |
|--------|----------|-----|
| **DAU** | Уникальные пользователи с хотя бы одним Job или Take за последние 24 ч | `GET /admin/telemetry/product-metrics` → `dau` |
| **WAU** | За 7 дней | `wau` |
| **MAU** | За 30 дней | `mau` |
| **Stickiness** | DAU/MAU × 100% | `stickiness_pct` |

Параметр: `window_days` (по умолчанию 7).

---

## Слайд 4 — Снимки (Take) — основной флоу «Создать фото»

Один «снимок» = одна генерация с 3 вариантами (A/B/C); пользователь выбирает вариант → избранное → по запросу HD.

| Метрика | Описание | Где взять |
|--------|----------|-----------|
| **Take за период** | Количество снимков за окно (часы) | `GET /admin/telemetry?window_hours=24` → `takes_window` |
| **По трендам** | Take по каждому тренду за окно | `trend_analytics_window[]` → `takes_window`, `takes_succeeded_window`, `takes_failed_window` |
| **Выбор варианта** | Сколько раз пользователь выбрал вариант в избранное | `chosen_window` по тренду |

**Статусы Take:** `generating` → `ready` | `partial_fail` | `failed`.

---

## Слайд 5 — Задачи (Job) — перегенерация / legacy

Один кадр, paywall/unlock. Метрики:

| Метрика | Описание | API |
|--------|----------|-----|
| **Всего Job за период** | За N часов | `GET /admin/telemetry?window_hours=24` → `jobs_window`, `jobs_total` |
| **По статусам** | CREATED, RUNNING, SUCCEEDED, FAILED, ERROR | `jobs_by_status` |
| **В очереди** | CREATED + RUNNING | `queue_length` |
| **Успешные (всего)** | SUCCEEDED за всё время | `succeeded` |
| **Ошибки по коду** | За окно | `jobs_failed_by_error` |
| **Аналитика по дням/трендам/пользователям** | Детализация | `GET /admin/jobs/stats`, `GET /admin/jobs/analytics` |

---

## Слайд 6 — История и ошибки

| Эндпоинт | Что даёт |
|----------|----------|
| **GET /admin/telemetry/history** | По дням за N дней: `jobs_total`, `jobs_succeeded`, `jobs_failed`, `active_users`, `takes_total` |
| **GET /admin/telemetry/errors** | За N дней: ошибки Job и Take по `error_code`, `errors_by_day` (график провалов) |

Параметры: `window_days` (по умолчанию 7 для history, 30 для errors).

---

## Слайд 7 — Платежи (Payments)

Все транзакции Telegram Stars. Метрики за N дней:

| Метрика | Описание | API |
|--------|----------|-----|
| **Количество платежей** | completed | `GET /admin/payments/stats?days=30` → `total_payments` |
| **Сумма в Stars** | total_stars | `total_stars` |
| **Выручка (приблизительно)** | USD и RUB по курсу | `revenue_usd_approx`, `revenue_rub_approx` |
| **Рефанды** | refunded за период | `refunds` |
| **Уникальные покупатели** | distinct user_id | `unique_buyers` |
| **По пакетам** | pack_id, количество, Stars | `by_pack` |

Курсы в коде: 1 Star ≈ $0.013, ≈ 1.3 ₽.

---

## Слайд 8 — Продуктовые метрики и воронка

**GET /admin/telemetry/product-metrics** (параметр `window_days`, по умолчанию 7):

| Метрика | Описание |
|--------|----------|
| **funnel_counts** | Счётчики по действиям: `collection_start`, `take_previews_ready`, `pay_success`, `collection_complete`, `hd_delivered` |
| **Доля Trial** | % покупок пакета trial от всех pay_success | `share_trial_purchases`, `trial_purchases_count` |
| **Средний чек (Stars)** | На один pay_success | `avg_stars_per_pay_success` |
| **Распределение по активности** | Пользователи с 1, 2–5, 6–10, 11–20, 21+ Job за окно | `jobs_per_user_distribution` |

---

## Слайд 9 — Пакеты (Packs)

Настраиваемые продукты за Stars (админка). Из БД (packs):

| Поле | Описание |
|------|----------|
| name, emoji | Название и иконка |
| tokens | Количество генераций (legacy) |
| stars_price | Цена в Stars |
| takes_limit, hd_amount | Лимит снимков и HD в сессии (MVP) |
| is_trial, pack_type | Триал, тип пакета |
| enabled, order_index | Включён ли, порядок |

Список: **GET /admin/packs**. Выручка по пакетам — в **GET /admin/payments/stats** → `by_pack`.

---

## Слайд 10 — Аналитика пользователей (когорты и сегменты)

**GET /admin/users/analytics** (параметр `time_window` в днях, по умолчанию 30):

| Блок | Содержание |
|------|------------|
| **overview** | total_users, active_subscribers, conversion_rate, avg_jobs_per_user |
| **growth_list** | Новые пользователи по дням (последние 14 дней) |
| **cohorts** | Новые пользователи по месяцам (последние 12 месяцев) |
| **activity_segments** | Пользователи: «Без задач», «1–5 задач», «6–20», «21+» за окно |
| **token_distribution** | Распределение по балансу: 0, 1–100, 101–500, 501–1000, 1001+ |
| **top_users** | Топ-10 по количеству Job (с succeeded/failed, подписка, баланс) |

---

## Слайд 11 — Реферальная программа

| Метрика | Описание | API |
|--------|----------|-----|
| **Приведённые пользователи** | referred_by_user_id не пусто | `GET /admin/referrals/stats` → `total_attributed` |
| **Бонусы** | Всего записей ReferralBonus | `total_bonuses` |
| **По статусам** | pending, available, spent, revoked | `by_status` |
| **Кредиты HD** | Суммы в pending / available / spent | `credits` |

Детали бонусов: **GET /admin/referrals/bonuses** (фильтр status, пагинация).

---

## Слайд 12 — Компенсации (Compensation)

Логи компенсаций (HD-кредиты и т.п.).  
**GET /admin/compensations/stats** — всего и по `reason`, по пользователям.  
Таблица: `compensation_log` (user_id, favorite_id, session_id, reason, comp_type, amount).

---

## Слайд 13 — Склейка фото (Photo Merge)

| Метрика | Описание | API |
|--------|----------|-----|
| **Всего заданий** | За window_days | `GET /admin/photo-merge/stats` → `total` |
| **Успешно / ошибки / в работе** | succeeded, failed, processing | `succeeded`, `failed`, `processing` |
| **Success rate** | % | `success_rate` |
| **Время** | avg_duration_ms, p50, p95 | `avg_duration_ms`, `p50_duration_ms`, `p95_duration_ms` |
| **Объёмы** | Байты вход/выход | `total_input_bytes`, `total_output_bytes` |
| **Топ пользователей** | По количеству склеек | `top_users` |
| **По дням** | total, succeeded, failed по дате | `by_day` |

---

## Слайд 14 — Тренды и постер

- **Тренды (trends):** каталог стилей генерации. В телеметрии — топ по Job/Take за окно, выбор вариантов по трендам.
- **Публикации в канал (trend_posts):** статусы draft / sent / deleted. Настройки канала и шаблона — **poster_settings** (одна запись).

Отдельного агрегирующего «дашборда по постерам» в API нет — данные в БД: `trend_posts`, `poster_settings`.

---

## Слайд 15 — Безопасность и аудит

| Раздел | Описание |
|--------|----------|
| **Security overview** | banned, suspended, rate_limited, moderators, total_users |
| **Список пользователей** | GET /admin/security/users (фильтры: banned, suspended, rate_limited, active, telegram_id) |
| **Аудит** | GET /admin/audit/stats — за окно: по actor_type, по action, по датам, топ акторов |

Таблица **audit_logs**: actor_type, actor_id, action, entity_type, entity_id, payload, created_at.

---

## Слайд 16 — Источники данных (сводка API)

| Назначение | Метод и путь |
|------------|--------------|
| Общая телеметрия (юзеры, Job, Take, очередь, тренды, ошибки) | GET /admin/telemetry?window_hours=24 |
| Продуктовые метрики (DAU/WAU/MAU, воронка, AOV, Trial) | GET /admin/telemetry/product-metrics?window_days=7 |
| История по дням | GET /admin/telemetry/history?window_days=7 |
| Ошибки по кодам и по дням | GET /admin/telemetry/errors?window_days=30 |
| Аналитика пользователей (когорты, сегменты, топ) | GET /admin/users/analytics?time_window=30 |
| Статистика Job | GET /admin/jobs/stats?hours=24 |
| Аналитика Job (по дням, трендам, пользователям) | GET /admin/jobs/analytics |
| Платежи | GET /admin/payments/stats?days=30 |
| Рефералы | GET /admin/referrals/stats |
| Компенсации | GET /admin/compensations/stats |
| Склейка фото | GET /admin/photo-merge/stats?window_days=30 |
| Безопасность | GET /admin/security/overview |
| Аудит | GET /admin/audit/stats?window_hours=24 |

Все запросы — через админ-API с JWT-авторизацией.

---

## Слайд 17 — Итог: что есть для оценки AS-IS

- **Пользователи:** объём, подписка, когорты по месяцам, сегменты по активности, распределение по балансу.
- **Генерации:** снимки (Take) и задачи (Job) в разрезе времени, трендов, статусов и ошибок.
- **Монетизация:** платежи, выручка в Stars/USD/RUB, разбивка по пакетам, Trial, средний чек.
- **Воронка:** от старта коллекции до оплаты и выдачи HD.
- **Рефералы и компенсации:** объёмы и статусы.
- **Доп. продукты:** склейка фото (объём, успешность, латентность).
- **Безопасность и аудит:** бан/саспенд, лимиты, логи действий.

Данные можно выгружать из перечисленных эндпоинтов и визуализировать в отчётах и дашбордах.
