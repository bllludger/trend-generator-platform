# Технологический стек сервиса

Полный перечень технологий проекта и их назначение.

---

## Backend (API и бот)

| Технология | Версия | Назначение |
|------------|--------|------------|
| **Python** | 3.12 | Язык бэкенда (API, воркеры, бот, cleanup). |
| **FastAPI** | 0.115.x | Веб-фреймворк: REST API, роуты health/auth/trends/admin/webhooks, CORS, lifespan. |
| **Uvicorn** | 0.30.x | ASGI-сервер для FastAPI (основной API и отдельный cleanup на порту 8001). |
| **Pydantic** / **pydantic-settings** | 2.9 / 2.5 | Валидация данных и загрузка конфигурации из переменных окружения. |
| **SQLAlchemy** | 2.0.x | ORM: модели, сессии, миграции (через Alembic). |
| **psycopg2-binary** | 2.9.x | Драйвер PostgreSQL для SQLAlchemy. |
| **Alembic** | 1.13.x | Миграции схемы БД (файлы в `migrations/`). |
| **Redis** (клиент) | 5.2.x | Очереди Celery (broker/backend), FSM бота (aiogram RedisStorage), кэш, идемпотентность. |
| **Celery** | 5.4.x | Очереди задач: генерация изображений, доставка HD, merge, watchdog, реферальные бонусы, рассылки. |
| **aiogram** | 3.17.x | Telegram-бот: хендлеры, FSM, клавиатуры, оплата (Stars/инвойсы), RedisStorage для состояний. |
| **OpenAI** (SDK) | ≥1.55 | Провайдер генерации изображений (DALL·E 2/3) и анализа референсов (GPT-4o Vision) при `IMAGE_PROVIDER=openai`. |
| **httpx** | 0.27.x | HTTP-клиент: вызовы внешних API (Hugging Face, Replicate, YooKassa, Vertex/Gemini при необходимости). |
| **python-multipart** | 0.0.x | Парсинг multipart/form-data (загрузка файлов в API). |
| **PyYAML** | 6.0.x | Чтение конфигов и промптов (YAML в `prompts/`). |
| **Jinja2** | 3.1.x | Шаблонизация текстов (сообщения бота, промпты). |
| **Pillow** | ≥10.4 | Обработка изображений: вотермарки, ресайз, форматы (PNG/JPEG). |
| **prometheus-client** | 0.21.x | Метрики приложения: счётчики/гистограммы генерации, HTTP, экспорт `/metrics`. |
| **pybreaker** | 1.2.x | Circuit breaker для внешних сервисов (снижение нагрузки при сбоях). |
| **itsdangerous** | 2.2.x | Подпись/сериализация (сессии, токены). |
| **fastapi-sessions** | 0.3.x | Сессии админ-UI (cookie-based). |
| **python-jose** (JWT) | 3.3.x | JWT для авторизации админки (опционально). |
| **passlib[bcrypt]** | 1.7.x | Хеширование паролей админки (bcrypt). |
| **python-dotenv** | 1.0.x | Загрузка `.env` в локальной разработке. |

---

## База данных и кэш

| Технология | Версия | Назначение |
|------------|--------|------------|
| **PostgreSQL** | 16 | Основная БД: пользователи, джобы, тренды, платежи, заказы разблокировки/паков, настройки, рефералы. |
| **Redis** | 7 | Брокер/бэкенд Celery, FSM бота (aiogram), кэш, идемпотентность; AOF для персистентности. |

---

## Очереди и фоновые задачи (Celery)

| Компонент | Назначение |
|-----------|------------|
| **Celery Worker** | Очереди `celery` и `generation`: генерация трендов, merge фото, доставка HD, unlock, рассылки, удаление данных. |
| **Celery Beat** | Периодические задачи: реферальные бонусы (каждые 30 мин), watchdog рендеринга (каждые 5 мин), детекция дропов коллекций (каждые 6 ч). |

---

## Генерация изображений (провайдеры)

Поддерживаются несколько провайдеров (выбор через `IMAGE_PROVIDER`):

| Провайдер | Назначение |
|-----------|------------|
| **OpenAI** | DALL·E 2/3, GPT-4o Vision для анализа референса («сделать такую же»). |
| **Hugging Face** | FLUX / Stable Diffusion через API inference. |
| **Replicate** | FLUX-schnell и др. модели через Replicate API. |
| **Google Vertex AI** | Imagen 3 (imagen-3.0-fast-generate-001). |
| **Google Gemini** | gemini-2.5-flash-image (и др.) — основной вариант в `env.example`. |

Общая обвязка: retry, классификация ошибок, метрики Prometheus — в `app/services/image_generation/runner.py`.

---

## Платежи и монетизация

| Технология / сервис | Назначение |
|---------------------|------------|
| **Telegram Stars** | Нативная оплата в боте (sendInvoice), провайдер — ЮKassa (TELEGRAM_PAYMENT_PROVIDER_TOKEN). |
| **ЮKassa (YooKassa)** | Платежи по ссылке (разблокировка, пакеты): создание платежа через API, webhooks для подтверждения. Клиент: `app/services/yookassa/client.py`. |
| **Банковский перевод** | Опциональный флоу: реквизиты карты, загрузка чека, распознавание суммы, зачисление (настройки в админке). |

---

## Админка (Frontend)

| Технология | Версия | Назначение |
|------------|--------|------------|
| **Node.js** | 20 | Среда сборки админки (stage build в Docker). |
| **TypeScript** | 5.3.x | Типизация кода админки. |
| **React** | 18.2.x | UI: страницы дашборда, пользователи, джобы, платежи, тренды, настройки и т.д. |
| **Vite** | 5.x | Сборка и dev-сервер (SWC для React). |
| **React Router** | 6.22.x | Маршрутизация SPA. |
| **TanStack React Query** | 5.17.x | Запросы к API, кэш, дебаунс, devtools. |
| **Axios** | 1.6.x | HTTP-клиент к бэкенду. |
| **Zustand** | 4.5.x | Глобальное состояние (например, авторизация/настройки). |
| **Radix UI** | — | Диалоги, селекты, табы, тосты, переключатели и т.д. (доступность, стилизация). |
| **Tailwind CSS** | 3.4.x | Стили, утилитарные классы; tailwindcss-animate для анимаций. |
| **Lucide React** | 0.323.x | Иконки. |
| **Recharts** | 2.12.x | Графики на дашборде (аналитика). |
| **date-fns** | 3.3.x | Работа с датами. |
| **clsx** / **tailwind-merge** / **class-variance-authority** | — | Условные и комбинируемые классы (компоненты UI). |
| **Sonner** | 1.4.x | Тосты/уведомления. |
| **@dnd-kit** | 6.1.x | Drag-and-drop (например, порядок элементов). |
| **ESLint** + **@typescript-eslint** | — | Линтинг и правила для TypeScript/React. |

---

## Доставка админки в проде

| Технология | Назначение |
|------------|------------|
| **Nginx** (Alpine) | Раздача статики собранной админки (production Docker-образ admin-ui). |

---

## Мониторинг и метрики

| Технология | Версия | Назначение |
|------------|--------|------------|
| **Prometheus** | 2.47 | Сбор метрик с API (`/metrics`), node_exporter, redis_exporter, postgres_exporter. |
| **Grafana** | 10.2 | Дашборды и алерты по метрикам приложения и инфраструктуры. |
| **Node Exporter** | 1.6.x | Метрики хоста (CPU, память, диск). |
| **Redis Exporter** | 1.55 | Метрики Redis. |
| **Postgres Exporter** | 0.15 | Метрики PostgreSQL. |
| **prometheus-client** (Python) | — | Экспорт метрик из API (счётчики запросов, длительность, генерация изображений). |

Конфиг Prometheus: `monitoring/prometheus.yml`. Дашборды: `monitoring/dashboards/`.

---

## Инфраструктура и деплой

| Технология | Назначение |
|------------|------------|
| **Docker** | Образы для api, worker, beat, bot, cleanup, admin-ui, db, redis, prometheus, grafana, экспортеры. |
| **Docker Compose** | Оркестрация сервисов, healthchecks, тома (postgres_data, redis_data, prometheus_data, grafana_data). |
| **Bash (start.sh и др.)** | Скрипты запуска/рестарта окружения. |

---

## Вспомогательные сервисы приложения

| Сервис | Назначение |
|--------|------------|
| **API** (порт 8000) | FastAPI: health, auth, trends, playground, admin API, webhooks, раздача админ-UI, `/metrics`. |
| **Cleanup** (порт 8001) | Отдельное FastAPI-приложение: удаление временных файлов завершённых джобов (по вызову с X-Admin-Key). |
| **Bot** | Процесс `python -m app.bot.main`: Telegram-бот на aiogram (long polling или webhook). |
| **Worker** | Celery worker (очереди celery, generation). |
| **Beat** | Celery beat (расписание задач). |

---

## Бэкапы и хранилище

| Технология / способ | Назначение |
|---------------------|------------|
| **scripts/backup.sh** | Дамп PostgreSQL + архив `prompts` и `data/`; опционально загрузка в S3 (`BACKUP_S3_URI`, нужен `aws` CLI). |
| **Локальные тома** | `postgres_data`, `redis_data`, `data/generated_images`, `data/trend_examples`, `prompts` — монтируются в контейнеры. |

---

## Схема потоков асинхронных задач и состояний инфраструктуры

### Очереди Celery

| Очередь | Назначение |
|--------|------------|
| **celery** | Задачи по умолчанию: доставка HD, unlock, merge фото, рассылки, удаление данных, реферальные бонусы (по расписанию). |
| **generation** | Тяжёлые задачи: `generate_take` (3 превью A/B/C), `merge_photos` (склейка). Роут: `generate_take` → `generation`. |

Один Worker слушает обе очереди: `-Q celery,generation`. Результаты задач хранятся в Redis (result backend), TTL 24 ч.

---

### Кто что ставит в очередь

| Инициатор | Задача | Очередь | Когда |
|-----------|--------|---------|--------|
| **Бот** | `generation_v2.generate_image` | celery | Пользователь отправил фото по тренду (один снимок) → создаётся Job → отправка в Telegram по завершении. |
| **Бот** | `generate_take.generate_take` | generation | Выбор тренда + фото → создаётся Take → генерация 3 вариантов A/B/C, превью с вотермарком, потом выбор и HD. |
| **Бот** | `merge_photos.merge_photos` | generation | Пользователь нажал «Соединить фото», загрузил N фото → Job merge → склейка, отправка в чат. |
| **Бот** | `deliver_hd.deliver_hd` | celery | Кнопка «Открыть фото в 4K» / «Забрать 4K» → апскейл оригинала, отправка файла. |
| **Бот** | `deliver_unlock.deliver_unlock_file` | celery | После оплаты разблокировки по ЮKassa (в боте по кнопке) — ставится из webhook или из бота при успешной оплате. |
| **API (webhook)** | `deliver_unlock.deliver_unlock_file` | celery | ЮKassa webhook `payment.succeeded` по unlock_order → mark_paid → постановка доставки файла в Telegram. |
| **Бот** | `delete_user_data.delete_user_data` | celery | Команда `/deletemydata` → удаление файлов пользователя и обнуление путей в БД, уведомление в чат. |
| **Админка (API)** | `send_telegram_to_user.send_telegram_to_user` | celery | Админ отправил сообщение пользователю (например, при активации пакета). |
| **Админка (API)** | `broadcast.broadcast_message` | celery | Массовая рассылка из админки. |
| **Celery Beat** | `process_pending_bonuses` | celery | Каждые 30 мин: реферальные бонусы с истёкшим hold → available, уведомление рефереру. |
| **Celery Beat** | `reset_stuck_rendering` | celery | Каждые 5 мин: сброс Favorite с `hd_status=rendering` старше 10 мин; для коллекций — компенсация по SLA. |
| **Celery Beat** | `detect_collection_drops` | celery | Каждые 6 ч: сессии с playlist, без активности 24 ч → status=abandoned, аудит. |

---

### Поток «Тренд → превью → 4K»

```
Пользователь в боте: выбор тренда + загрузка фото
         │
         ▼
Бот: создаётся Take, send_task("generate_take", [take_id])  ──►  очередь generation
         │
         ▼
Worker: generate_take
  ├── Загрузка тренда, юзера, фото
  ├── Генерация 3 вариантов (A/B/C) через ImageProvider (Gemini/OpenAI/…), сохранение original_no_watermark
  ├── Превью = downscale + вотермарк
  └── Отправка в Telegram (3 фото + кнопки выбора)
         │
Пользователь нажимает «Открыть фото в 4K» по выбранному варианту
         │
         ▼
Бот: send_task("deliver_hd", …)  ──►  очередь celery
         │
         ▼
Worker: deliver_hd — апскейл original_no_watermark, отправка документа в чат, обновление Favorite.hd_status
```

---

### Поток «Один снимок» (Job без Take)

```
Пользователь: один тренд + одно фото (флоу «один снимок»)
         │
         ▼
Бот: создаётся Job, send_task("generation_v2.generate_image", [job_id], {status_chat_id, status_message_id})
         │
         ▼
Worker: generate_image — билд промпта, вызов провайдера, сохранение, редактирование сообщения в Telegram, отправка фото
```

---

### Поток «Оплата по ссылке ЮKassa»

```
Пользователь в боте: «Выбрать и оплатить» (unlock одного фото)  ──►  переход на ЮKassa
         │
ЮKassa: оплата успешна  ──►  POST /webhooks/yookassa  (payment.succeeded)
         │
         ▼
API: UnlockOrderService.mark_paid, PaymentService.record_*, commit
         │
         ▼
API: send_task("deliver_unlock_file", [order_id])  ──►  очередь celery
         │
         ▼
Worker: deliver_unlock_file — загрузка файла по order, отправка документа в Telegram, mark delivered
```

Аналогично для **pack_order**: webhook → mark_paid → process_session_purchase_yookassa_link → mark_completed → отправка поздравления в чат (без отдельной задачи, из webhook).

---

### Поток «Склейка фото»

```
Пользователь: «Соединить фото»  ──►  загрузка 2+ фото  ──►  бот создаёт Job (merge)
         │
         ▼
Бот: send_task("merge_photos", [job_id], queue="generation")
         │
         ▼
Worker: merge_photos — склейка (Pillow и т.д.), отправка результата в Telegram
```

---

### Состояние инфраструктуры (где что хранится)

| Компонент | Хранит | Назначение |
|-----------|--------|------------|
| **PostgreSQL** | Пользователи, сессии, джобы, тренды, Take, Favorite, платежи, unlock_order, pack_order, рефералы, настройки, аудит | Постоянное состояние приложения. |
| **Redis (broker)** | Очередь сообщений Celery (celery, generation) | Доставка задач воркерам. |
| **Redis (result backend)** | Результаты задач Celery (до 24 ч) | Получение result.get(), мониторинг. |
| **Redis (FSM)** | Состояния FSM бота (aiogram RedisStorage) | Текущий шаг диалога, введённые данные (фото, выбор тренда и т.д.). |
| **Redis (идемпотентность)** | Ключи идемпотентности (по TTL) | Защита от дублей при ретраях. |
| **Файловая система (тома)** | Сгенерированные изображения, входные фото, примеры трендов, промпты | Пути в БД; чтение/запись воркерами и API. |
| **API** | Нет долгоживущего состояния | Статус через health/ready и метрики. |
| **Бот** | Только FSM в Redis | Long polling или webhook; рестарт без потери диалога (FSM в Redis). |
| **Worker** | Обрабатывает задачи по одной (prefetch=1), task_track_started=True | Видны «запущенные» задачи в broker/backend. |
| **Beat** | Расписание в коде (crontab) | Только триггер по времени. |

---

### Зависимости сервисов (старт и healthcheck)

```
db (PostgreSQL)  ──►  api, worker, beat, bot, cleanup  (ожидают db healthy)
redis             ──►  api, worker, beat, bot           (ожидают redis healthy)
api               ──►  admin-ui (прокси к API), prometheus (scrape /metrics)
redis             ──►  prometheus (через redis_exporter)
db                ──►  prometheus (через postgres_exporter)
prometheus        ──►  grafana (источник данных)
```

Cleanup не обязателен для основного флоу; вызывается по HTTP (X-Admin-Key) для удаления временных файлов старых джобов.

---

## Краткая схема по слоям

```
[Пользователь]
      │
      ├── Telegram Bot (aiogram) ──► Redis (FSM), PostgreSQL, Celery
      │
      └── Браузер (админка) ──► Nginx (статика) ──► React SPA
                                      │
                                      └── API (FastAPI) ──► PostgreSQL, Redis, Celery
                                                                  │
                                            Celery Worker ◄───────┘
                                                  │
                    ┌─────────────────────────────┼─────────────────────────────┐
                    ▼                             ▼                             ▼
            Генерация изображений          Доставка HD / Unlock          Рефералы, рассылки
            (OpenAI/Gemini/HF/Replicate)   (файлы, сообщения в TG)        (Beat по расписанию)

Мониторинг: API ──► /metrics ◄── Prometheus ◄── Grafana
            Redis/Postgres/Node ──► Exporters ◄── Prometheus
```

Документ составлен по коду и конфигурации репозитория (docker-compose, requirements.txt, package.json, app/core/config.py, env.example, celery_app, workers, webhooks, bot и смежные модули).
