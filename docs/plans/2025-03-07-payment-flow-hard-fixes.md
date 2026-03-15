# Payment flow — исправления по жёсткому ревью (вариант 2)

> **Цель:** Закрыть critical + high-risk из PAYMENT_FLOW_HARD_REVIEW без большого рефакторинга. Критичные инварианты в PaymentService, хендлер — тонкая оркестрация.

**Архитектура:** Два этапа для unlock (commit платежа → доставка файла). Guards «уже оплачено / уже разблокировано» в pre_checkout, при показе инвойса и в successful_payment. Rate limit — fail closed при Redis down. В общем except successful_payment — попытка рефанда Stars. ЮMoney trial — логирование и документ (автовозврат только при появлении API).

---

## Task 1: PaymentService — guards для unlock и pre_checkout

**Файлы:** `app/services/payments/service.py`

- Добавить метод `has_unlock_payment_for_job(self, job_id: str) -> bool`: есть ли хотя бы один Payment с `pack_id="unlock"`, `job_id=job_id`, `status="completed"`.
- В `validate_pre_checkout` для legacy unlock (блок `pack_id == "unlock"`): после проверки job и владельца добавить: если `job.unlocked_at` или `has_unlock_payment_for_job(job_id)` — вернуть `(False, "Фото уже разблокировано")`.
- В `_check_rate_limit`: при `redis.RedisError` возвращать `False` (fail closed). Сообщение в pre_checkout при отказе по rate limit уже есть («Слишком много покупок»); при RedisError можно оставить то же или «Сервис временно недоступен» — в pre_checkout текст берётся из error_msg, в сервисе при fail closed вызывающий код получит False и подставит своё сообщение. Проверить: при False из _check_rate_limit вызывающий validate_pre_checkout возвращает (False, "Слишком много покупок. Попробуйте позже."). Для RedisError лучше отдельное сообщение «Сервис временно недоступен. Попробуйте позже.» — для этого можно возвращать из _check_rate_limit пару (ok: bool, error_key: str) или бросать специальное исключение, но проще в validate_pre_checkout поймать вызов _check_rate_limit и при RedisError возвращать (False, "Сервис временно недоступен. Попробуйте позже."). Реализация: в _check_rate_limit при RedisError логировать и возвращать False. В validate_pre_checkout при not _check_rate_limit возвращать (False, "Слишком много покупок. Попробуйте позже.") — тогда при RedisError пользователь увидит «Слишком много покупок», что приемлемо. Либо в _check_rate_limit возвращать tuple (allowed: bool, reason: str | None); при RedisError (False, "redis_unavailable"). В validate_pre_checkout если not allowed и reason == "redis_unavailable": return (False, "Сервис временно недоступен. Попробуйте позже."). Минимальное изменение: оставить _check_rate_limit возвращающим bool, при RedisError return False; сообщение везде «Слишком много покупок» — ок для первого прохода. Позже можно уточнить текст по логам.
- Коммит: `fix(payments): unlock guards in pre_checkout, rate limit fail closed`

---

## Task 2: Бот — unlock_photo: не показывать инвойс, если уже оплачено за job

**Файлы:** `app/bot/main.py`

- В `unlock_photo()` после проверки `job.is_preview` и `output_path_original`: вызвать `payment_service.has_unlock_payment_for_job(job_id)`. Если True — не вызывать `send_invoice`, ответить пользователю «Это фото уже оплачено. Если не получили файл — напишите в поддержку: @…» и `callback.answer()`, return.
- Коммит: `fix(bot): unlock invoice only if no existing unlock payment for job`

---

## Task 3: Бот — successful_payment unlock: проверка «уже разблокировано» и два этапа (commit → доставка)

**Файлы:** `app/bot/main.py`

- В ветке `pack_id == "unlock"` после проверки владельца и наличия `output_path_original`, **до** вызова `credit_tokens`: проверить `job.unlocked_at` или `payment_service.has_unlock_payment_for_job(job_id_unlock)`. Если уже разблокировано/оплачено: вызвать `bot.refund_star_payment(charge_id)`, сообщение «Фото уже разблокировано. Средства возвращены.» return.
- Разбить обработку unlock на два этапа:
  1) В одном `with get_db_session() as db:` только валидации + `credit_tokens`; audit.log/track для unlock выполнять после успешной доставки (перенести в блок после send_document). По выходу из `with` — commit, платёж сохранён.
  2) После выхода из `with`: в try вызвать send_document; в том же try в новом `with get_db_session() as db:` обновить job (is_preview=False, unlocked_at=now, unlock_method="stars"), paywall_record_unlock, audit, ProductAnalyticsService, logger.info. При исключении send_document или обновления job: except — logger.exception, сообщение пользователю «Оплата принята. Не удалось отправить фото — напишите в поддержку: @…».
- Убедиться, что audit.log и ProductAnalyticsService для unlock вызываются только при успешной доставке (в блоке после send_document).
- Коммит: `fix(bot): unlock two-phase commit then deliver; refund if already unlocked`

---

## Task 4: Бот — общий except в successful_payment: попытка рефанда Stars

**Файлы:** `app/bot/main.py`

- В блоке `except Exception` в конце `handle_successful_payment`: определить, был ли платёж Stars (по payload: не начинается с `yoomoney_session:` и приходит из message.successful_payment — для Stars приходит telegram_payment_charge_id). Вызвать `await bot.refund_star_payment(user_id=message.from_user.id, telegram_payment_charge_id=charge_id)` в try/except, залогировать успех или исключение (`payment_failed_refund_attempt`, `payment_failed_refund_error`). После этого отправить пользователю то же сообщение об ошибке и поддержке. Не рефандить, если payload.startswith("yoomoney_session:") (ЮMoney возврат отдельно).
- Коммит: `fix(bot): attempt Stars refund on successful_payment exception`

---

## Task 5: ЮMoney trial_already_used — документ и логирование

**Файлы:** `docs/PAYMENT_FLOW_HARD_REVIEW.md` (или отдельный процесс), код уже логирует `yoomoney_trial_already_used_manual_refund_needed`.

- Добавить в `docs/` короткий процесс «Ручной возврат ЮMoney при trial_already_used»: по логам (telegram_id, provider_charge_id, amount_kopecks) выполнить возврат в ЮKassa/админке; алерт при появлении события. В коде оставить как есть (логирование + сообщение пользователю).
- Коммит: `docs: YooMoney trial manual refund process`

---

## Task 6: Регрессионные тесты

**Файлы:** `tests/services/payments/test_payment_service.py` (создать при отсутствии), при необходимости `tests/bot/test_payment_handlers.py` (если есть контур для хендлеров).

- Тесты для PaymentService: `has_unlock_payment_for_job` возвращает True при наличии Payment (pack_id=unlock, job_id, status=completed), False иначе; `validate_pre_checkout` для unlock с уже существующим платежом за job — (False, "Фото уже разблокировано"); rate limit при RedisError — возврат False (мок Redis).
- Минимально: один тест на has_unlock_payment_for_job, один на pre_checkout reject при уже оплаченном unlock.
- Коммит: `test(payments): unlock guards and rate limit fail closed`

---

## Проверка

- Ручная проверка: unlock дважды (второй раз инвойс не показывается / при повторной оплате рефанд и сообщение); отключить Redis — pre_checkout отклоняется; при падении send_document платёж остаётся в БД, сообщение пользователю.
- Запуск тестов: `pytest tests/services/payments/ -v`
