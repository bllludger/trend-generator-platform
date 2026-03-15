# Code Review: Payment Flow — Release-Critical Zone

**Scope:** payment flow, critical API/backend, auth/session/permissions, async/queues/retries, preview→checkout→success, analytics on conversion, error handling, prod config/env/feature flags.

**Focus:** только то, что ломает оплату, роняет сценарий, даёт silent failure, портит конверсию, нестабильность в проде, критичные security/config риски.

---

## 1. Critical issues

### 1.1 Unlock (Stars): оплата принята, файла нет — нет рефанда и нет записи платежа

**Где:** `app/bot/main.py`, `handle_successful_payment`, ветка `pack_id == "unlock"`.

**Суть:** Если у Job нет `output_path_original` (файл ещё не готов или потерян), код:
- показывает пользователю: «Оплата принята, но файл ещё не готов. Обратитесь в /paysupport»;
- **не** вызывает `credit_tokens` (запись Payment не создаётся);
- **не** вызывает `bot.refund_star_payment()`.

**Итог:** Деньги списаны в Telegram, доставки нет, возврата нет, в БД платежа нет — потеря денег для пользователя и риск для репутации/комплаенса.

**Нужно:** В этой ветке либо сразу делать `refund_star_payment` и сообщать «Средства возвращены, попробуйте позже», либо создавать Payment со статусом типа `pending_delivery` и иметь процесс доставки/рефанда по обращению в поддержку. Минимум — всегда рефандить при отсутствии файла.

---

### 1.2 YooMoney: trial_already_used без автоматического возврата

**Где:** `app/bot/main.py`, `handle_successful_payment`, ветка `payload.startswith("yoomoney_session:")`, блок `trial_flag == "trial_already_used"`.

**Суть:** Для Stars при «Trial уже использован» вызывается `refund_star_payment`. Для YooMoney только текст: «Обратитесь в /paysupport для возврата средств» — автоматического рефанда через API ЮKassa нет.

**Итог:** Пользователь оплатил рублями, сессия не создана, возврат только вручную. Риск недовольства и лишней нагрузки на поддержку.

**Нужно:** Либо реализовать возврат через API ЮKassa при `trial_already_used` и сообщать «Средства возвращены», либо явно задокументировать ручной процесс и мониторинг таких кейсов.

---

## 2. High-risk issues

### 2.1 Race при session purchase: rollback в сервисе + commit в handler

**Где:** `app/services/payments/service.py` — `process_session_purchase` при `IntegrityError` делает `self.db.rollback()` и возвращает `(existing, None, None)`. Handler использует тот же `db` из `get_db_session()`; при выходе из `with` вызывается `db.commit()`.

**Суть:** При гонке двух запросов с одним `charge_id` один падает по unique constraint, откатывает свою транзакцию и перезапрашивает Payment. Если второй ещё не закоммитил, `existing` будет `None` — пользователь увидит «Ошибка обработки», хотя второй запрос потом может успешно создать сессию.

**Итог:** Возможное «ложное» сообщение об ошибке при фактически успешной оплате. Потеря денег маловероятна (один из запросов создаст запись).

**Рекомендация:** После `rollback` делать повторный idempotency-запрос с короткой задержкой (или сериализуемая транзакция / advisory lock по `charge_id`), чтобы чаще возвращать уже созданный платёж и не показывать ошибку.

---

### 2.2 Rate limit: fail-open при недоступности Redis

**Где:** `app/services/payments/service.py`, `_check_rate_limit` — при `redis.RedisError` возвращается `True` (покупка разрешена).

**Суть:** При падении Redis лимит покупок не применяется — возможен всплеск покупок/злоупотреблений.

**Рекомендация:** Для прода оставить fail-open (чтобы не блокировать все оплаты при сбое Redis), но добавить алерт при RedisError и мониторинг аномалий по количеству платежей.

---

## 3. Conversion blockers

### 3.1 pay_initiated не отправляется в основном флоу (магазин / paywall Stars)

**Где:** `app/bot/main.py`: для апгрейда сессии вызывается `ProductAnalyticsService(db).track("pay_initiated", ...)` перед `send_invoice`; для основного выбора пакета (paywall → Stars) вызываются только `payment_method_selected` и затем сразу `send_invoice` — события `pay_initiated` нет.

**Суть:** Воронка в телеметрии (pay_click → pay_initiated → pay_success) для основной массы покупок пакетов неполная: шаг «нажата оплата» не фиксируется.

**Итог:** Конверсия «pay_initiated → pay_success» и отчёты по воронке для основного сценария некорректны.

**Нужно:** Добавить `track("pay_initiated", user.id, pack_id=pack_id, properties={...})` перед `send_invoice` в `pay_method_stars` (и при необходимости в других точках создания инвойса за пакет).

---

## 4. Stability risks

### 4.1 Обработка исключений в handle_successful_payment

**Где:** `app/bot/main.py`, конец `handle_successful_payment`: общий `except Exception` логирует и отправляет «Ошибка при обработке платежа. Обратитесь в /paysupport». `charge_id` задаётся в начале обработчика до `try`, поэтому в логах он есть — ок.

**Суть:** При любой необработанной ошибке пользователь видит общее сообщение, платёж в Telegram уже прошёл. Если падение произошло до записи Payment/сессии, возможен «деньги списаны — в БД ничего нет». Нет автоматического ретрая или отложенной обработки.

**Рекомендация:** Для прода: (1) не глотать исключения; (2) иметь мониторинг/алерт по таким логам; (3) рассмотреть фоновую очередь для идемпотентной повторной обработки по `charge_id` (с лимитом попыток), чтобы не терять платежи при временных сбоях БД/Redis.

---

### 4.2 Цены YooMoney: DISPLAY_RUB и pre_checkout

**Где:** `app/services/balance_tariffs.py` — `DISPLAY_RUB` (рубли); `validate_pre_checkout` для `yoomoney_session:` берёт сумму из `DISPLAY_RUB` или `pack.stars_price * star_to_rub`, переводит в копейки и сверяет с `total_amount`.

**Суть:** В `pay_method_yoomoney` инвойс формируется с `amount_kopecks = rub * 100` из того же источника. Логика согласована; риск — рассинхрон при изменении только DISPLAY_RUB или только цен в БД. Тогда pre_checkout может начать отклонять легитимные платежи.

**Рекомендация:** Один источник правды для суммы (например, БД + star_to_rub для RUB), DISPLAY_RUB только для отображения и расчёт в копейках из того же источника; тесты на изменение цен.

---

## 5. What must be fixed before prod

1. **Unlock без файла (1.1):** ✅ Исправлено — при отсутствии `output_path_original` вызывается `refund_star_payment`, пользователю сообщение «Средства возвращены» или «Обратитесь в /paysupport» при ошибке рефанда.
2. **YooMoney trial (1.2):** ✅ Частично — добавлено структурированное логирование `yoomoney_trial_already_used_manual_refund_needed` (telegram_id, charge_id, provider_charge_id, amount_kopecks) и уточнённое сообщение пользователю «Обратитесь в /paysupport — мы вернём средства на карту». Автовозврат через API ЮKassa не реализован (нужна отдельная интеграция).
3. **pay_initiated (3.1):** ✅ Исправлено — в `pay_method_stars` перед `send_invoice` добавлен `ProductAnalyticsService.track("pay_initiated", ..., pack_id, price_stars, price_rub)`.
4. **Мониторинг:** Алерты на исключения в `handle_successful_payment` и на RedisError в rate limit; дашборд по «платёж есть в логах Telegram / нет в payments» — остаётся на стороне инфраструктуры.

**Доп. исправлено:** Race (2.1) — в `process_session_purchase`, `process_session_purchase_yoomoney`, `process_session_upgrade` после `IntegrityError` добавлены `time.sleep(0.15)` и повторный запрос Payment (+ загрузка Session по session_id); при нахождении записи возвращается (existing, session, None), чтобы хендлер мог показать «Платёж уже обработан» или успешное сообщение.

---

## 6. Что проверено и ок

- **Idempotency:** В `process_session_purchase` и `process_session_purchase_yoomoney` проверка по `telegram_payment_charge_id` / `yoomoney:{provider_charge_id}` в начале — повторный вызов не создаёт дубликаты.
- **Commit:** `get_db_session()` делает commit при успехе, rollback при исключении — поведение ожидаемое.
- **Pre-checkout:** Валидация payload, суммы, валюты, блокировки, rate limit, trial — покрыто; при ошибке всегда вызывается `answer_pre_checkout_query(ok=False, error_message=...)`.
- **Payload session/upgrade:** Формат `session:{pack_id}` и `upgrade:{new_pack_id}:{session_id}` согласован между отправкой инвойса и разбором в successful_payment.
- **YooMoney:** `amount_kopecks` в Payment и в запросе инвойса согласованы; миграция 060 добавляет колонку.
- **Admin API:** Роуты платежей защищены `Depends(get_current_user)` (JWT).
- **Конфиг:** `env.example` и `app/core/config.py` содержат нужные переменные для Stars, ЮMoney, банковского перевода; нет захардкоженных секретов в коде.

---

## 7. Final verdict

**No-go** до исправления пунктов раздела 5 (как минимум 1.1 и 1.2).

После исправления критичных пунктов (unlock без файла, YooMoney trial, при необходимости — pay_initiated и мониторинг) — **go** с пониманием рисков по гонке (2.1) и стабильности (4.1), с планом доработок по мониторингу и повторной обработке платежей.
