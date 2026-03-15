# Анализ пробелов: что есть и чего не хватает

Полный разбор соответствия admin-frontend (React) и бэкенда (FastAPI), а также недостающих API и логики.

---

## 1. Текущее состояние бэкенда (app/main.py)

**Подключённые роутеры:**

| Роутер        | Префикс/пути              | Назначение                    |
|---------------|----------------------------|-------------------------------|
| health        | `/health`, `/ready`        | Liveness/readiness, healthcheck Docker |
| auth          | `/admin/auth/login`, `/logout`, `/me` | JWT-авторизация админа |
| trends        | `/trends`                  | Публичный список трендов (только активные) |
| admin_ui      | `/admin-ui/*`              | HTML-страницы старой админки (Jinja2) |
| metrics       | `/metrics`                 | Prometheus |

**Итого:** API стартует, контейнер проходит healthcheck. Реакт-админка может залогиниться (`/admin/auth/*`), но все остальные страницы будут уходить в **404**, т.к. эндпоинтов `/admin/*` (кроме auth) нет.

---

## 2. Чего ждёт admin-frontend (api.ts) и чего нет в API

Фронт ходит на один baseURL (порт 8000). Ниже — полный список вызовов и наличие на бэке.

### 2.1. Auth — есть

| Метод | Путь | Бэкенд |
|-------|------|--------|
| POST | `/admin/auth/login` | есть |
| POST | `/admin/auth/logout` | есть |
| GET  | `/admin/auth/me` (через interceptor) | есть |

**Мелкое несоответствие:** фронт ожидает `user: { id: string; username: string }`. Сейчас бэкенд отдаёт только `username`. Поле `id` можно добавить в ответ login/me (например, `id: username` или отдельная таблица админов).

---

### 2.2. Security — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET  | `/admin/security/settings` | Настройки лимитов, банов, подписчиков |
| PUT  | `/admin/security/settings` | Обновление настроек |
| GET  | `/admin/security/overview` | Сводка: banned_count, suspended_count, rate_limited_count, moderators_count, total_users |
| GET  | `/admin/security/users` | Список пользователей с фильтрами (page, page_size, filter_status, telegram_id) |
| POST | `/admin/security/users/:id/ban` | Забанить |
| POST | `/admin/security/users/:id/unban` | Разбанить |
| POST | `/admin/security/users/:id/suspend` | Временная блокировка (hours, reason) |
| POST | `/admin/security/users/:id/resume` | Снять суспенд |
| POST | `/admin/security/users/:id/rate-limit` | Установить лимит (limit \| null) |
| POST | `/admin/security/reset-limits` | Сброс лимитов по всем |
| POST | `/admin/security/users/:id/moderator` | Выдать/забрать права модератора |

**Бэкенд:** Есть `SecuritySettingsService`, модель `SecuritySettings`. Нет HTTP-роутов и нет логики бана/суспенда/модератора по пользователям (нет полей или отдельной таблицы под это в User — нужно уточнить модель).

---

### 2.3. Transfer policy — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/admin/settings/transfer-policy` | Настройки политики переноса |
| PUT | `/admin/settings/transfer-policy` | Обновление |

**Бэкенд:** Есть `app.services.transfer_policy.service`, модель `TransferPolicy`. Роутов нет.

---

### 2.4. Env / App settings — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/admin/settings/env` | Список env-переменных (key, value, category, description) |
| GET | `/admin/settings/app` | Настройки приложения (use_nano_banana_pro и т.п.) |
| PUT | `/admin/settings/app` | Обновление |

**Бэкенд:** Есть `AppSettingsService`, модель `AppSettings`. Роутов нет. Для env — обычно читают из `os.environ` или конфига (без записи в БД).

---

### 2.5. Users — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/admin/users` | Список пользователей (page, page_size, search) |
| GET | `/admin/users/analytics` | Аналитика (time_window) |

**Бэкенд:** Есть `UserService`, модель `User`. Роутов нет.

---

### 2.6. Telegram messages — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET  | `/admin/telegram-messages` | Список шаблонов сообщений |
| POST | `/admin/telegram-messages/bulk` | Массовое обновление (items: { key, value }[]) |
| POST | `/admin/telegram-messages/reset` | Сброс к дефолтам |

**Бэкенд:** Есть `TelegramMessageTemplateService`, модель `TelegramMessageTemplate`, дефолты. Роутов нет.

---

### 2.7. Telemetry — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/admin/telemetry` | Дашборд (window_hours) |
| GET | `/admin/telemetry/trends` | Аналитика по трендам |
| GET | `/admin/telemetry/history` | История (window_days) |
| GET | `/admin/telemetry/product-metrics` | Продуктовые метрики (window_days) |

**Бэкенд:** Нет ни роутов, ни выделенного сервиса телеметрии. Данные можно собирать из `AuditLog`, `Job`, `Payment` и т.д.

---

### 2.8. Bank transfer — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/admin/bank-transfer/settings` | Настройки перевода (карта, комментарий, star_to_rub, промпты, толерансы, пакеты для кнопок) |
| PUT | `/admin/bank-transfer/settings` | Обновление |
| GET | `/admin/bank-transfer/receipt-logs` | Логи чеков (page, page_size, match_success, telegram_user_id) |
| GET | `/admin/bank-transfer/receipt-logs/:id/file` | Файл (blob) по логу |

**Бэкенд:** Есть `BankTransferSettingsService`, модели `BankTransferSettings`, `BankTransferReceiptLog`. Роутов нет.

---

### 2.9. Payments / Packs — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET    | `/admin/payments` | Список платежей (page, page_size, payment_method) |
| GET    | `/admin/payments/stats` | Статистика (days) |
| POST   | `/admin/payments/:id/refund` | Рефанд |
| GET    | `/admin/packs` | Список пакетов |
| PUT    | `/admin/packs/:id` | Обновление пакета |
| POST   | `/admin/packs` | Создание пакета |
| DELETE | `/admin/packs/:id` | Удаление пакета |

**Бэкенд:** Есть `PaymentService` (list, refund, stats по платежам; CRUD по пакам). Роутов нет.

---

### 2.10. Trends (админские) — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/admin/trends` | Список всех трендов (в т.ч. выключенных), с полями для админки |
| GET | `/admin/trends/:id` | Один тренд по id (полная модель: scene_prompt, style_preset, prompt_sections и т.д.) |

**Бэкенд:** Есть только публичный `GET /trends` (только активные, упрощённая схема). Есть `TrendService.list_all()`, `TrendService.get()`. Админских роутов нет.

---

### 2.11. Audit — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/admin/audit` | Список записей (action, page, page_size) |
| GET | `/admin/audit/stats` | Агрегаты по actor_type (window_hours) |

**Бэкенд:** Есть `AuditService` только с методом `log()`. Нет методов `list()` и `get_stats()` и нет роутов.

---

### 2.12. Broadcast — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET  | `/admin/broadcast/preview` | Количество получателей (include_blocked) |
| POST | `/admin/broadcast/send` | Отправить рассылку (message, include_blocked) |

**Бэкенд:** Есть воркер `app.workers.tasks.broadcast`. Роутов для запуска/превью нет.

---

### 2.13. Jobs — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/admin/jobs` | Список джоб (page, page_size, status, telegram_id) |
| GET | `/admin/jobs/:id` | Одна джоба по id |

**Бэкенд:** Есть `JobService`, модель `Job`. Роутов нет.

---

### 2.14. Copy style settings — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/admin/settings/copy-style` | Настройки «Сделать такую же» |
| PUT | `/admin/settings/copy-style` | Обновление |

**Бэкенд:** Есть `CopyStyleSettingsService`, модель `CopyStyleSettings`. Роутов нет.

---

### 2.15. Cleanup — нет на основном API

| Метод | Путь | Назначение |
|-------|------|------------|
| GET  | `/admin/cleanup/preview` | Превью (older_than_hours → jobs_count, files_count) |
| POST | `/admin/cleanup/run` | Запуск очистки (older_than_hours) |

**Бэкенд:** Отдельный сервис cleanup на порту **8001**: `POST /cleanup/run`, своего `/cleanup/preview` нет. На основном API (8000) нет ни прокси, ни своих `/admin/cleanup/*`. Логика есть в `CleanupService` (preview_temp_cleanup, cleanup_temp_files).

**Варианты:** либо добавить на основной API роуты `/admin/cleanup/preview` и `/admin/cleanup/run` (вызов `CleanupService` или HTTP-прокси на cleanup:8001), либо фронту вызывать другой baseURL для cleanup.

---

### 2.16. Playground — нет

| Метод | Путь | Назначение |
|-------|------|------------|
| GET  | `/admin/playground/config` | Дефолтный конфиг промпта (модель, temperature, format, sections, variables) |
| GET  | `/admin/playground/logs/stream` | SSE-стрим логов |
| GET  | `/admin/trends/:id` | Загрузка тренда в Playground (уже учтено в Trends) |
| PUT  | `/admin/playground/trends/:id` | Сохранить конфиг Playground в тренд |
| POST | `/admin/playground/test` | Тест промпта (multipart: config, image1, image2) → image_url / error |

**Бэкенд:** В `app/` нет ни роутов, ни отдельного приложения Playground. В `PLAYGROUND_SUMMARY_RU.md` описан только фронт и сценарии; бэкенд для конфига, стрима логов и теста промпта не реализован.

---

## 3. Старая админка (admin-ui, Jinja2)

Она дергает те же API через `_api_url()` (основной хост 8000):

- `/admin/telemetry`, `/admin/cleanup`, `/admin/prompts`, `/admin/prompts/:name`, `/admin/trend-prompts`, `/admin/trends/:id`, `/admin/users/:telegram_id`, `/admin/jobs/:id`

То есть без реализации перечисленных выше эндпоинтов и старая админка будет получать 404 при любом обращении к API (кроме auth).

---

## 4. Промпты и trend-prompts

Фронт и старая админка ожидают:

- `GET/PUT /admin/prompts` и `/admin/prompts/:name`
- `GET/PUT /admin/trend-prompts` и `/admin/trend-prompts/:trend_id`

В бэкенде есть сервисы промптов (`app.services.prompts`, `generation_prompt`, модель тренда с полями промптов), но **отдельных HTTP API под эти пути нет**. Их тоже нужно добавить в список недостающих.

---

## 5. Сводная таблица: что есть в сервисах, чего нет в API

| Область | Сервис / модель | Роуты в main API |
|---------|----------------|-------------------|
| Auth | jwt, login_rate_limit | есть `/admin/auth/*` |
| Health | — | есть `/health`, `/ready` |
| Trends (публичные) | TrendService | есть `/trends` |
| Trends (админ) | TrendService | нет `/admin/trends`, `/admin/trends/:id` |
| Security | SecuritySettingsService | нет `/admin/security/*` |
| Transfer policy | transfer_policy.service | нет `/admin/settings/transfer-policy` |
| App settings | AppSettingsService | нет `/admin/settings/app`, env |
| Users | UserService | нет `/admin/users`, `/admin/users/analytics` |
| Telegram messages | TelegramMessageTemplateService | нет `/admin/telegram-messages/*` |
| Telemetry | — | нет сервиса и роутов `/admin/telemetry/*` |
| Bank transfer | BankTransferSettingsService, receipt log | нет `/admin/bank-transfer/*` |
| Payments / Packs | PaymentService | нет `/admin/payments/*`, `/admin/packs/*` |
| Audit | AuditService (только log) | нет list/stats и роутов `/admin/audit/*` |
| Broadcast | workers.tasks.broadcast | нет `/admin/broadcast/*` |
| Jobs | JobService | нет `/admin/jobs/*` |
| Copy style | CopyStyleSettingsService | нет `/admin/settings/copy-style` |
| Cleanup | CleanupService / cleanup:8001 | нет `/admin/cleanup/*` на 8000 |
| Playground | — | нет `/admin/playground/*` |
| Prompts / trend-prompts | prompts, generation_prompt | нет `/admin/prompts/*`, `/admin/trend-prompts/*` |
| Admin UI (HTML) | admin.ui | есть `/admin-ui/*` |
| Metrics | utils.metrics | есть `/metrics` |

---

## 6. Рекомендуемые приоритеты

1. **Критично для запуска стека:** уже сделано — `app/main.py`, health, auth, trends, admin_ui, metrics. Контейнер api поднимается.
2. **Чтобы реакт-админка перестала сыпать 404:**
   - Высокий приоритет: **Trends (админ)** — `/admin/trends`, `/admin/trends/:id` (список всех + один с полной моделью).
   - Затем по важности для страниц: **Packs**, **Payments**, **Users**, **Jobs**, **Security** (settings + overview; ban/suspend — по возможности).
   - Затем: **Audit**, **Bank transfer**, **Telegram messages**, **Copy style**, **Transfer policy**, **App settings**, **Env**.
3. **Cleanup:** добавить на основной API либо прокси на cleanup:8001, либо свои роуты с вызовом `CleanupService` и, при необходимости, один эндпоинт на 8001 для preview (если решите оставить логику там).
4. **Telemetry:** проектировать агрегаты по Job/Payment/AuditLog и добавить роуты `/admin/telemetry`, `/admin/telemetry/trends`, history, product-metrics.
5. **Broadcast:** роуты preview + send, внутри вызывать существующий воркер рассылки.
6. **Playground:** отдельный блок: конфиг, SSE-логи, сохранение в тренд, тест промпта (multipart) — либо отдельный сервис, либо роуты в main API с вызовом генерации/логирования.

После этого можно по одному добавлять роутеры в `app/main.py` и подключать их к уже существующим сервисам.
