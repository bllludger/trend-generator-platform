# Runbook: действия при инцидентах

Краткий чек-лист для дежурного: как проверить здоровье сервиса и что делать при типовых сбоях.

## 1. Проверка здоровья

### Быстрая проверка

- **API (liveness):** `curl http://localhost:8000/health` — ожидается `{"status":"ok"}`.
- **API (readiness):** `curl http://localhost:8000/ready` — при доступных БД и Redis: `{"status":"ready"}`. При 503 — в ответе `error` с причиной.
- **Логи:** `docker compose logs --tail=100 api worker bot` — ошибки, исключения, 5xx.

### Где смотреть логи

- API: `docker compose logs -f api`
- Воркер (генерация, доставка HD/unlock): `docker compose logs -f worker`
- Бот: `docker compose logs -f bot`
- БД: `docker compose logs -f db`
- Redis: `docker compose logs -f redis`

### Очереди Celery

- Длина очередей и активные задачи экспортируются в Prometheus (см. [MONITORING.md](MONITORING.md)). При необходимости проверить вручную: подключиться к Redis и посмотреть списки ключей очередей `celery` и `generation`, либо использовать Flower (если развёрнут).

---

## 2. Падение или недоступность API

- Проверить `/health` и `/ready`. При 503 по ready — причина в ответе (`error`).
- Типичные причины: БД недоступна (контейнер db не запущен или пароль/хост неверны), Redis недоступен.
- Действия: `docker compose ps` — все ли контейнеры Up; перезапуск: `docker compose restart api`. При потере БД/Redis — проверить volumes (не удалялись ли тома командой с `-v`). Резервное копирование и восстановление — [STABILITY_AND_BACKUPS.md](STABILITY_AND_BACKUPS.md).

---

## 3. Генерация не выполняется или падает с ошибкой

- Логи воркера: `docker compose logs --tail=200 worker` — искать `generation_failed`, `ImageGenerationError`, traceback провайдера (Gemini/OpenAI).
- Типичные причины: неверный/истёкший ключ провайдера (`GEMINI_API_KEY` и т.д.), rate limit провайдера, блокировка контента (Gemini safety). Пояснения от Gemini при ошибке — в [TROUBLESHOOTING.md](TROUBLESHOOTING.md) (finish_message, prompt_feedback).
- Действия: проверить переменные окружения воркера (`IMAGE_PROVIDER`, ключи), при массовых safety-ошибках — проверить промпты/настройки в админке. Отдельные упавшие Take/Job — смотреть в админке (Jobs, аудит) и при необходимости повторить сценарий пользователем.

---

## 4. Платежи: оплата прошла, пакет не активирован / файл не доставлен

### Stars / ЮMoney (успешный платёж в боте)

- Проверить логи бота и API при моменте оплаты: `successful_payment`, ошибки при `process_session_purchase` или `credit_tokens`.
- Админка: пользователь, платежи (payments), сессии (sessions). Если платежа нет — смотреть логи на исключение при записи. Если платёж есть, а сессия не создана — возможна ошибка в `process_session_purchase` (например trial_already_used для ЮMoney — см. ниже).

### ЮKassa: webhook не сработал или заказ «завис»

- Webhook: `POST /webhooks/yookassa`. В логах API искать `yookassa_webhook_received`, `yookassa_webhook_mark_paid_failed`, `yookassa_webhook_deliver_enqueued`, `yookassa_webhook_pack_completed`.
- Всегда возвращаем 200, чтобы ЮKassa не ретраила; при внутренней ошибке заказ может остаться в `payment_pending`. Действия: проверить в БД статус `unlock_orders` / `pack_orders` по `yookassa_payment_id`; при статусе `paid` у ЮKassa и `payment_pending` у нас — вручную обновить статус и поставить задачу доставки (или повторить логику webhook вручную/скриптом). См. [WEBHOOKS.md](WEBHOOKS.md).

### Unlock: файл не пришёл после оплаты по ссылке

- Задача `deliver_unlock.deliver_unlock_file`. Логи воркера: `deliver_unlock_file`, исключения при отправке в Telegram. В БД: `unlock_orders.status` — при `delivery_failed` причина может быть в логах (файл не найден, ошибка send_document). Действия: исправить путь/файл при необходимости; повторная отправка — кнопка «Получить фото снова» у пользователя или ручной вызов доставки (если реализовано в админке/скрипте).

---

## 5. ЮMoney: trial уже использован, деньги списаны

- В логах искать событие `yoomoney_trial_already_used_manual_refund_needed` (telegram_id, amount_kopecks, provider_charge_id). Возврат через API не выполняется автоматически. Действия: выполнить ручной возврат в кабинете ЮKassa по `provider_charge_id` и сумме; при необходимости уведомить пользователя. Подробно: [YOOMONEY_TRIAL_MANUAL_REFUND.md](YOOMONEY_TRIAL_MANUAL_REFUND.md).

---

## 6. Банковский перевод: чек не засчитался

- Логи бота при отправке чека: распознавание (LLM), проверка суммы/карты/дубликата. При трёх неудачах пользователь видит предложение обратиться в поддержку. Действия: проверить настройки банковского перевода в админке; при спорных случаях — ручное зачисление (grant pack) через админку и уведомление пользователя.

---

## 7. Бот не отвечает или пользователи в бане/подвешены

- Логи бота: исключения, SecurityMiddleware (ban, suspend, rate limit). Админка → Безопасность: снять бан/suspend или скорректировать rate limit. Проверить, что контейнер бота запущен и получает обновления от Telegram (нет ошибок подключения в логах).

---

## 8. Админка не открывается / 401

- Проверить CORS и URL API в конфиге админки (`VITE_API_BASE` при сборке). Логин: `ADMIN_USERNAME` / `ADMIN_PASSWORD` из `.env`. При смене пароля — перезапуск API (сессии/cookie).

---

## 9. Эскалация

- При потере данных БД — восстановление из последнего бэкапа ([STABILITY_AND_BACKUPS.md](STABILITY_AND_BACKUPS.md)).
- При массовых сбоях провайдера генерации — переключение на другой провайдер (смена `IMAGE_PROVIDER` и ключей) и перезапуск воркера.
- Критичные баги платежей/доставки — фиксация в логах и БД (order_id, payment_id, user_id), ручное разрешение (возврат/повторная доставка) и последующий разбор кода/тестов.
