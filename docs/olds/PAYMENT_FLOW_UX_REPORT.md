# Отчёт: флоу оплаты, методы и UX (NeoBanana)

Полный обзор платёжной системы проекта: сценарии, способы оплаты, пользовательский опыт и техническая реализация.

---

## 1. Обзор методов оплаты

| Метод | Валюта | Где доступен | Что покупается |
|-------|--------|--------------|----------------|
| **Telegram Stars** | XTR (Stars) | Магазин, paywall, апгрейд сессии | Пакеты сессий (trial, Neo Start, Neo Pro, Neo Unlimited), апгрейд, разблокировка (legacy) |
| **Перевод на карту** | RUB | Кнопка «Не получается купить Stars» / «Оплатить картой» | Те же пакеты продуктовой лестницы (по Stars-эквиваленту в рублях) |
| **Токены (внутренний баланс)** | — | Разблокировка одного фото с превью | Одно фото без водяного знака (`unlock_tokens`) |
| **Бонусы 4K (реферальные)** | — | Кнопка «За бонус 4K» на paywall | Одно фото в 4K без оплаты Stars |

**Продуктовая лестница (PRODUCT_LADDER_IDS):** `trial`, `neo_start`, `neo_pro`, `neo_unlimited`. Только эти пакеты показываются в магазине, paywall и оплате переводом.

---

## 2. Флоу оплаты по сценариям

### 2.1 Покупка пакета за Stars (основной сценарий)

**Точки входа:**

1. **Меню → «🛒 Купить пакет»** → экран магазина (`_show_shop`).
2. **Профиль** → «Как пополнить» → выбор «⭐ Stars (в боте)» → магазин.
3. **Контекстный paywall** после бесплатного превью (выбор варианта A/B/C) → кнопки пакетов с ценой в Stars и рублях.

**Экран магазина (balance_tariffs):**

- Текст: «Осталось фото: N из M» (если есть активная сессия) или «Выберите пакет».
- Описания пакетов: Trial (1 фото), Neo Start (10 фото), Neo Pro (40 фото), Neo Unlimited (120 фото).
- Кнопки: каждая — «emoji Название · outcome · RUB ₽», `callback_data`: `paywall:{pack_id}`.
- Доп. кнопки: «📘 Как купить Stars», «💳 Не получается купить Stars», «📋 В меню».

**После нажатия на пакет:**

- Хендлер `paywall_buy`: проверка пакета, пользователя, trial уже использован.
- Формируется payload: `session:{pack_id}`.
- Вызов `bot.send_invoice()`: title, description, payload, currency=XTR, prices=[LabeledPrice].
- Пользователь видит нативное окно оплаты Telegram Stars.

**Pre-checkout:**

- `handle_pre_checkout`: из payload извлекается тип (`session:`, `upgrade:`, legacy).
- Для `session:{pack_id}`: проверка пользователя, блокировки, rate-limit, пакет доступен, для trial — не использован; проверка `total_amount` и валюты XTR.
- При успехе: `answer_pre_checkout_query(ok=True)`; при отказе — сообщение об ошибке (до 200 символов).

**Successful payment:**

- `handle_successful_payment`: для `session:{pack_id}` вызывается `PaymentService.process_session_purchase()`.
- Создаётся/находится Payment (идемпотентность по `telegram_payment_charge_id`), создаётся Session, начисляется HD на баланс пользователя (`HDBalanceService.credit_paid`).
- Trial: атомарная установка `user.trial_purchased = True`; при гонке («Trial уже использован») — рефанд через `bot.refund_star_payment()` и сообщение пользователю.
- Пользователю отправляется сообщение: «✅ Пакет {emoji} {name} активирован! Осталось фото: N. Отправьте фото для начала!» и главное меню.

**UX-детали:**

- В магазине показывается картинка (MONEY_IMAGE_PATH), если есть.
- Цены в рублях считаются как `stars_price * star_to_rub` (по умолчанию 1.3).
- Аудит: `pay_click`, `pay_success`; аналитика: `pay_initiated`, `pay_success` с pack_id, price, payment_method: "stars".

---

### 2.2 Апгрейд сессии (Trial → Neo Start / Neo Pro)

**Точка входа:** только при активной сессии пакета **Trial**: в статусе сессии («📸 Ваша сессия») показываются кнопки:

- «⬆️ Neo Start — доплата 54⭐»
- «⬆️ Neo Pro — доплата 439⭐»

`callback_data`: `upgrade:neo_start` / `upgrade:neo_pro`.

**Флоу:**

- Хендлер `upgrade_session`: проверка активной сессии, новый пакет доступен; цена доплаты = `new_pack.stars_price - old_pack.stars_price`.
- Payload: `upgrade:{new_pack_id}:{old_session_id}`.
- `send_invoice` с title «⬆️ Апгрейд до {name}», description с доплатой и зачётом.

**Pre-checkout:** проверка payload `upgrade:`, валидация сессии и принадлежности пользователю, ожидаемая сумма = доплата.

**Successful payment:** `process_session_upgrade()` — создаётся новая сессия (старая помечается как upgraded), начисляется дельта HD. Сообщение: «⬆️ Апгрейд до {pack}! Осталось фото: N. Продолжайте!».

---

### 2.3 Оплата переводом на карту (bank transfer)

**Точки входа:**

- Магазин: «💳 Не получается купить Stars» → текст «Как купить Stars» + кнопка «💳 Оплатить картой (перевод)».
- Профиль: «Как пополнить» → «💳 Карта (перевод)».

**Шаг 1 — `bank_transfer:start`:**

- Проверка: способ включён в админке (`BankTransferSettings.enabled` и указана карта).
- Текст из настроек (step1_description): про оплату переводом на карту Озон Банка и выбор пакета.
- Кнопки: пакеты продуктовой лестницы с подписью вида «emoji Название: outcome — N⭐ (RUB ₽)», `callback_data`: `bank_pack:{pack_id}`; «📋 В меню».

**Шаг 2 — `bank_pack:{pack_id}`:**

- В FSM сохраняются: pack_id, pack_name, tokens, stars, expected_rub (stars × star_to_rub), receipt_code («оплата № N» из Redis-счётчика).
- Состояние: `BotStates.bank_transfer_waiting_receipt`.
- Текст из шаблона step2_requisites: номер карты, комментарий (если включён), сумма к переводу, код в комментарии; напоминание отправить чек после перевода.
- Кнопка «❌ Отменить».

**Шаг 3 — приём чека:**

- Пользователь отправляет фото или документ (image) в состоянии `bank_transfer_waiting_receipt`.
- Файл сохраняется в `{storage_base_path}/receipts/`.
- `_process_bank_receipt`: вызов Vision (LLM receipt_parser) для извлечения: amount_rub, card_number (first4/last4), date_time, comment.
- Проверки: сумма в допуске (amount_tolerance_abs, amount_tolerance_pct), карта совпадает с настройкой, свежесть чека (не старше 48 ч), антидубликат по fingerprint.
- При успехе: `PaymentService.credit_tokens_manual()` с `charge_id = bank_transfer:{reference}` (uuid), начисление `tokens_granted` на `user.token_balance`. **Важно:** у session-пакетов (trial, neo_*) в Pack поле `tokens = 0`, поэтому при оплате переводом зачисляются 0 токенов, сессия не создаётся и HD не начисляется — для полной поддержки нужна отдельная ветка (как для Stars: создание сессии + credit HD). Сообщение из success_message. Очистка FSM.
- При неудаче: счётчик попыток; после 3 неудач — текст с /paysupport и кнопки «🔄 Попробовать снова», «📋 В меню».

**Ограничения:**

- Rate limit: 10 попыток в час на пользователя.
- Комментарий к переводу в проверках отключён (`BANK_RECEIPT_COMMENT_DISABLED = True`).
- Каждая попытка логируется в `bank_transfer_receipt_log` (админка: раздел «Оплата переводом» → лог чеков).

**UX:**

- Понятный пошаговый сценарий; при несовпадении — явное сообщение и возможность повторной отправки чека.
- Админка: настройка реквизитов, промптов Vision, допусков, текстов шагов и сообщений об ошибке.

---

### 2.4 Разблокировка одного фото (превью → полное качество)

**Контекст:** Legacy Job (одно фото с превью) или контекст «получить 4K» по одному избранному. В текущем UX разблокировка за Stars в интерфейсе убрана; остались:

- **За токены:** кнопка «Разблокировать за N токен», `unlock_tokens:{job_id}`. Списывается `unlock_cost_tokens` с баланса, запись в payments с pack_id=unlock_tokens, отправка оригинала, обновление job (unlock_method=tokens).
- **За бонус 4K:** кнопка «🎁 За бонус 4K», `unlock_hd:{job_id}`. Списывается 1 реферальный HD-кредит, отправка оригинала.

**Legacy unlock за Stars (если бы использовался):** payload с pack_id=unlock и job_id. В pre_checkout проверяется владелец job. В successful_payment — проверка владельца и наличия файла до `credit_tokens`; при несовпадении — рефанд и сообщение.

---

## 3. Модели данных и сервисы

### 3.1 Payment (модель)

- `id`, `user_id`, `telegram_payment_charge_id` (уникален), `provider_payment_charge_id`
- `pack_id`, `stars_amount`, `tokens_granted`, `status` (completed / refunded)
- `payload`, `job_id`, `session_id`, `created_at`, `refunded_at`

Платёж привязан к сессии (`session_id`) для session-пакетов или к job для unlock.

### 3.2 Pack

- Session-пакеты: `takes_limit`, `hd_amount`, `is_trial`, `pack_type` (session/legacy), `stars_price`.
- Product ladder: trial, neo_start, neo_pro, neo_unlimited.

### 3.3 Ключевые сервисы

- **PaymentService:** list_active_packs, list_product_ladder_packs, get_pack, build_payload, resolve_payload, parse_payload, validate_pre_checkout, credit_tokens (идемпотентность по charge_id), process_refund (FOR UPDATE, откат токенов и реферального бонуса), credit_tokens_manual (bank transfer), process_session_purchase, process_session_upgrade, rate-limit покупок (Redis, 3 покупки / 60 сек, fail open при ошибке Redis).
- **BankTransferSettingsService:** реквизиты, тексты шагов, промпты и допуски для Vision, включение способа.
- **HDBalanceService:** credit_paid / credit_promo, spend (сначала promo, потом paid), get_balance.
- **SessionService:** создание сессии, апгрейд, привязка бесплатных Take к новой сессии.

---

## 4. UX-паттерны и сообщения

### 4.1 Магазин и выбор пакета

- **Баланс:** «Осталось фото: N из M» — один счётчик, без отдельного «4K» в магазине.
- **Кнопки пакетов:** outcome-first подписи («1 фото для пробы», «10 фото», «40 фото», «120 фото») и цена в рублях.
- **Помощь:** «Как купить Stars» — пошаговая инструкция + альтернатива «Оплатить картой».

### 4.2 После оплаты Stars

- Session: «✅ Пакет {emoji} {name} активирован! Осталось фото: N. Отправьте фото для начала!»
- Upgrade: «⬆️ Апгрейд до {pack}! Осталось фото: N. Продолжайте!»
- Trial уже использован: «Trial уже был использован. Средства возвращены на ваш счёт Stars.»

### 4.3 Ошибки и поддержка

- Pre-checkout отклонён: сообщение из `validate_pre_checkout` (например «Trial уже использован», «Неверная сумма платежа»).
- Общая ошибка обработки: «⚠️ Ошибка обработки. Обратитесь в /paysupport.»
- Команды: `/paysupport` — поддержка по платежам; `/terms` — условия использования (требование Telegram для ботов с оплатой).

### 4.4 Bank transfer

- Успех: настраиваемое success_message с подстановкой pack_name, tokens, balance.
- Неудача: amount_mismatch_message + «Попытка N из 3».
- После 3 неудач: приглашение в /paysupport и кнопка «Попробовать снова».

---

## 5. Админка

### 5.1 Платежи (PaymentsPage)

- Список платежей с фильтром по способу: все / Stars / перевод на карту.
- Период: 7, 30, 90 дней.
- Статистика: total_stars, revenue_rub_approx, revenue_usd_approx, total_payments, refunds, unique_buyers, conversion_rate_pct, разбивка по пакетам (by_pack).
- Действие: рефанд по кнопке; вызов `POST /admin/payments/{id}/refund` → `PaymentService.process_refund()`. Telegram refund админ должен выполнять отдельно (документировано).

### 5.2 Оплата переводом (BankTransferPage)

- Включение способа и реквизиты: номер карты, комментарий.
- Промпты Vision для чека (system/user), модель (например gpt-4o), допуски по сумме (abs, pct).
- Тексты: step1_description, step2_requisites, success_message, amount_mismatch_message.
- Лог чеков: таблица с фильтрами (успех/неудача, telegram_id), просмотр файла чека по id.

---

## 6. Безопасность и идемпотентность

- **Pre-checkout:** проверка user, блокировки, rate-limit, сумма и валюта; для unlock — владелец job.
- **Successful payment:** идемпотентность по `telegram_payment_charge_id` (повторная доставка update не создаёт второй платёж).
- **Trial:** атомарный UPDATE `trial_purchased`; при гонке — рефанд и сообщение.
- **Refund:** `process_refund` с `with_for_update()` по Payment, откат токенов и реферального бонуса; Telegram refund вызывается отдельно.
- **Bank transfer:** антидубликат по fingerprint чека; rate limit попыток; логирование всех попыток.

---

## 7. Связь с сессиями и HD

- Покупка session-пакета создаёт **Session** с `takes_limit` и `hd_limit`; на пользователя начисляется **HD** (`hd_paid_balance`) в размере `pack.hd_amount`.
- Апгрейд создаёт новую сессию и начисляет дельту HD.
- Расход HD происходит при доставке 4K (deliver_hd): сначала списываются promo, затем paid.
- Бесплатные Take из pre-session при покупке пакета переносятся в новую сессию и учитываются в takes_used.

---

## 8. Реферальная программа

- При первой оплате пакета (Stars) рефереру создаётся бонус (HD-кредиты); рефереру отправляется уведомление.
- При рефанде платежа бонус отзывается (`revoke_bonus_by_payment`).

---

## 9. Итоговая схема флоу (упрощённо)

```
[Меню / Профиль / Paywall]
        ↓
[Магазин или выбор пакета]
        ↓
  ┌─────┴─────┐
  │ Stars     │ Bank transfer
  ↓           ↓
send_invoice  Выбор пакета → Реквизиты → Чек (фото)
  ↓           ↓
Pre-checkout  Vision → проверки → credit_tokens_manual
  ↓
Success → process_session_purchase / process_session_upgrade
  ↓
Session создана, HD начислен → сообщение пользователю
```

Отчёт составлен по коду: `app/services/payments/service.py`, `app/bot/main.py`, `app/services/balance_tariffs.py`, `app/services/bank_transfer/settings_service.py`, `admin-frontend` (PaymentsPage, BankTransferPage), существующим ревью `PAYMENT_FLOW_REVIEW.md` и `PAYMENT_FLOW_CODE_REVIEW_PREPROD.md`.
