# Пошаговый запуск

Онбординг для локальной разработки и первого запуска бота и админки.

## 1. Требования

- Docker и Docker Compose (или `docker compose` v2)
- Git

## 2. Клонирование и каталог

```bash
git clone <url-репозитория> ai_slop_2
cd ai_slop_2
```

## 3. Конфигурация

Скопируйте пример окружения и отредактируйте:

```bash
cp env.example .env
```

Минимальный набор для «запустить бота и админку»:

| Переменная | Описание |
|------------|----------|
| `POSTGRES_PASSWORD` | Пароль БД (совпадает с паролем в `DATABASE_URL`) |
| `DATABASE_URL` | `postgresql+psycopg2://trends:<пароль>@db:5432/trends` |
| `REDIS_URL` | `redis://: пароль@redis:6379/0` (пароль из `REDIS_PASSWORD`) |
| `REDIS_PASSWORD` | Пароль Redis |
| `CELERY_BROKER_URL` | Обычно `redis://: пароль@redis:6379/1` |
| `CELERY_RESULT_BACKEND` | Обычно `redis://: пароль@redis:6379/2` |
| `TELEGRAM_BOT_TOKEN` | Токен бота от @BotFather |
| `TELEGRAM_BOT_USERNAME` | Username бота без @ (для deep link) |
| `IMAGE_PROVIDER` | Например `gemini` |
| `GEMINI_API_KEY` | Обязательно при `IMAGE_PROVIDER=gemini` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Логин и пароль админки |

Полный справочник переменных — в [env.example](../env.example) в корне проекта. Секреты хранить только в `.env`, не коммитить.

## 4. Запуск сервисов

Из корня проекта:

```bash
./start.sh
```

Поднимаются: PostgreSQL, Redis, API, воркер Celery, Beat, бот, админка (admin-ui), при необходимости cleanup. Порты: API 8000 (внутри сети), админка 3000.

Проверка здоровья API:

```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl http://localhost:8000/ready
# {"status":"ready"} при доступных БД и Redis
```

## 5. Первый запрос к API

- Тренды (публичный эндпоинт): `GET http://localhost:8000/trends/` (или см. роуты в `app/api/routes/trends.py`).
- Админка: открыть http://localhost:3000, войти с `ADMIN_USERNAME` / `ADMIN_PASSWORD`.

## 6. Проверка бота

В Telegram найти бота по username и отправить `/start`. Если задан `SUBSCRIPTION_CHANNEL_USERNAME`, потребуется подписка на канал. После этого доступно меню «Создать фото» и остальные сценарии.

## 7. Если что-то не поднимается

- Убедитесь, что база `trends` и пользователь созданы (обычно делается при первом запуске контейнеров).
- Логи: `docker compose logs api`, `docker compose logs worker`, `docker compose logs bot`.
- Типовые проблемы (пустая БД, сиды, Gemini): [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
- Архитектура и компоненты: [ARCHITECTURE.md](ARCHITECTURE.md), [TECH_STACK.md](TECH_STACK.md).
