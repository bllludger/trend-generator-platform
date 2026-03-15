# Trend Generator (Nano Banana)

Telegram-бот для генерации стилизованных фото по трендам: пользователь загружает фото, выбирает тему и тренд, получает варианты изображений. Монетизация через пакеты (фотосессии) и разблокировку в HD (4K). Платежи: Telegram Stars, ЮKassa, ЮMoney, банковский перевод.

## Что внутри

- **Бот** (aiogram) — Telegram: сценарии «Создать фото», «Сделать такую же», «Соединить фото», магазин, профиль, избранное, доставка HD.
- **API** (FastAPI) — health, тренды, авторизация, админка, webhooks (ЮKassa).
- **Воркеры** (Celery) — генерация изображений, доставка HD, unlock, merge, рассылки.
- **Админка** (React) — пользователи, тренды, платежи, настройки, безопасность, рассылки.

Стек: Python 3.12, PostgreSQL, Redis, Celery, Gemini/OpenAI и др. — см. [docs/TECH_STACK.md](docs/TECH_STACK.md).

## Быстрый старт

1. Клонировать репозиторий, перейти в каталог проекта.
2. Скопировать конфиг: `cp env.example .env` и заполнить обязательные переменные (см. ниже).
3. Запустить сервисы: `./start.sh`
4. Админка: http://localhost:3000 (логин из `ADMIN_*` в `.env`). API: http://localhost:8000. Бот подключается к Telegram по `TELEGRAM_BOT_TOKEN`.

Обязательно в `.env`: `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`. Для генерации: `IMAGE_PROVIDER` и ключ провайдера (например `GEMINI_API_KEY` при `IMAGE_PROVIDER=gemini`). Секреты хранить только в `.env`, не коммитить.

Подробный онбординг: [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md).

## Документация

| Документ | Назначение |
|----------|------------|
| [GETTING_STARTED](docs/GETTING_STARTED.md) | Пошаговый запуск и первый запрос |
| [TECH_STACK](docs/TECH_STACK.md) | Стек и версии |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Схема компонентов и связей |
| [USER_FLOW_TREE](docs/USER_FLOW_TREE.md) | Потоки пользователя (AS-IS) |
| [BUSINESS_AND_PRODUCT_OVERVIEW](docs/BUSINESS_AND_PRODUCT_OVERVIEW.md) | Продукт и монетизация |
| [TROUBLESHOOTING](docs/TROUBLESHOOTING.md) | Типовые проблемы |
| [RUNBOOK](docs/RUNBOOK.md) | Действия при инцидентах |
| [PAYMENTS_OVERVIEW](docs/PAYMENTS_OVERVIEW.md) | Способы оплаты и сценарии |
| [WEBHOOKS](docs/WEBHOOKS.md) | Входящие webhook'и |
| [ADMIN_GUIDE](docs/ADMIN_GUIDE.md) | Как пользоваться админкой |
| [CONTRIBUTING](docs/CONTRIBUTING.md) | Разработка и тесты |
| [SECURITY](docs/SECURITY.md) | Секреты, порты, чек-лист |
| [GLOSSARY](docs/GLOSSARY.md) | Терминология продукта |
| [COMPLIANCE_OR_PRIVACY](docs/COMPLIANCE_OR_PRIVACY.md) | Удаление данных по запросу |

## Остановка

- Обычная остановка: `./stop.sh` (контейнеры останавливаются, данные в volumes сохраняются).
- **Не использовать** `./stop.sh -v` в проде — флаг `-v` удаляет тома с БД и Redis.
