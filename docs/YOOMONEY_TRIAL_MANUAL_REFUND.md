# Ручной возврат ЮMoney при trial_already_used

При гонке «Trial уже использован» после успешной оплаты ЮMoney автоматический возврат через API не выполняется (в отличие от Stars). Средства списаны с карты, сессия не создана.

## Что делается автоматически

- В лог пишется событие `yoomoney_trial_already_used_manual_refund_needed` с полями:
  - `telegram_id`
  - `charge_id`
  - `provider_charge_id`
  - `pack_id`
  - `amount_kopecks`
- Пользователю показывается сообщение: «Пробный пакет уже был использован. Обратитесь в поддержку: @… — мы вернём средства на карту.»

## Ручной возврат

1. Найти в логах записи с событием `yoomoney_trial_already_used_manual_refund_needed`.
2. По `provider_charge_id` и сумме `amount_kopecks` выполнить возврат в кабинете ЮKassa (или через API ЮKassa, если подключён).
3. При необходимости ответить пользователю (по telegram_id), что возврат выполнен.

## Рекомендации

- Настроить алерт при появлении события `yoomoney_trial_already_used_manual_refund_needed`.
- При появлении API возврата ЮKassa — добавить автоматический вызов при `trial_already_used` и логирование результата.
