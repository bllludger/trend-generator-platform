# Payment flow — жёсткий code review перед продом

Проверка после внедрения доработок: баги, edge cases, регрессии, логика, стабильность, обработка ошибок и состояний.

---

## 1. Critical bugs

### 1.1 NameError в unlock: использование `cost` и `user` после раннего выхода

**Где:** [app/bot/main.py](app/bot/main.py) — блок `if pack_id == "unlock"` в `handle_successful_payment()`.

**Суть:** После веток «owner mismatch» и «file not ready» нет `return`. Выполнение доходит до строк:
```python
audit.log(..., payload={"job_id": job_id_unlock, "stars": cost})
if user:
    ProductAnalyticsService(db).track(..., "price": cost, ...)
```
Переменная `cost` задаётся только в ветке `else` (`cost = settings.unlock_cost_stars`). В ветках «owner mismatch» и «file not ready» `cost` не определена → **NameError** при первом же таком сценарии (чужой job или оплата до появления файла).

**Следствие:** Падение хендлера successful_payment, пользователь видит общее сообщение об ошибке из `except`, рефанд при owner mismatch уже вызван, но аудит/аналитика не пишутся и возможны побочные эффекты от падения (например, повторная доставка update).

**Исправление (выполнено):** После обоих ранних выходов добавлен `return`; `audit.log`, `ProductAnalyticsService.track` и `logger.info("unlock_payment_completed")` перенесены внутрь ветки `else`, чтобы выполняться только при успешном unlock и не обращаться к неопределённому `cost`.

---

## 2. High-risk issues

### 2.1 process_refund для session-платежей не отзывает сессию и HD

**Где:** [app/services/payments/service.py](app/services/payments/service.py) — `process_refund()`.

**Суть:** Для платежей с `session_id` (session/upgrade) в `process_refund` списываются только `tokens_granted` (у session они равны 0). Сессия и начисленный HD не отзываются. Документация требует вызывать Telegram refund **отдельно**; отзыв доступа (завершение сессии, списание HD) в коде не реализован.

**Риск:** Админ может вызвать только `process_refund` (или только Telegram refund). В одном случае пользователь теряет деньги без возврата, в другом — получает возврат и сохраняет сессию/HD (двойная выгода). Нужна явная политика и, при необходимости, доработка: при рефанде session-платежа помечать сессию как отменённую и/или списывать соответствующий HD.

### 2.2 Redis при rate-limit: fail open

**Где:** [app/services/payments/service.py](app/services/payments/service.py) — `_check_rate_limit()`.

**Суть:** При `redis.RedisError` возвращается `True` (покупка разрешена). При недоступности Redis лимит не применяется.

**Риск:** В момент сбоя Redis возможен всплеск покупок сверх лимита. Для платежей это в первую очередь нагрузка и возможный abuse, а не прямая финансовая ошибка, но поведение стоит зафиксировать и при необходимости заменить на fail closed или явный отказ в оплате с сообщением «Попробуйте позже».

### 2.3 credit_tokens после rollback: запрос в той же сессии

**Где:** [app/services/payments/service.py](app/services/payments/service.py) — `credit_tokens()` в `except IntegrityError`.

**Суть:** После `self.db.rollback()` выполняется `self.db.query(Payment).filter(...).one_or_none()`. В SQLAlchemy сессия после rollback остаётся валидной, следующий запрос идёт в новой транзакции — технически корректно. Но вызывающий код (бот) держит контекст `with get_db_session()` и по выходу из контекста делает commit. Если между rollback и выходом из `with` в этой же сессии что-то ещё изменится, возможна путаница. Сейчас в этом пути только один запрос — риск низкий, но при доработках легко добавить код, полагающийся на «чистую» транзакцию.

**Рекомендация:** Оставить как есть, при изменениях не добавлять в этот блок дополнительную логику без явного переоткрытия сессии/транзакции.

---

## 3. Logic problems

### 3.1 Unlock: audit/track выполняются даже при раннем выходе (до исправления 1.1)

Пока после owner mismatch и file not ready нет `return`, логика «логируем только успешный unlock» нарушена: код пытается писать audit и аналитику для всех веток и падает на `cost`. После добавления `return` (и/или переноса audit/track в `else`) логика станет согласованной: один успешный путь — один платёж и одна запись в аудит/аналитику.

### 3.2 Legacy: pack_id пустой, но job_id есть

**Где:** Условие `if not pack_id and not job_id_unlock: return`.

**Суть:** Payload может содержать только `job_id` (например, старый формат unlock без pack в payload). Тогда `pack_id == ""`, мы не выходим по этой проверке и попадаем в `if pack_id == "unlock"` — не сработает. Далее идёт ветка `else` (покупка пакета), `pack = payment_service.get_pack("")` → `pack` None → сообщение «пакет не найден». Для чисто unlock payload без pack_id лучше явно обрабатывать «есть job_id, нет pack_id» как unlock (или отклонять с чётким сообщением), чтобы не уходить в ветку пакетов.

---

## 4. Edge cases missed

- **Pre_checkout без total_amount:** Если по какой-то причине `pre_checkout.total_amount` не приходит (старый клиент/версия), передаётся `None`; валидация суммы не выполняется, платёж по сумме не проверяется. Приемлемо как fallback, но в логах стоит явно фиксировать отсутствие total_amount.
- **Unlock, файл удалён:** Если `job.output_path_original` указывает на несуществующий файл, после `credit_tokens` отправка документа упадёт; пользователь получит «Оплата прошла, но не удалось отправить фото». Проверки существования файла до `credit_tokens` нет — при желании можно добавить и в этом случае не создавать платёж, а направлять в поддержку без списания (или с рефандом по политике).
- **Двойной клик / повторная доставка update:** Идемпотентность по `telegram_payment_charge_id` в `credit_tokens` и `process_session_purchase` сохраняется; повторная доставка того же successful_payment не создаёт второй платёж и не начисляет повторно — ок.
- **refund_star_payment исключение:** При падении `bot.refund_star_payment` (сеть, лимиты Telegram) логируем и показываем пользователю «Средства возвращены». Фактически деньги могут ещё не вернуться. Нужен мониторинг логов `trial_refund_failed` / `unlock_refund_failed` и ручной рефанд или повтор при сбоях.

---

## 5. What must be fixed before release

1. **Обязательно (critical) — выполнено:**  
   - **Unlock: NameError по `cost`.** Добавлен `return` после обеих ранних веток (owner mismatch, file not ready); audit/track/logger перенесены в ветку `else`.

2. **Желательно перед продом:**  
   - Зафиксировать политику рефанда для session-платежей (только Telegram + process_refund или ещё отзыв сессии/HD) и при необходимости реализовать отзыв доступа в `process_refund` для записей с `session_id`.  
   - Решить поведение при недоступности Redis в rate-limit (оставить fail open или перейти на fail closed с сообщением «Попробуйте позже»).  
   - Мониторинг логов `trial_refund_failed` и `unlock_refund_failed` и процедура ручного/повторного рефанда при сбоях Telegram API.

3. **По возможности:**  
   - Обработка legacy payload с `job_id` без `pack_id` как unlock (или явный отказ с понятным текстом).  
   - Проверка существования файла по `job.output_path_original` до вызова `credit_tokens` в unlock и единая политика (не создавать платёж / направить в поддержку / рефанд).

---

## 6. Final verdict

**Ready** для релиза после внесённого исправления критичного бага (return + перенос audit/track в else).

Рекомендуется перед/после выката: зафиксировать политику рефанда для session-платежей (п. 5.2), включить мониторинг логов `trial_refund_failed` и `unlock_refund_failed`, при необходимости — доработать поведение при недоступности Redis (rate-limit).
