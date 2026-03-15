# Блок "Аудит": устройство и карта данных

## Что именно считается блоком "Аудит"

В проекте есть две реализации просмотра аудита:

1. Основная актуальная: React-страница админки `admin-frontend/src/pages/AuditPage.tsx`.
2. Legacy-версия: server-rendered HTML `app/admin/templates/audit_list.html`, открывается через `app/admin/ui.py`.

Основной источник данных для обеих реализаций один: таблица `audit_logs`.

---

## 1. Архитектура блока

```mermaid
flowchart LR
  A[Bot / API / Worker / PaymentService / ProductAnalytics] --> B[AuditService.log]
  B --> C[(PostgreSQL.audit_logs)]
  C --> D[/GET /admin/audit]
  C --> E[/GET /admin/audit/filters]
  C --> F[/GET /admin/audit/stats]
  C --> G[/GET /admin/audit/analytics]
  D --> H[React AuditPage]
  E --> H
  F --> H
  G --> H
  D --> I[Legacy audit_list.html]
```

Ключевой принцип: `audit_logs` используется как единый event log. Из него строится не только журнал, но и часть аналитики.

---

## 2. Слой хранения данных

## Таблица `audit_logs`

Базовая схема появилась в `migrations/schema.sql`, позже была расширена полями `user_id` и `session_id`.

Поля:

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `TEXT/UUID string` | ID записи |
| `actor_type` | `TEXT` | Кто создал событие: `user`, `admin`, `system` |
| `actor_id` | `TEXT \| NULL` | Внешний идентификатор актора |
| `action` | `TEXT` | Имя события |
| `entity_type` | `TEXT` | Тип сущности |
| `entity_id` | `TEXT \| NULL` | ID сущности |
| `payload` | `JSONB` | Произвольные дополнительные данные |
| `created_at` | `TIMESTAMPTZ` | Время события |
| `user_id` | `TEXT \| NULL` | Внутренний `users.id` для аналитики/фильтров |
| `session_id` | `TEXT \| NULL` | Связь с пользовательской сессией |

## Индексы

Для блока аудита и аналитики важны индексы:

- `created_at DESC`
- `(actor_type, created_at DESC)`
- `(action, created_at DESC)`
- `(entity_type, created_at DESC)`
- `(user_id, created_at DESC)` с `WHERE user_id IS NOT NULL`
- `(session_id, created_at DESC)` с `WHERE session_id IS NOT NULL`

Это объясняет, почему UI активно использует фильтры по `actor_type`, `action`, `entity_type`, `user_id`, `session_id`.

---

## 3. Запись данных в аудит

## Базовый механизм

Центральная точка записи: `app/services/audit/service.py`.

`AuditService.log(...)`:

- создаёт `AuditLog`
- пишет запись в БД
- сразу делает `commit()`
- делает `refresh()`
- возвращает сохранённую запись

Это важно: аудит живёт как отдельная транзакция. Если событие уже записано, а основной сценарий упал позже, запись в аудите может остаться.

## Кто пишет в `audit_logs`

### 1. Admin API

Хелпер `_admin_audit(...)` в `app/api/routes/admin.py` пишет административные действия:

- `actor_type = "admin"`
- `actor_id = current_user.username || "unknown"`
- `action` и `entity_*` зависят от конкретного admin endpoint

Примеры событий:

- `update` для настроек
- `user_banned`
- `user_unbanned`
- `user_suspended`
- `reset_limits`
- `refund`
- `create/update/delete` для pack/theme/trend
- `broadcast`

### 2. ProductAnalyticsService

`app/services/product_analytics/service.py` тоже пишет в `audit_logs`, но через `AuditService.log`.

Он:

- принимает бизнес-событие `event_name`
- нормализует payload
- автоматически пробрасывает `user_id`
- автоматически пробрасывает `session_id`
- использует `actor_type = "user"`
- подставляет `actor_id = telegram_id`, если пользователь найден

Это делает `audit_logs` единым источником и для журнала, и для продуктовой аналитики.

Типичные события:

- `bot_started`
- `button_click`
- `photo_uploaded`
- `take_preview_ready`
- `favorite_selected`
- `paywall_viewed`
- `pay_initiated`
- `pay_success`
- `hd_delivered`

### 3. Bot

`app/bot/main.py` местами пишет напрямую через `AuditService.log`, без `ProductAnalyticsService`.

Типичные прямые события из бота:

- `start`
- `traffic_start`
- `referral_start`
- `referral_attributed`
- часть событий выбора/запуска сценария

### 4. Workers

Celery-задачи пишут системные события:

- `generate_take.py` пишет `take_previews_ready`
- `generation_v2.py` пишет `generation_request`, `generation_response`, технические статусы
- `deliver_hd.py` пишет доставку HD
- `deliver_unlock.py` пишет доставку unlock
- `merge_photos.py` пишет события merge photo
- `watchdog_rendering.py` пишет системные диагностики

Обычно у таких записей:

- `actor_type = "system"`
- `actor_id = имя задачи/сервиса`

### 5. PaymentService

`app/services/payments/service.py` пишет системные записи вокруг покупок и старта коллекций.

Пример:

- `collection_start`

## Нормализованные поля и "сырой" payload

Архитектурно запись делится на две части:

1. Нормализованная шапка:
   `actor_type`, `actor_id`, `action`, `entity_type`, `entity_id`, `user_id`, `session_id`, `created_at`
2. Неструктурированное содержимое:
   `payload`

Именно поэтому:

- фильтры и агрегаты строятся по шапке
- детализация и отладка строятся по `payload`

---

## 4. Чтение данных: backend API блока

Все актуальные API блока находятся в `app/api/routes/admin.py`.

## `GET /admin/audit/filters`

Назначение: вернуть списки действий и типов сущностей для фильтров.

Особенности:

- окно по умолчанию: `window_days = 90`
- кэш в памяти на 5 минут
- выборка ограничена `500_000` строками
- возвращает:
  - `actions[]`
  - `entity_types[]`
  - `window_days`

## `GET /admin/audit`

Назначение: список записей аудита.

Поддерживаемые фильтры:

- `action`
- `actor_type`
- `entity_type`
- `audience` из `payload["audience"]`
- `date_from`
- `date_to`
- `search` по `actor_id` и `entity_id`
- `user_id`
- `session_id`
- `page`
- `page_size`

Что делает endpoint:

1. Строит SQLAlchemy query по `AuditLog`
2. Применяет фильтры
3. Считает `total`
4. Возвращает страницу, отсортированную по `created_at DESC`
5. Для пользовательских событий отдельно подтягивает display name по `User.telegram_id == actor_id`

Выходной формат записи:

- `id`
- `actor_type`
- `actor_id`
- `actor_display_name`
- `action`
- `entity_type`
- `entity_id`
- `user_id`
- `session_id`
- `payload`
- `created_at`

## `GET /admin/audit/stats`

Назначение: быстрые агрегаты.

Возвращает:

- `total`
- `by_actor_type`
- `window_hours`

В React-странице вызывается не за 24 часа, а за очень большое окно `876000` часов, то есть фактически "за всё время".

## `GET /admin/audit/analytics`

Назначение: агрегаты для вкладки аналитики.

Поддерживает фильтры:

- `date_from`
- `date_to`
- `action`
- `actor_type`
- `entity_type`
- `audience`
- `user_id`
- `session_id`

Возвращает:

- `events_by_day`
- `by_action`
- `by_actor_type`
- `top_actors`

`top_actors` считается только для `actor_type = "user"` и агрегируется по `actor_id`.

---

## 5. UI-слой: React AuditPage

## Вход в страницу

Маршрут подключён в `admin-frontend/src/App.tsx` как `/audit`.

## Какие запросы делает страница

Страница использует 3 основных чтения и 1 вспомогательное:

1. `auditService.getFilters()`
2. `auditService.getStats()`
3. `auditService.list()`
4. `auditService.getAnalytics()`

Все вызовы объявлены в `admin-frontend/src/services/api.ts`.

## Локальное состояние страницы

Состояния:

- `page`
- `actorType`
- `action`
- `entityType`
- `audienceFilter`
- `search`
- `userIdFilter`
- `sessionIdFilter`
- `selectedLog`
- `liveEnabled`

## Реально доступные фильтры в UI

React-страница выводит:

- поиск по `actor_id/entity_id`
- фильтр по `user_id`
- фильтр по `session_id`
- `actor_type`
- `action`
- `entity_type`
- `audience`

Важно: backend умеет `date_from/date_to`, но текущий React UI эти поля не показывает и не использует.

## KPI и вкладки

Экран состоит из:

1. KPI-карточек:
   - всего записей
   - за сегодня
   - топ действие
   - ошибки (`job_failed`, `pay_failed`, `unlock_delivery_failed`)
2. Вкладки:
   - `Журнал`
   - `Аналитика`

## Журнал

В таблице журнала выводятся:

- время
- актор
- действие
- аудитория
- сущность
- сокращённый `entity_id`
- краткий preview `payload`

По клику строка открывает `AuditDetailPanel`.

## Детальная панель

Страница умеет отдельно разбирать специальные payload-форматы:

### `generation_request`

Отрисовывает вкладки:

- "Как видит Gemini"
- "Промпт"
- "Мета"
- "JSON"

Используемые поля payload:

- `prompt`
- `request_as_seen_by_provider`
- `request_parts`

### `generation_response`

Отрисовывает вкладки:

- "Как ответил Gemini"
- "Полный ответ API"
- `response_summary`
- весь payload

Используемые поля payload:

- `response_summary`
- `raw_gemini_response`

### Остальные события

Показываются как pretty-printed JSON payload.

## Live-режим

При `liveEnabled = true`:

- список аудита автообновляется каждые 15 секунд
- stats тоже автообновляются каждые 15 секунд

Аналитика live-обновление не использует.

## Fallback-логика

Если `/admin/audit/filters` недоступен или вернул пусто, страница использует встроенные статические списки:

- `ACTIONS`
- `ENTITY_TYPES`

Это защищает UI от частичного отказа backend.

---

## 6. Legacy-страница аудита

Legacy-версия проще:

- только таблица
- только фильтр по `action`
- прямой `fetch('/admin/audit')`
- без аналитики
- без детальной боковой панели

Она существует параллельно с новой SPA и использует тот же endpoint списка.

---

## 7. Полная карта данных

## Поток записи

```text
Источник события
  -> AuditService.log(...) или ProductAnalyticsService.track(...)
  -> нормализация полей actor/action/entity/user/session
  -> payload JSONB
  -> INSERT + COMMIT в audit_logs
```

## Поток чтения в React

```text
AuditPage state
  -> buildAuditListParams / buildAuditAnalyticsParams
  -> auditService (axios)
  -> /admin/audit* endpoints
  -> SQLAlchemy query к audit_logs
  -> JSON response
  -> таблица / KPI / графики / detail drawer
```

## Карта полей

| Источник | Что пишет | Куда ложится |
|---|---|---|
| `AuditService.log(actor_type=..., actor_id=...)` | Тип и ID актора | `actor_type`, `actor_id` |
| `ProductAnalyticsService.track(event_name)` | Имя события | `action` |
| `ProductAnalyticsService.track(entity_type/entity_id)` | Привязка к сущности | `entity_type`, `entity_id` |
| `ProductAnalyticsService.track(user_id, session_id)` | Аналитические связи | `user_id`, `session_id` |
| `properties` / `payload` | Дополнительные данные | `payload` |
| БД default / `AuditService` | Время и ID записи | `id`, `created_at` |

## Карта чтения полей в UI

| Поле | Где используется |
|---|---|
| `created_at` | таблица журнала, график `events_by_day` |
| `actor_type` | иконка актора, фильтр, stats |
| `actor_id` | поиск, top actors, fallback-отображение |
| `actor_display_name` | человекочитаемое имя пользователя |
| `action` | бейдж действия, фильтр, bar chart, KPI "топ действие" |
| `entity_type` | фильтр и колонка сущности |
| `entity_id` | колонка ID, fallback preview |
| `payload.audience` | фильтр ЦА и колонка ЦА |
| `payload.*` | preview в таблице и detail drawer |
| `user_id` | отдельный фильтр в UI |
| `session_id` | отдельный фильтр в UI |

## Карта аналитических представлений

| Представление | Источник |
|---|---|
| Всего записей | `/admin/audit/stats` |
| За сегодня | `/admin/audit/analytics.events_by_day` |
| Топ действие | `/admin/audit/analytics.by_action` |
| Ошибки | сумма по `job_failed`, `pay_failed`, `unlock_delivery_failed` |
| График по дням | `/admin/audit/analytics.events_by_day` |
| График по действиям | `/admin/audit/analytics.by_action` |
| Топ пользователей | `/admin/audit/analytics.top_actors` |

---

## 8. Семантика данных внутри блока

Блок "Аудит" смешивает три разных типа данных в одной таблице:

1. Журнал пользовательских действий
   - клики, шаги воронки, выборы, оплаты
2. Журнал системных событий
   - генерация, воркеры, доставка, ответы провайдера
3. Журнал действий админа
   - настройки, модерация, CRUD в админке

Из-за этого один и тот же экран решает сразу две задачи:

- операционный журнал
- аналитический просмотр событий

Это ключевая архитектурная особенность блока.

---

## 9. Важные наблюдения по устройству

1. `audit_logs` в проекте является не "вторичным логом", а центральным слоем событий.
2. React-страница читает журнал "за всё время", хотя backend поддерживает диапазоны дат.
3. `payload` используется как flexible schema: удобно для развития, но часть фильтров живёт внутри JSONB, а не в колонках.
4. Для пользователя UI показывает friendly name только если `actor_type == "user"` и `actor_id` совпадает с `User.telegram_id`.
5. `ProductAnalyticsService.track()` физически пишет в тот же `audit_logs`, а не в отдельную таблицу аналитики.
6. Запись аудита делает собственный `commit()`, поэтому событие может сохраниться независимо от остального бизнес-сценария.
7. Фильтры `actions/entity_types` в UI не полностью динамические: есть резервный статический набор на случай проблем API.
8. В проекте остаётся legacy-экран аудита, но основная функциональность уже живёт в SPA.

---

## 10. Краткий итог

Блок "Аудит" устроен как витрина над единой таблицей `audit_logs`.

Сверху:

- React-страница с фильтрами, таблицей, аналитикой и детальным просмотром payload

Посередине:

- 4 admin endpoint'а: `filters`, `list`, `stats`, `analytics`

Снизу:

- единый event log, который наполняют bot, admin API, workers, payment services и product analytics

Итоговая роль блока:

- просмотр событий
- отладка генерации и payload'ов провайдера
- контроль админских действий
- лёгкая аналитика по действиям и акторам
