# Обзор способов оплаты

Сводка способов оплаты, в каких сценариях они используются и куда приходят уведомления (webhooks).

## Способы оплаты

| Способ | Сценарий | Как инициируется | Подтверждение |
|--------|----------|------------------|---------------|
| **Telegram Stars** | Покупка пакета (Trial, Neo Start, Neo Pro, Neo Unlimited), апгрейд сессии, разблокировка одного фото (legacy) | Кнопка в боте → `send_invoice` (XTR). Payload: `session:...`, `upgrade:...`, `unlock:job_id` | `pre_checkout_query` → `successful_payment` в боте. Обработка в хендлерах бота: `process_session_purchase`, `process_session_upgrade`, `credit_tokens` (unlock). |
| **ЮMoney (инвойс в чате)** | Покупка пакета | Кнопка «Оплатить через ЮMoney» → `send_invoice` (RUB, provider_token). Payload: `yoomoney_session:...` | Аналогично Stars: pre_checkout + successful_payment в боте → `process_session_purchase_yoomoney`. При trial_already_used автоматический возврат не выполняется — ручной возврат, см. [YOOMONEY_TRIAL_MANUAL_REFUND.md](YOOMONEY_TRIAL_MANUAL_REFUND.md). |
| **ЮMoney (оплата по ссылке)** | Покупка пакета | Кнопка «Оплатить по ссылке» → создание платежа ЮKassa, ссылка пользователю. Создаётся **PackOrder**. | ЮKassa шлёт webhook `payment.succeeded` на **API** → `POST /webhooks/yookassa` → PackOrderService.mark_paid, process_session_purchase_yookassa_link, отправка поздравления в Telegram. |
| **ЮKassa (разблокировка одного фото)** | После выбора варианта A/B/C в free preview — оплата одного фото без watermark | Кнопка «Оплатить» на экране unlock → создание **UnlockOrder**, ссылка на оплату ЮKassa. Return URL: `https://t.me/Bot?start=unlock_done_{order_id}` | Webhook `payment.succeeded` → UnlockOrderService.mark_paid → задача Celery `deliver_unlock_file` → отправка файла в чат. |
| **Банковский перевод** | Покупка пакета | «Перевод на карту» → реквизиты и комментарий → пользователь загружает фото чека. State: `bank_transfer_waiting_receipt`. | Обработка в боте: распознавание чека (LLM), проверка суммы/карты/дубликата → `process_session_purchase_bank_transfer` или `credit_tokens_manual`. Настройки в админке: [Bank transfer](ADMIN_GUIDE.md). |

## Где что хранится

- **Stars / ЮMoney (инвойс в чате):** платёж фиксируется в таблице **payments** (telegram_payment_charge_id, pack_id, session_id, payload). Сессия создаётся/обновляется в **sessions**.
- **ЮMoney по ссылке (пакет):** заказ в **pack_orders** (yookassa_payment_id, pack_id, status). После webhook — обновление pack_orders и создание/обновление session.
- **ЮKassa unlock:** заказ в **unlock_orders** (take_id, variant, yookassa_payment_id, status). После webhook — mark_paid, запись в payments (record_yookassa_unlock_payment), постановка deliver_unlock_file.
- **Банковский перевод:** логи чеков (bank_transfer_receipt_log), при успехе — payment и session как при обычной покупке пакета.

## Сценарии по потоку пользователя

1. **Магазин («Купить пакет»):** выбор пакета → экран способов оплаты (Stars, ЮMoney, ЮMoney по ссылке, «Перевод на карту») → в зависимости от выбора: инвойс в чате (Stars/ЮMoney) или переход на оплату по ссылке (PackOrder) или ввод реквизитов и загрузка чека.
2. **Paywall после бесплатного превью:** выбор варианта A/B/C → если нет активной сессии — экран оплаты (Trial, пакеты). Оплата Stars/ЮMoney в чате или по ссылке (пакет) или unlock по ссылке (одно фото).
3. **Unlock одного фото (по ссылке):** только для сценария «выбрал вариант в free preview» → создаётся UnlockOrder, пользователь переходит по ссылке ЮKassa → после оплаты возврат в бота `?start=unlock_done_{order_id}` и доставка файла по webhook.

## Webhooks

Входящие webhook'и от внешних сервисов описаны в [WEBHOOKS.md](WEBHOOKS.md). Для платежей критичен только **POST /webhooks/yookassa**: он обрабатывает и unlock (UnlockOrder), и покупку пакета по ссылке (PackOrder). Ответ всегда 200, чтобы ЮKassa не ретраила; при внутренней ошибке заказ может остаться в статусе payment_pending — см. [RUNBOOK.md](RUNBOOK.md).
