# Входящие webhook'и

Список входящих webhook'ов от внешних сервисов: назначение, идемпотентность и что делать при ошибке.

## POST /webhooks/yookassa

**Назначение:** приём уведомлений ЮKassa о статусе платежа. Обрабатываются события `payment.succeeded` и `payment.canceled`.

**Кто вызывает:** ЮKassa (настраивается в личном кабинете ЮKassa — URL должен указывать на ваш API, например `https://your-api.example.com/webhooks/yookassa`).

**Тело запроса:** JSON с полями `event` (тип события), `object` (объект платежа с `id`, `status` и др.). См. [документацию ЮKassa](https://yookassa.ru/developers/payment-acceptance/getting-started/notification).

**Логика обработки:**

1. **payment.canceled**  
   Поиск заказа по `object.id` (yookassa_payment_id): сначала **UnlockOrder**, затем **PackOrder**. Если найден и статус `created` или `payment_pending` — вызов `mark_canceled` для соответствующего заказа. Ответ **200** в любом случае.

2. **payment.succeeded**  
   - Поиск **UnlockOrder** по `object.id`. Если найден и статус `created` или `payment_pending`: `mark_paid`, запись платежа (PaymentService.record_yookassa_unlock_payment), постановка задачи Celery `deliver_unlock.deliver_unlock_file`. Ответ 200.
   - Если UnlockOrder не найден — поиск **PackOrder** по `object.id`. Если найден и статус `created` или `payment_pending`: `mark_paid`, `process_session_purchase_yookassa_link` (активация пакета), `mark_completed`, отправка сообщения об успехе в Telegram пользователю. Ответ 200.
   - Если заказ не найден — в лог пишется предупреждение, ответ 200.

**Идемпотентность:** Повторный запрос с тем же `payment.succeeded` для уже обработанного заказа (status уже `paid`/`delivered` или `completed`) приводит к ответу 200 без повторной обработки (проверка статуса в начале ветки).

**При ошибке:** Внутри обработки при исключении выполняется rollback БД и логирование; ответ клиенту всё равно **200**, чтобы ЮKassa не повторяла запрос бесконечно. Заказ может остаться в `payment_pending`. Действия: см. [RUNBOOK.md](RUNBOOK.md) (раздел «ЮKassa: webhook не сработал»): проверить статус в БД и при необходимости вручную обновить статус и поставить задачу доставки или активации.

**Код:** `app/api/routes/webhooks.py` — функция `yookassa_webhook`.

---

## Другие webhook'и

На текущий момент других входящих webhook'ов в приложении нет. Платежи через Telegram Stars и ЮMoney (инвойс в чате) обрабатываются в боте по событиям `pre_checkout_query` и `successful_payment`, без отдельного HTTP-callback от платёжной системы.
