# Полный аудит проекта ai_slop_2 (Trend Generator)

**Дата:** 2026-02-03  
**Цель:** Проверка конфигурации, БД, API, бота, воркера, админки и скриптов — всё ли работает корректно.

---

## 1. Архитектура и конфигурация

### 1.1 Сервисы (docker-compose)

| Сервис    | Порт  | Зависимости | Статус |
|-----------|-------|-------------|--------|
| admin-ui  | 3000  | api (healthy) | ✅ |
| api       | 8000  | db, redis   | ✅ |
| worker    | —     | db, redis   | ✅ |
| bot       | —     | db, redis   | ✅ |
| cleanup   | 8001  | db          | ✅ |
| db        | 5432  | —           | ✅ |
| redis     | 6379  | —           | ✅ |

- Все сервисы используют один `.env`. Одна база `trends`, один Redis (разные DB: 0 — приложение, 1 — Celery broker, 2 — Celery results). Всё согласовано.

### 1.2 Конфиг приложения (app/core/config.py)

- **database_url** — обязательный, без дефолта ✅  
- **redis_url**, **celery_broker_url**, **celery_result_backend** — обязательные ✅  
- **admin_ui_session_secret** — валидация ≥16 символов, запрет слабых значений ✅  
- **admin_ui_password** — запрет admin/password/123456/changeme ✅  
- **Config**: `extra = "ignore"` — лишние переменные из .env не ломают приложение ✅  

### 1.3 Зависимости (requirements.txt)

- FastAPI, Uvicorn, SQLAlchemy, psycopg2, Redis, Celery, aiogram, pydantic-settings, httpx, JWT, passlib — версии зафиксированы. Критичных уязвимостей по списку не видно; при деплое стоит периодически проверять `pip audit`.

---

## 2. База данных

### 2.1 Подключение

- **Единая точка:** `app/db/session.py` — `create_engine(settings.database_url)`, один `SessionLocal`.
- API, бот, воркер, cleanup используют один и тот же `SessionLocal` / `get_db` → одна БД `trends` ✅  

### 2.2 Миграции

- **schema.sql** — создание таблиц: users, trends, jobs, token_ledger, audit_logs (IF NOT EXISTS) ✅  
- **002–016** — последовательные миграции (telemetry, security, copy_style, generation_prompt и т.д.). В `start.sh` применяются по порядку после schema.sql ✅  
- **Сид трендов:** `001_trends.sql` выполняется только если `SELECT COUNT(*) FROM trends` вернул 0 (при ошибке запроса считается 0 и сид выполняется). Перезапуск не затирает правки админки ✅  

### 2.3 Создание БД при первом запуске

- В `start.sh` после ожидания PostgreSQL: если базы `trends` нет — создаётся (`CREATE DATABASE trends`), при необходимости создаётся пользователь `trends`. Это устраняет ошибку `database "trends" does not exist` при старом томе с другой конфигурацией ✅  

### 2.4 Роль postgres для IDE/pgAdmin

- В `start.sh` и в `scripts/fix_postgres_role.sh` задаётся пароль для роли `postgres` и права на БД `trends`. Уменьшает количество FATAL в логах при подключении внешних клиентов ✅  

---

## 3. API

### 3.1 Роуты (app/main.py)

- **health** — без префикса: `/health`, `/ready` ✅  
- **trends** — префикс `/trends` ✅  
- **auth** — префикс `/admin/auth` (логин, логаут, me) ✅  
- **admin** — префикс `/admin` (все админ-эндпоинты) ✅  
- **admin_ui** — префикс `/admin-ui` (старые HTML-шаблоны, если используются) ✅  
- **metrics** — для Prometheus ✅  

### 3.2 Порядок маршрутов admin (важно для FastAPI)

- **GET /admin/users/analytics** и **GET /admin/users** объявлены выше **GET /admin/users/{telegram_id}**. Иначе запрос к `/admin/users/analytics` обрабатывался бы как запрос пользователя с `telegram_id="analytics"` и возвращал 404. Сейчас порядок корректный ✅  

### 3.3 Health и Ready

- `/health` — всегда 200 (liveness).  
- `/ready` — проверка БД и Redis; при ошибке 503. Используется в healthcheck docker-compose ✅  

### 3.4 CORS

- `allow_credentials=True`, список origins из `cors_origins` или дефолт (localhost:3000, 45.14.245.43:3000, admin-ui и т.д.). Для админки с другого хоста/порта нужно добавить origin в .env ✅  

---

## 4. Бот

### 4.1 Подключение к БД и Redis

- Бот использует `SessionLocal` и `get_db_session()` из `app.db.session` — та же БД ✅  
- FSM storage — Redis (`settings.redis_url`). Отдельный ключ/DB от Celery не конфликтуют ✅  

### 4.2 Тренды

- Тренды берутся из БД через `TrendService` (таблица `trends`). Нет отдельного кэша; список в боте совпадает с тем, что в API/админке ✅  

### 4.3 Безопасность

- `SecurityMiddleware`: проверка бана, суспенда, rate limit по пользователю в БД ✅  

---

## 5. Воркер (Celery)

### 5.1 Конфигурация

- `app.core.celery_app`: broker и backend из настроек (Redis DB 1 и 2). Подключение единое ✅  
- Включены таски: `app.workers.tasks.generation`, `app.workers.tasks.broadcast` ✅  
- `task_acks_late=True`, `worker_prefetch_multiplier=1` — подходящие настройки для надёжной обработки ✅  

### 5.2 Работа с БД

- Воркер использует `SessionLocal` и сервисы (JobService, UserService, TrendService и т.д.) — та же БД ✅  

### 5.3 Предупреждение в логах

- Celery выводит SecurityWarning при запуске от root (uid=0). На работу не влияет; для продакшена можно запускать воркер от непривилегированного пользователя (--uid) ✅  

---

## 6. Админка (React)

### 6.1 API Base URL

- В рантайме используется `import.meta.env.VITE_API_BASE` (в Vite переменные вшиваются при сборке).  
- В docker-compose для admin-ui задано `VITE_API_BASE=http://45.14.245.43:8000` — это передаётся только если сборка образа делается через compose (build args). В текущем Dockerfile админки переменная не прокидывается в `npm run build`, поэтому фактически берётся из `admin-frontend/.env` при сборке. Если IP/порт API меняются — нужна пересборка образа админки ✅/⚠️  

### 6.2 Авторизация

- Логин через `/admin/auth/login`, JWT в `Authorization: Bearer <token>`, `withCredentials: true`. При 401 токен сбрасывается и редирект на логин ✅  

### 6.3 Эндпоинты

- Все вызовы в `admin-frontend/src/services/api.ts` соответствуют роутам бэкенда (`/admin/users`, `/admin/users/analytics`, `/admin/trends`, `/admin/jobs`, `/admin/audit`, телеметрия, security, settings и т.д.). После исправления порядка маршрутов `/admin/users/analytics` отдаёт 200 ✅  

---

## 7. Скрипты

### 7.1 start.sh

- Проверка .env, Docker, портов 3000/8000/8001/5432/6379.  
- Запуск db + redis, ожидание pg_isready, создание БД `trends` при необходимости, применение schema + миграций 002–016, сид трендов (только при пустой таблице), настройка роли postgres, затем `up -d` всех сервисов. Логика корректна ✅  
- Количество контейнеров для проверки «уже запущено» — 7. Совпадает с числом сервисов в docker-compose ✅  

### 7.2 stop.sh

- Без флагов — только остановка контейнеров, данные не удаляются.  
- `-v` / `--volumes` — удаление volumes (потеря данных БД). Явно описано в справке ✅  

### 7.3 restart.sh

- Вызывает `./stop.sh` без `-v`, затем `./start.sh`. Volumes не удаляются ✅  

### 7.4 data/generated_images

- В docker-compose смонтирован каталог `./data/generated_images` в контейнеры api, worker, bot, cleanup. Каталог создаётся Docker при первом запуске, если его не было. Отдельное создание в start.sh не обязательно ✅  

---

## 8. Безопасность

### 8.1 Секреты

- `.env` в `.gitignore` — не коммитится ✅  
- В репозитории нет `env.example` — при новом деплое конфиг нужно восстанавливать вручную или из безопасного хранилища. Рекомендуется добавить `env.example` без секретов (пустые значения или плейсхолдеры) ⚠️  

### 8.2 Админ API

- Защита по `X-Admin-Key` и/или JWT. Для вызовов из браузера используется JWT после логина ✅  

### 8.3 Cleanup

- Эндпоинт `/cleanup/run` защищён `require_admin` (X-Admin-Key). API вызывает cleanup по внутреннему URL (cleanup:8001) с заголовком ✅  

---

## 9. Известные ограничения и риски

1. **Жёсткий IP в конфиге админки**  
   `VITE_API_BASE=http://45.14.245.43:8000` зашит в docker-compose и, при сборке из контекста admin-frontend, в образ. При смене IP/домена нужна пересборка образа админки и при необходимости правка `.env` админки.

2. **Один том PostgreSQL**  
   При `./stop.sh -v` или пересоздании тома все данные БД теряются. Рекомендуется регулярный бэкап:  
   `docker compose exec -T db pg_dump -U trends trends > backup_$(date +%Y%m%d).sql`

3. **Redis без пароля**  
   В .env указан `redis://redis:6379/0` без AUTH. В изолированной сети допустимо; при доступе к Redis снаружи лучше включить пароль.

4. **Нет env.example**  
   Добавить в корень репозитория `env.example` с перечислением переменных без реальных секретов — упростит деплой и аудит.

---

## 10. Сводка: что в порядке, что улучшить

### Работает корректно

- Одна БД, один Redis; все сервисы используют их согласованно.  
- Создание БД `trends` при первом запуске; сид трендов только при пустой таблице.  
- Порядок маршрутов API: `/admin/users/analytics` и `/admin/users` выше `/admin/users/{telegram_id}`.  
- Health/ready, CORS, JWT и X-Admin-Key настроены.  
- Бот и воркер читают/пишут в ту же БД; тренды в боте и в админке из одной таблицы.  
- Скрипты start/stop/restart и миграции применяются последовательно и предсказуемо.

### Рекомендации

1. Добавить **env.example** (список переменных без секретов).  
2. По возможности не хардкодить IP в образе админки (build-arg для VITE_API_BASE при сборке).  
3. Настроить **регулярный бэкап БД** (cron + pg_dump).  
4. При необходимости — включить **пароль для Redis** и обновить URL в .env.

После выполнения этих пунктов конфигурация будет ещё более предсказуемой и устойчивой к смене окружения и потере данных.
