# Мониторинг и метрики

Где смотреть метрики приложения и события телеметрии.

## Prometheus-метрики (API)

Эндпоинт: **`GET /metrics`** (тот же хост и порт, что и API, по умолчанию 8000). Формат Prometheus text. Используется для сбора скрапером (Prometheus/Grafana или аналог).

### Основные метрики (app/utils/metrics.py)

| Метрика | Тип | Описание |
|---------|-----|----------|
| `http_requests_total` | Counter | Запросы к API по method, path, status |
| `http_request_duration_seconds` | Histogram | Длительность HTTP-запросов |
| `api_health_check_failures_total` | Counter | Сбои проверки ready (БД/Redis) |
| `jobs_created_total`, `jobs_succeeded_total`, `jobs_failed_total` | Counter | Джобы по trend_id (и error_code для failed) |
| `takes_created_total`, `takes_completed_total`, `takes_failed_total` | Counter | Take (сессионная генерация) |
| `job_duration_seconds`, `take_generation_duration_seconds` | Histogram | Длительность генерации |
| `image_generation_requests_total`, `image_generation_duration_seconds`, `image_generation_retries_total` | Counter/Histogram | Обращения к провайдеру генерации |
| `generation_failed_total` | Counter | Неуспешные генерации (с лейблами) |
| `pay_initiated_total`, `pay_pre_checkout_rejected_total`, `pay_success_total` | Counter | Воронка оплаты |
| `payment_amount_stars_total`, `payment_processing_errors_total`, `pay_refund_total` | Counter | Платежи и ошибки |
| `favorites_hd_delivery_total`, `hd_delivery_failed_total` | Counter | Доставка HD |
| `celery_queue_length`, `celery_active_tasks` | Gauge | Длина очередей Celery и число активных задач по очередям |
| `telegram_requests_total`, `telegram_request_duration_seconds` | Counter/Histogram | Запросы к Telegram API |
| `telegram_send_failures_total` | Counter | Ошибки отправки в Telegram |
| `admin_api_requests_total`, `admin_grant_pack_total`, `admin_reset_limits_total` | Counter | Запросы админки и действия |
| `product_events_track_total` | Counter | Запись событий телеметрии |
| `circuit_breaker_state` | Gauge | Состояние circuit breaker по имени (0=closed, 1=open) |

### Где смотреть

- Локально: `curl http://localhost:8000/metrics`.
- В проде: настроить Prometheus scrape на `http://api:8000/metrics` (или внешний URL API) и дашборды в Grafana. Старые примеры дашбордов — в `docs/olds/` (MONITORING_GRAFANA, METRICS_PROMETHEUS_GRAFANA); актуальный список метрик — в коде `app/utils/metrics.py`.

---

## Телеметрия (события продукта)

События пишутся в таблицу **`product_events`** через `ProductAnalyticsService.track()`. Используются для воронок, аналитики и отчётов в админке (например «Нажата оплата», «Выбор варианта»).

### Справочник событий

Полный каталог кнопок и событий: **[TELEMETRY_EVENT_CATALOG.md](TELEMETRY_EVENT_CATALOG.md)**.

Примеры: `pay_initiated`, `favorite_selected`, `theme_selected`, `trend_selected`, команды бота (`/help`, `/trends` и т.д.) с `button_id`.

### Где смотреть

- Админка: разделы с аналитикой/воронками (если реализованы) читают из `product_events`.
- Прямой запрос к БД: `SELECT event_name, COUNT(*), MAX(timestamp) FROM product_events GROUP BY event_name;` (см. также [TROUBLESHOOTING_PAY_INITIATED_ZERO.md](TROUBLESHOOTING_PAY_INITIATED_ZERO.md) при нулях в воронке).

---

## Аудит (audit_log)

Действия админов и системы пишутся в **`audit_logs`** (AuditService): actor_type, action, entity_type, entity_id, payload. Просмотр — страница «Аудит» в админке.

---

## Рекомендации

- Настроить алерты на: рост `api_health_check_failures_total`, рост `generation_failed_total` или `payment_processing_errors_total`, падение `celery_active_tasks` при длинной очереди (воркер упал).
- При инциденте с платежами сверять метрики `pay_initiated_total` / `pay_success_total` и логи webhook'ов ЮKassa; при доставке unlock — логи воркера и `hd_delivery_failed_total`.
