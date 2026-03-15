# Мониторинг: Grafana и Prometheus

Краткая инструкция по запуску и доступу к Grafana и Prometheus.

## Запуск

Сервисы мониторинга поднимаются вместе со стеком:

```bash
docker compose up -d
```

Будут запущены:

- **Prometheus** — сбор метрик с API, **bot** (порт 8002), **worker** (порт 9091) и экспортеров (node, redis, postgres).
- **Grafana** — веб-интерфейс для дашбордов и алертов.
- **node_exporter** — метрики хоста (CPU, память, диск).
- **redis_exporter** — метрики Redis.
- **postgres_exporter** — метрики PostgreSQL.

Метрики приложения: API отдаёт `/metrics` на порту 8000; бот и воркер поднимают в процессе простой HTTP‑сервер для `/metrics` (bot:8002, worker:9091), чтобы Prometheus мог скрейпить платёжные, воронку, генерацию и Telegram‑метрики.

## Доступ

| Сервис     | URL (с вашей машины)        | Логин / примечание |
|-----------|-----------------------------|---------------------|
| **Grafana**   | `http://<IP_VPS>:3001` или `http://localhost:3001` | Логин и пароль из `.env`: `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`. По умолчанию `admin` / `admin` (смените в проде). |
| **Prometheus**| `http://<IP_VPS>:9090` или `http://localhost:9090` | Без логина (только чтение метрик). |

На VPS порты 3001 и 9090 проброшены на все интерфейсы — доступ по IP сервера из браузера. Для доступа только через SSH используйте туннель: `ssh -L 3001:127.0.0.1:3001 -L 9090:127.0.0.1:9090 user@<IP_VPS>` и открывайте `http://localhost:3001` и `http://localhost:9090` локально.

## Первая настройка Grafana

1. Откройте Grafana в браузере, войдите (admin / пароль из `.env`).
2. **Data source:** Configuration → Data sources → Add data source → Prometheus.  
   URL: `http://prometheus:9090`. Save & test.
3. **Дашборды:** можно импортировать по ID (например Node Exporter Full — 1860, Redis — 763, Postgres — 9628) или создать свои на основе метрик приложения (см. [METRICS_PROMETHEUS_GRAFANA.md](METRICS_PROMETHEUS_GRAFANA.md)).

## Переменные окружения

В `.env` (по образцу из `env.example`):

- `GRAFANA_ADMIN_USER` — логин администратора Grafana (по умолчанию `admin`).
- `GRAFANA_ADMIN_PASSWORD` — пароль (в проде задайте свой).
- `GRAFANA_SERVER_ROOT_URL` — опционально, корневой URL при доступе через reverse proxy (например `https://grafana.example.com`).

## Дашборды

- **Готовые (импорт по ID):** В Grafana → Dashboards → Import → введите ID:
  - **1860** — Node Exporter Full (CPU, память, диск).
  - **763** — Redis Dashboard.
  - **9628** — Postgres.
- **Приложение:** создайте дашборд вручную и добавьте панели по метрикам из [METRICS_PROMETHEUS_GRAFANA.md](METRICS_PROMETHEUS_GRAFANA.md). Примеры запросов:
  - HTTP RPS: `sum(rate(http_requests_total[5m])) by (path, status)`.
  - Очередь: `celery_queue_length`.
  - Генерация: `rate(jobs_succeeded_total[5m])`, `rate(takes_completed_total[5m])`, `rate(generation_failed_total[5m])`.
  - Платежи: `rate(pay_success_total[5m])`, `rate(pay_pre_checkout_rejected_total[5m])`.
  - Воронка: `rate(bot_started_total[5m])`, `rate(favorite_selected_total[5m])`, `rate(paywall_viewed_total[5m])`.
- Готовые JSON дашборды приложения (импорт вручную):
  - **Полный обзор** — [monitoring/dashboards/trend-generator-full.json](monitoring/dashboards/trend-generator-full.json): инфра (Node/Redis/Postgres), API, очереди, генерация, платежи, воронка, ошибки, Telegram и админка.
  - **Краткий обзор** — [monitoring/dashboards/app-overview.json](monitoring/dashboards/app-overview.json).

## Критичные алерты (настроить первыми)

1. **Инфра:** `node_memory_MemAvailable_bytes` < 200e6 (5m); `node_filesystem_avail_bytes` < 10e9 по mountpoint; скрейп /metrics падает.
2. **Деньги:** `increase(payment_processing_errors_total[5m])` > 0.
3. **Генерация:** `rate(generation_failed_total[5m])` > 0.05; `increase(favorites_hd_stuck_rendering_reset_total[1h])` > 0; `celery_queue_length{queue="generation"}` > 100.
4. **Тихие сбои:** `rate(product_events_track_total{status="db_error"}[5m])` > 0; `circuit_breaker_state` == 1.
5. **Telegram:** доля `telegram_requests_total{status="error"}` > 5% за 10m.

## Безопасность

- В проде ограничьте доступ к портам 3001 и 9090 фаерволом (только ваш IP или VPN) или вынесите Grafana и при необходимости Prometheus за reverse proxy с HTTPS и авторизацией.
- Пароль Grafana и пароль БД не коммитьте; храните в `.env` на сервере.
