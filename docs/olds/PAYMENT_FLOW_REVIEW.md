# Payment flow — жёсткий code review

Проверка сценария оплаты end-to-end: создание платежа, checkout, success/fail/cancel, webhooks, idempotency, race conditions, выдача результата, edge cases.

---

## 1. Critical issues

### 1.1 Trial: оплата без выдачи и без рефанда при race

**Где:** `app/services/payments/service.py` — `process_session_purchase()` при `pack.is_trial`.

**Суть:** После создания сессии и начисления HD выполняется `UPDATE User SET trial_purchased = True WHERE ...`. При `rowcount == 0` выбрасывается `ValueError("Trial уже использован (race condition guard)`) и делается rollback. Обрабатывается только `IntegrityError`, не `ValueError`.

**Следствия:**
- Второй платёж за trial (дубль от Telegram или два быстрых клика) списывается у пользователя, но запись Payment не создаётся (rollback).
- При повторной доставке того же `successful_payment` снова будет исключение → пользователь платит, не получает сессию, автоматический рефанд не вызывается.
- Деньги списаны, выдача не произошла, запись о платеже в БД нет → сложно автоматически вернуть средства.

**Нужно:** Обрабатывать "Trial уже использован" без падения всей транзакции: либо не бросать исключение (только лог и пропуск обновления trial), либо при таком ValueError вызывать рефанд через Telegram API по `telegram_payment_charge_id` и возвращать пользователю явное сообщение о возврате.

---

### 1.2 Unlock: нет проверки владельца job в pre_checkout

**Где:** `validate_pre_checkout()` для legacy payload с `pack_id == "unlock"` не проверяет, что `job_id` принадлежит текущему пользователю.

**Суть:** В pre_checkout проверяется только `user_id` из payload и совпадение с `telegram_user_id`. Владение job не проверяется. В `successful_payment` при `job.user_id != user.id` только пишется лог, но `credit_tokens()` уже вызван — платёж записан за плательщика.

**Следствия:**
- Теоретически можно сформировать payload с чужим `job_id` и оплатить. Деньги списаны, разблокировка и отправка файла не выполняются (owner check в handler), запись Payment создаётся.
- Итог: оплата без выдачи и без разблокировки чужого job.

**Нужно:** В `validate_pre_checkout()` для legacy unlock по `job_id` загружать Job и проверять `job.user_id == user.id`. При несовпадении возвращать `(False, "Фото не найдено" или аналог)`.

---

### 1.3 process_refund: возможен двойной рефанд при конкурентных вызовах

**Где:** `app/services/payments/service.py` — `process_refund()`.

**Суть:** Платёж читается без `SELECT ... FOR UPDATE`. Два одновременных вызова могут оба увидеть `status != "refunded"`, оба заблокируют User и оба спишут токены и обновят платёж.

**Следствия:**
- Двойное списание токенов с баланса при двойном рефанде одной и той же оплаты.
- Риск рассинхрона баланса и двойного "возврата" по факту.

**Нужно:** Блокировать строку платежа:  
`payment = self.db.query(Payment).filter(Payment.id == payment_id).with_for_update().one_or_none()`  
и проверять `status == "refunded"` уже после блокировки (при необходимости — с перечитыванием после lock).

---

## 2. High-risk issues

### 2.1 Нет проверки total_amount в pre_checkout

**Где:** `handle_pre_checkout()` — используется только `invoice_payload`, сумма из запроса не проверяется.

**Суть:** В Telegram PreCheckoutQuery приходит и payload, и сумма. Текущая логика не сверяет фактическую сумму с ожидаемой для данного payload (pack/session/upgrade/unlock).

**Риски:**
- При любом баге или рассинхроне (изменение цены пакета между отправкой инвойса и оплатой, сбой в сумме на стороне Telegram) мы можем одобрить платёж с неверной суммой.
- Нет защиты от сценария "подмена суммы" на уровне одного запроса (если бы такое было возможно).

**Нужно:** В pre_checkout получать `total_amount` из `pre_checkout` и для каждого типа payload проверять: для session/upgrade — сумма равна ожидаемой (pack.stars_price / upgrade_price), для unlock — равна `unlock_cost_stars`, для legacy pack — равна `pack.stars_price`. При несовпадении — `answer_pre_checkout_query(ok=False, error_message=...)`.

---

### 2.2 Unlock (Stars): платёж фиксируется до проверки владельца и доставки

**Где:** `handle_successful_payment()` для `pack_id == "unlock"`: сначала вызывается `credit_tokens()`, затем проверка `job.user_id == user.id` и отправка файла.

**Суть:** При несовпадении владельца платёж уже записан, доставка не выполняется, пользователю показывается только общее сообщение об ошибке (если попадает в другую ветку). Явного рефанда при owner mismatch нет.

**Риск:** Если по какой-то причине pre_checkout не отклонил чужой job (баг, обход), в success мы всё равно спишем оплату без выдачи. После добавления проверки в pre_checkout (п. 1.2) сценарий маловероятен, но порядок операций лучше поменять: проверка владельца и наличие `output_path_original` до вызова `credit_tokens()`, при несовпадении — не создавать платёж и при необходимости инициировать рефанд.

---

### 2.3 Session purchase: при IntegrityError возвращается existing без переоткрытия сессии

**Где:** `process_session_purchase()` в блоке `except IntegrityError`: после `self.db.rollback()` выполняется `self.db.query(Payment).filter(...).one_or_none()`.

**Суть:** После rollback сессия SQLAlchemy остаётся живой, следующий запрос идёт в новой транзакции — технически это ок. Но при любом другом исключении внутри блока (например, при логировании или последующем коде) состояние сессии может быть неочевидным. Явного бага не видно, но цепочка "rollback → query в той же сессии" заслуживает единообразной обработки и, при необходимости, явного переоткрытия контекста БД в handler при возврате "payment already processed".

---

## 3. Broken payment scenarios

| Сценарий | Поведение | Критичность |
|----------|-----------|-------------|
| Двойная оплата за trial (два successful_payment подряд) | Второй платёж: ValueError → rollback, нет Payment, нет рефанда | Critical (деньги списаны, выдачи нет) |
| Unlock чужого job (payload с чужим job_id) | pre_checkout пропускает, success создаёт Payment, доставки нет | Critical (оплата без выдачи) |
| Двойной вызов process_refund(payment_id) | Оба могут пройти проверку status → двойное списание токенов | Critical |
| Повторная доставка successful_payment (retry Telegram) | По charge_id возвращается существующий Payment, повторное начисление не делается | OK (idempotency есть) |
| Отмена оплаты в Telegram | successful_payment не приходит, ничего не делаем | OK |
| Ошибка при send_document после credit_tokens (unlock) | Платёж записан, job не помечен unlocked, пользователю — "напишите в поддержку"; при retry — повторная попытка отправки по тому же payment | OK (идемпотентность по charge_id) |

---

## 4. Missing safeguards

- **Pre_checkout:** нет проверки суммы (`total_amount`) и для unlock — владельца job (см. п. 1.2, 2.1).
- **Success:** для unlock нет явного рефанда при owner mismatch; логичнее проверять владельца до `credit_tokens` и при несовпадении не создавать платёж и при необходимости вызвать рефанд.
- **process_refund:** нет блокировки строки Payment (FOR UPDATE) → риск двойного рефанда (п. 1.3).
- **Trial:** при "Trial уже использован" после списания нет автоматического рефанда и нет записи о платеже для последующего ручного рефанда.
- **Логирование:** charge_id и payload логируются — трассировка есть; добавление в логи `total_amount` и типа payload улучшит разбор инцидентов.
- **Idempotency:** по `telegram_payment_charge_id` реализована для credit_tokens и process_session_purchase/process_session_upgrade; отдельный IdempotencyStore (Redis) в payment flow не используется — для Telegram Stars текущей схемы достаточно.

---

## 5. What must be fixed before prod

1. **Обязательно (critical):**
   - Trial: обработать "Trial уже использован" без потери платежа: либо не падать (логировать и не обновлять trial), либо при таком ValueError вызывать рефанд по `telegram_payment_charge_id` и дать пользователю сообщение о возврате.
   - Unlock: в `validate_pre_checkout()` для legacy unlock проверять, что job принадлежит пользователю; при несовпадении — отклонять pre_checkout.
   - process_refund: читать Payment с `with_for_update()`, проверять `status == "refunded"` после блокировки, чтобы исключить двойной рефанд.

2. **Сильно рекомендуется (high-risk):**
   - В pre_checkout проверять `total_amount` против ожидаемой суммы для данного payload (session/upgrade/unlock/legacy pack).
   - Unlock в successful_payment: проверять владельца job до вызова `credit_tokens()`; при несовпадении не создавать платёж и при необходимости инициировать рефанд.

3. **Желательно:**
   - Уточнить и при необходимости усилить обработку возврата из `process_session_purchase` при IntegrityError (единообразие и явность работы с сессией БД после rollback).
   - Расширить логи (например, total_amount, тип payload) для упрощения разбора проблем с платежами.

---

## 6. Final verdict

**Payment flow: not safe for prod** в текущем виде.

Критичные проблемы:
- возможность **оплаты без выдачи** (trial race, unlock чужого job);
- возможность **двойного рефанда** (process_refund без блокировки платежа).

После внесения исправлений из п. 5 (как минимум пункты 1 и 3 по critical, желательно и п. 2 по high-risk) сценарий можно считать приемлемым для продакшена с последующим мониторингом и при необходимости доработкой проверки суммы и порядка проверок в unlock.
