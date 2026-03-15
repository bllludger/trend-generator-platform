# Метрики Prometheus и дашборды Grafana для Nano Banana / Trend Generator

Production-grade observability: стабильность, производительность, очереди, генерации, оплаты, конверсия и критические бизнес-флоу.

---

## 1. Ключевые метрики по категориям

### 1.1 System / Infrastructure

| Metric name | Type | Что измеряет | Зачем важна | Alert | Dashboard |
|-------------|------|--------------|-------------|-------|-----------|
| `node_cpu_seconds_total` | counter | CPU по режимам (user, system, iowait) | Деградация под нагрузкой, iowait при диске | CPU > 90% 5m | Host / System |
| `node_memory_MemAvailable_bytes` | gauge | Свободная память | OOM, swap | Available < 200MB | Host / System |
| `node_filesystem_avail_bytes` | gauge | Свободное место на диске (mountpoint `/data`) | Переполнение outputs/inputs | Avail < 5% или < 10GB | Host / System |
| `redis_connected_clients` | gauge | Число подключений к Redis | Утечки, лимиты | Резкий рост или > 500 | Redis |
| `redis_memory_used_bytes` | gauge | Память Redis | Рост до лимита | Used > 80% maxmemory | Redis |
| `redis_keyspace_hits_total` / `redis_keyspace_misses_total` | counter | Cache hit/miss | Деградация FSM/кеша | Hit rate < 90% при росте | Redis |
| `pg_stat_database_numbackends` | gauge | Активные соединения к БД | Исчерпание пула | NumBackends близко к max_connections | Postgres |
| `pg_stat_database_xact_commit` / `xact_rollback` | counter | Commit/rollback | Здоровье транзакций | Рост rollback rate | Postgres |

**Источники:** node_exporter, redis_exporter, postgres_exporter. Dashboard: один общий «Infrastructure» или отдельные строки в Overview.

---

### 1.2 API / Backend

| Metric name | Type | Что измеряет | Зачем важна | Alert | Dashboard |
|-------------|------|--------------|-------------|-------|-----------|
| `http_requests_total` | counter | Запросы к API по method, path, status | Объём трафика и ошибки | 5xx rate > 1% | API |
| `http_request_duration_seconds` | histogram | Латентность по path (p50, p95, p99) | Деградация API | p99 > 5s для /admin/* | API |
| `api_health_check_failures_total` | counter | Неуспешные /health или /ready | Не готовность к трафику | Любой инкремент | API / SLO |
| `telegram_requests_total` | counter | Запросы к Telegram API по method, status | Ошибки отправки сообщений/фото | status=error rate > 5% | Telegram / Bot |
| `telegram_request_duration_seconds_*` | histogram | Латентность вызовов Telegram | Таймауты, деградация Telegram | p95 > 5s | Telegram / Bot |
| `circuit_breaker_state` | gauge | 0=closed, 1=open по name | Отключение внешних вызовов | state=1 дольше 1m | Reliability |

**Примечание:** `telegram_requests_total` и `telegram_request_duration_seconds` уже есть в [app/utils/metrics.py](app/utils/metrics.py) и пишутся из [app/services/telegram/client.py](app/services/telegram/client.py). Остальное — добавить (middleware для HTTP, health counter).

---

### 1.3 Queues / Workers / Jobs

| Metric name | Type | Что измеряет | Зачем важна | Alert | Dashboard |
|-------------|------|--------------|-------------|-------|-----------|
| `celery_queue_length` | gauge | Длина очереди по queue (celery, generation) | Рост очереди, отставание воркеров | generation > 50 или рост 2x за 15m | Queues |
| `celery_active_tasks` | gauge | Число выполняющихся задач по task_name | Перегрузка воркеров | active generation > concurrency*workers долго | Queues |
| `celery_task_sent_total` | counter | Отправлено задач по task_name, queue | Throughput по типам задач | Резкое падение при ожидаемом трафике | Queues |
| `celery_task_success_total` | counter | Успешно завершено по task_name | Успешный throughput | — | Queues |
| `celery_task_failure_total` | counter | Ошибки по task_name, error_type | Частота сбоев по типам | rate > 0.1/s для generate_take/generate_image | Queues |
| `celery_task_duration_seconds` | histogram | Время выполнения по task_name | Медленные задачи, SLA | p95 generate_take > 120s | Queues / Generation |
| `celery_task_retries_total` | counter | Повторные попытки по task_name | Нестабильность провайдера/инфра | rate растёт | Queues |

**Примечание:** Сейчас в коде нет экспорта метрик из воркеров (только API отдаёт /metrics). Нужен либо экспортер Celery (celery-exporter или свой скрейп Redis/бракера), либо инструментация задач с записью в Pushgateway / отдельный metrics endpoint для воркеров. `queue_length` и `active_jobs` в metrics.py объявлены, но нигде не обновляются; админка считает «очередь» по Job в БД (CREATED+RUNNING за окно), а не по реальной длине очереди Celery.

---

### 1.4 Generation Pipeline

| Metric name | Type | Что измеряет | Зачем важна | Alert | Dashboard |
|-------------|------|--------------|-------------|-------|-----------|
| `takes_created_total` | counter | Take создано (флоу «Создать фото») | Вход в основной флоу | — | Generation |
| `takes_completed_total` | counter | Take в ready/partial_fail (все 3 варианта или часть) | Успешный выход из генерации | rate падает при стабильном created | Generation |
| `takes_failed_total` | counter | Take status=failed | Полный провал снимка | rate или доля растёт | Generation |
| `take_generation_duration_seconds` | histogram | Время от создания Take до take_previews_ready | SLA «фото готовы» | p95 > 90s | Generation |
| `jobs_created_total` | counter | Job создано (перегенерация/legacy) по trend_id | Объём Job-флоу | — | Generation |
| `jobs_succeeded_total` | counter | Job SUCCEEDED по trend_id | Успешные генерации Job | — | Generation |
| `jobs_failed_total` | counter | Job FAILED по trend_id, error_code | Причины провалов (provider, trend_missing) | rate по error_code растёт | Generation |
| `job_duration_seconds` | histogram | Время выполнения задачи generate_image | SLA одной картинки | p95 > 60s | Generation |
| `image_generation_requests_total` | counter | Вызов провайдера (Gemini/OpenAI) по status (ok, retry, fail) | Объём и исход генерации | fail rate > 5% | Generation |
| `image_generation_duration_seconds` | histogram | Время generate_with_retry до ответа | Латенция провайдера | p95 > 45s | Generation |
| `image_generation_retries_total` | counter | Retry по failure_type (rate_limit, safety, timeout) | Частота ретраев и блокировок | rate резко вырос | Generation |
| `favorites_hd_delivery_total` | counter | HD доставлено по outcome (delivered, failed, skipped) | Конверсия «выбрал вариант → получил 4K» | failed rate > 2% | Generation / Conversion |
| `favorites_hd_stuck_rendering_reset_total` | counter | Сброс «залипших» rendering (watchdog) | Silent failure доставки 4K | > 0 за 1h | Generation |

**Примечание:** В коде уже объявлены `jobs_created_total`, `jobs_succeeded_total`, `jobs_failed_total`, `job_duration_seconds` в metrics.py, но **нигде не вызываются** из generation_v2 или generate_take. Их нужно начать инкрементировать/observe в воркерах (при этом метрики должны быть доступны для скрейпа — см. раздел про воркеры). Take-метрики и image_generation_* — добавить; retries сейчас только в логах (runner.py).

---

### 1.5 Payments

| Metric name | Type | Что измеряет | Зачем важна | Alert | Dashboard |
|-------------|------|--------------|-------------|-------|-----------|
| `pay_initiated_total` | counter | Пользователь нажал оплату (pre_checkout или инициация) по pack_id | Вход в воронку оплаты | — | Payments |
| `pay_pre_checkout_rejected_total` | counter | pre_checkout_query отклонён по reason (user_not_found, pack_unavailable, wrong_amount, rate_limit) | Потеря оплат из-за валидации | rate > 0.1/min | Payments |
| `pay_success_total` | counter | Успешная оплата по pack_id, payment_method (stars, yoomoney) | Выручка и конверсия | Резкое падение при стабильном initiated | Payments |
| `payment_amount_stars_total` | counter | Сумма в Stars по pack_id (при pay_success) | Revenue в реальном времени | — | Payments |
| `payment_processing_errors_total` | counter | Ошибка при credit_tokens / process_* (duplicate, db_error) | Потеря денег или двойное начисление | Любой инкремент | Payments |
| `pay_refund_total` | counter | Рефанд по reason (trial_already_used, support) | Возвраты и риски | Рост refund rate | Payments |

**Примечание:** Сейчас платёжные события есть только в product_events и audit_log (БД). Для Prometheus нужно добавить инкременты в боте и в PaymentService при pre_checkout (reject), successful_payment (success, amount), refund и при ошибках обработки.

---

### 1.6 User Flow / Conversion

| Metric name | Type | Что измеряет | Зачем важна | Alert | Dashboard |
|-------------|------|--------------|-------------|-------|-----------|
| `bot_started_total` | counter | /start или первый вход в бота | Вход в продукт | — | Funnel |
| `photo_uploaded_total` | counter | Пользователь отправил фото (сессия/формат) | Вход в генерацию | — | Funnel |
| `take_previews_ready_total` | counter | Take с 3 превью готовы | Успех генерации снимка | rate падает при стабильных uploads | Funnel |
| `favorite_selected_total` | counter | Пользователь выбрал вариант (A/B/C) | Выбор результата | — | Funnel |
| `paywall_viewed_total` | counter | Показан paywall (unlock/пакет) | Переход к оплате | — | Funnel |
| `preview_to_pay_conversion_rate` | gauge | (pay_success / take_previews с paywall) за скользящее окно | Конверсия превью → оплата | Падение на 20%+ за 24h | Funnel / Business |
| `session_start_to_first_result_seconds` | histogram | Время от bot_started до первого favorite_selected по пользователю | UX «до первого результата» | p95 > 300s | Funnel |

**Примечание:** Точные конверсии (preview_to_pay, start_to_result) сейчас считаются в админке из product_events (product-metrics-v2). Для алертинга в реальном времени можно выносить в Prometheus: либо счётчики событий + gauge rate, либо периодический экспорт из БД через отдельный job (exporter).

---

### 1.7 Telemetry / Admin Visibility

| Metric name | Type | Что измеряет | Зачем важна | Alert | Dashboard |
|-------------|------|--------------|-------------|-------|-----------|
| `product_events_track_total` | counter | Вызовы ProductAnalyticsService.track по event_name, status (ok, db_error) | Потеря событий воронки | status=db_error rate > 0 | Telemetry |
| `admin_api_requests_total` | counter | Запросы к /admin/* по path, status | Нагрузка и ошибки админки | 5xx | Admin |
| `telemetry_query_duration_seconds` | histogram | Время ответа GET /admin/telemetry/* | Деградация дашбордов админки | p95 > 10s | Admin |

**Примечание:** product_events сейчас при ошибке только логирует и возвращает None; добавление счётчика product_events_track_total с label status=db_error позволит ловить silent loss событий.

---

### 1.8 Error / Failure Metrics

| Metric name | Type | Что измеряет | Зачем важна | Alert | Dashboard |
|-------------|------|--------------|-------------|-------|-----------|
| `generation_failed_total` | counter | Провал генерации по error_code (trend_missing, generation_failed, unexpected_error), source (take, job) | Причины и частота | rate по error_code > 0.05/s | Errors |
| `balance_rejected_total` | counter | Отказ в списании баланса (недостаточно токенов/HD) | Недоступность контента | Резкий рост | Errors |
| `token_operations_total` | counter | HOLD/CAPTURE/RELEASE по operation | Корректность балансов | Дисбаланс HOLD vs CAPTURE/RELEASE | Errors |
| `telegram_send_failures_total` | counter | Неуспешная отправка сообщения/фото по method | Потеря уведомлений пользователю | rate > 0.01/s | Errors |
| `payment_validation_failures_total` | counter | Ошибка валидации платежа по reason | Отклонённые платежи | — | Payments / Errors |
| `hd_delivery_failed_total` | counter | deliver_hd завершился ошибкой (файл не найден, Telegram error) | Потеря 4K доставки | rate > 0 | Generation |

**Примечание:** `balance_rejected_total` и `token_operations_total` объявлены в metrics.py, но вызовов `metrics.inc_balance_rejected()` / `inc_token_*` в коде не найдено — нужно повесить на места проверки баланса и списания.

---

## 2. Сводка: must-have, раннее обнаружение, деньги/конверсия, чего не хватает

### 2.1 Must-have для запуска в прод

- **System:** `node_memory_MemAvailable_bytes`, `node_filesystem_avail_bytes` (по mountpoint данных), `redis_memory_used_bytes`, `redis_connected_clients`.
- **API:** `http_requests_total` (path, status), `http_request_duration_seconds`, проверка /health (достаточно проверки скрейпа или `api_health_check_failures_total`).
- **Telegram:** уже есть `telegram_requests_total`, `telegram_request_duration_seconds` — алерт на долю status=error.
- **Queues:** реальная длина очереди Celery (generation) и, по возможности, число активных задач.
- **Generation:** хотя бы счётчики `jobs_succeeded_total` / `jobs_failed_total` и `takes_completed_total` / `takes_failed_total` (инкремент в воркерах) + гистограмма длительности одной задачи (job или take).
- **Payments:** `pay_success_total`, `pay_pre_checkout_rejected_total` (хотя бы по reason).
- **Errors:** `generation_failed_total` по error_code; при наличии — `product_events_track_total` с status=db_error.

### 2.2 Метрики раннего обнаружения деградации

- Латентность: `http_request_duration_seconds` (p95/p99), `job_duration_seconds`, `take_generation_duration_seconds`, `telegram_request_duration_seconds`.
- Очередь: рост `celery_queue_length` (generation) и время жизни задач в очереди (если экспортируется).
- Провайдер: `image_generation_retries_total`, `image_generation_duration_seconds` (рост p95).
- Инфра: `redis_keyspace_hits_total`/misses (падение hit rate), `node_cpu_seconds_total` (iowait), доступность диска.
- Тихие сбои: `favorites_hd_stuck_rendering_reset_total`, `product_events_track_total` (status=db_error).

### 2.3 Метрики потери денег или падения конверсии

- `pay_pre_checkout_rejected_total` по reason — рост отказов при валидации.
- `payment_processing_errors_total` — любая ошибка при проведении платежа.
- `pay_success_total` и `payment_amount_stars_total` — резкое падение при стабильном трафике.
- `preview_to_pay_conversion_rate` (или эквивалент из счётчиков) — падение конверсии.
- `favorites_hd_delivery_total` (outcome=failed) — пользователь заплатил за 4K, но доставка не ушла.
- `balance_rejected_total` — рост отказов в списании (недополученная выручка при желании платить).

### 2.4 Чего сейчас нет в коде (кратко)

- **Не пишутся:** все `jobs_*` и `job_duration_seconds` в воркерах; `active_jobs`, `queue_length` (Gauge нигде не set); `openai_*` (провайдер Gemini); `token_operations_total`, `balance_rejected_total` (нет вызовов inc).
- **Нет метрик:** по Take (created/completed/failed, duration); по платежам (pay_initiated, pay_success, reject, amount); по image_generation (requests, duration, retries); по Celery (queue length, task duration, retries); по product_events (track ok/error); по HTTP API (request count, latency); по deliver_hd и stuck rendering.
- **Очередь:** админка считает «queue_length» по Job в БД за окно, а не длину очереди Redis/Celery — для алертов нужен реальный queue length.

---

## 3. Рекомендуемый список метрик Prometheus (имена и типы)

```
# System (node_exporter)
node_cpu_seconds_total
node_memory_MemAvailable_bytes
node_filesystem_avail_bytes
node_filesystem_size_bytes

# Redis (redis_exporter)
redis_connected_clients
redis_memory_used_bytes
redis_keyspace_hits_total
redis_keyspace_misses_total

# Postgres (postgres_exporter)
pg_stat_database_numbackends
pg_stat_database_xact_commit
pg_stat_database_xact_rollback

# API (приложение)
http_requests_total{method,path,status}
http_request_duration_seconds_bucket{path}
api_health_check_failures_total

# Telegram (есть)
telegram_requests_total{method,status}
telegram_request_duration_seconds_*

# Circuit breaker (есть)
circuit_breaker_state{name}

# Queues (приложение или celery-exporter)
celery_queue_length{queue}
celery_active_tasks{task_name}
celery_task_sent_total{task_name,queue}
celery_task_success_total{task_name}
celery_task_failure_total{task_name,error_type}
celery_task_duration_seconds_*
celery_task_retries_total{task_name}

# Generation
takes_created_total
takes_completed_total
takes_failed_total
take_generation_duration_seconds_*
jobs_created_total{trend_id}
jobs_succeeded_total{trend_id}
jobs_failed_total{trend_id,error_code}
job_duration_seconds_*
image_generation_requests_total{provider,status}
image_generation_duration_seconds_*
image_generation_retries_total{failure_type}
favorites_hd_delivery_total{outcome}
favorites_hd_stuck_rendering_reset_total

# Payments
pay_initiated_total{pack_id}
pay_pre_checkout_rejected_total{reason}
pay_success_total{pack_id,payment_method}
payment_amount_stars_total{pack_id}
payment_processing_errors_total{reason}
pay_refund_total{reason}

# User flow / conversion
bot_started_total
photo_uploaded_total
take_previews_ready_total
favorite_selected_total
paywall_viewed_total
preview_to_pay_conversion_rate (gauge или запрос к БД)

# Telemetry
product_events_track_total{event_name,status}

# Errors
generation_failed_total{error_code,source}
balance_rejected_total
token_operations_total{operation}
telegram_send_failures_total{method}
hd_delivery_failed_total
```

---

## 4. Рекомендуемая структура дашбордов Grafana

- **Overview (один экран)**  
  Строки: Host (CPU, memory, disk), Redis (memory, connections, hit rate), Postgres (connections, commit/rollback), API (RPS, latency p95), Queues (generation length, active tasks), Generation (takes/jobs success rate, duration p95), Payments (pay_success rate, reject rate), Critical alerts (circuit breaker, payment errors, product_events db_error).

- **Host / System**  
  Node Exporter: CPU по режимам, memory available, disk по mountpoint, load average. Источник: node_exporter.

- **Redis**  
  Memory used, connected clients, commands/sec, keyspace hit rate. Источник: redis_exporter.

- **Postgres**  
  Connections, transactions commit/rollback, slow queries (если есть). Источник: postgres_exporter.

- **API & Bot**  
  Request rate и latency по path; telegram_requests_total по status; telegram_request_duration_seconds; circuit_breaker_state.

- **Queues & Workers**  
  Длина очереди celery/generation, активные задачи, task_sent/success/failure по task_name, task_duration p50/p95.

- **Generation Pipeline**  
  Takes: created, completed, failed, take_generation_duration. Jobs: created, succeeded, failed по trend_id и error_code, job_duration. Image: requests, retries, duration. HD: delivered/failed, stuck reset.

- **Payments**  
  pay_initiated, pay_success, pay_pre_checkout_rejected по reason, payment_amount_stars, payment_processing_errors, refunds.

- **Funnel & Conversion**  
  Счётчики: bot_started, photo_uploaded, take_previews_ready, favorite_selected, paywall_viewed, pay_success. Gauge/вычисляемая метрика: preview_to_pay за окно (или ссылка на админку product-metrics-v2).

- **Errors & Reliability**  
  generation_failed по error_code, balance_rejected, product_events_track status=db_error, telegram_send_failures, hd_delivery_failed.

---

## 5. Критичные алерты (настроить первыми)

1. **Инфра**  
   - Host: `node_memory_MemAvailable_bytes` < 200e6 на 5m.  
   - Disk: `node_filesystem_avail_bytes` на mountpoint данных < 10e9 или < 5%.  
   - Redis: `redis_memory_used_bytes` > 0.8 * maxmemory (если задан).  
   - API: скрейп /metrics или /health падает 3 раза подряд.

2. **Деньги и конверсия**  
   - `payment_processing_errors_total` увеличился за 5m.  
   - `pay_success_total` rate упал в 2+ раза за 1h при стабильном `pay_initiated_total` (если метрики есть).  
   - Резкое падение конверсии в админке (product-metrics-v2) — можно алертить по порогу через периодический экспорт в Prometheus или отдельный канал.

3. **Генерация и доставка**  
   - `generation_failed_total` rate > 0.05/s по любому error_code на 10m.  
   - `favorites_hd_stuck_rendering_reset_total` > 0 за 1h.  
   - Очередь: `celery_queue_length{queue="generation"}` > 100 или рост в 2 раза за 15m.

4. **Тихие сбои**  
   - `product_events_track_total{status="db_error"}` rate > 0.  
   - `circuit_breaker_state{name="..."}` == 1 дольше 1m.

5. **Внешние зависимости**  
   - Доля `telegram_requests_total{status="error"}` > 5% за 10m.  
   - Рост p95 `telegram_request_duration_seconds` или `image_generation_duration_seconds` выше порога (например 10s и 60s).

---

## Связь с кодом

- Метрики приложения: [app/utils/metrics.py](app/utils/metrics.py) — расширять новыми счётчиками/гистограммами и вызывать из бота, воркеров, PaymentService, ProductAnalyticsService, middleware API.  
- Эндпоинт /metrics: только на API; воркеры не отдают HTTP — для них либо Pushgateway, либо вынос метрик в общий store (например Redis) и экспорт через отдельный sidecar/endpoint.  
- Продуктовая воронка и конверсия: остаются в БД (product_events) и в админке (TelemetryPage, product-metrics-v2); Prometheus дублирует ключевые счётчики и производные для алертов в реальном времени.
