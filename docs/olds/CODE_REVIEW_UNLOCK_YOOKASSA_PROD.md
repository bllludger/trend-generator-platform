# Code review: оплата по ссылке ЮKassa (unlock A/B/C) — перед продом

## 1. Critical bugs

### 1.1 Celery task не коммитит изменения в БД
**Файл:** `app/workers/tasks/deliver_unlock.py`  
**Проблема:** Используется `SessionLocal()` без вызова `db.commit()`. Все вызовы `mark_delivered()` и `mark_delivery_failed()` не сохраняются в БД после закрытия сессии.  
**Следствие:** Статусы заказов остаются `paid`, доставки не фиксируются, повторные задачи и логика «уже доставлено» ломаются.  
**Исправление:** После успешного обновления вызывать `db.commit()` перед `db.close()`. В блоке `except` при ошибке отправки — `db.rollback()` при необходимости, затем `commit()` только для `mark_delivery_failed`.

### 1.2 Webhook доверяет metadata.order_id
**Файл:** `app/api/routes/webhooks.py`  
**Проблема:** При отсутствии заказа по `yookassa_payment_id` заказ ищется по `metadata.get("order_id")`. Злоумышленник может отправить поддельный POST с произвольным `object.id` и известным `order_id` и перевести чужой заказ в paid, запустив доставку.  
**Исправление:** Искать заказ **только** по `get_by_yookassa_payment_id(payment_id)`. Не использовать `order_id` из metadata для поиска заказа при отметке paid. Если заказ не найден по `payment_id` — логировать и возвращать 200, не вызывать `mark_paid` и не ставить задачу.

### 1.3 Кнопка «Перейти к оплате» с пустым url
**Файл:** `app/bot/main.py`, ветка choose_variant (unlock).  
**Проблема:** Если ЮKassa вернула ответ без `confirmation.confirmation_url` (или с пустым), в кнопку передаётся `url=confirmation_url` (пустая строка). Сообщение «Оплатите по ссылке» при этом всё равно отправляется; возможны ошибки Telegram API или некорректная ссылка.  
**Исправление:** Если после `create_payment` нет `confirmation_url` или `yookassa_payment_id`, не вызывать `set_payment_created`, отправить пользователю сообщение об ошибке («Не удалось получить ссылку на оплату…») и не показывать кнопку с пустым url.

---

## 2. High-risk issues

### 2.1 Webhook без проверки источника
**Файл:** `app/api/routes/webhooks.py`  
**Проблема:** POST `/webhooks/yookassa` принимается без проверки подписи/источника. ЮKassa поддерживает проверку по IP или подпись — в коде её нет.  
**Рекомендация:** Добавить проверку (по документации ЮKassa): IP из whitelist и/или подпись в заголовках/теле. До внедрения — минимум не использовать `metadata.order_id` для поиска заказа (см. 1.2).

### 2.2 «Уже оплачено»: файл не отправился, но сообщение «Отправили ещё раз»
**Файл:** `app/bot/main.py`, блок existing_paid.  
**Проблема:** Если `original_path` пустой или файл не существует (`os.path.exists(original_path)` False), `send_document` не вызывается, но пользователю пишется «Фото уже разблокировано. Отправили ещё раз в чат.»  
**Исправление:** Если файла нет — не писать «Отправили ещё раз»; отправить сообщение вида «Файл временно недоступен» и кнопку «Получить фото снова» (или «В меню»), чтобы пользователь мог повторить позже.

### 2.3 Падение при удалённом take (existing_paid)
**Файл:** `app/bot/main.py`, блок existing_paid.  
**Проблема:** `TakeService(db).get_take(take_id)` может вернуть `None` (take удалён). Дальше вызывается `get_variant_paths(take, variant)` и возможен AttributeError.  
**Исправление:** Проверять `take` на None перед `get_variant_paths`; при отсутствии take — сообщение «Фото не найдено» и кнопка «В меню», без попытки отправить файл.

### 2.4 Пути к файлам и воркер Celery
**Файлы:** `app/workers/tasks/deliver_unlock.py`, модель Take (paths).  
**Проблема:** В `generate_take` пути строятся от `settings.storage_base_path` (как правило, абсолютные). Если Celery worker запущен на другой машине или без общего тома, файл по такому пути не будет найден — доставка всегда будет падать с `delivery_failed`.  
**Рекомендация:** В проде обеспечить одинаковый доступ к `storage_base_path` для API и воркеров (общий диск/NFS/одинальный путь). В коде при отсутствии файла логировать полный путь и `storage_base_path` для диагностики.

---

## 3. Logic problems

### 3.1 Order в статусе created без платежа
**Файл:** `app/bot/main.py`.  
**Проблема:** При успешном `create_or_get_pending_order` создаётся заказ со статусом `created`. Если затем `create_payment` падает с YooKassaClientError, заказ так и остаётся в `created` без `yookassa_payment_id`. При следующем нажатии «Выбрать и оплатить» для той же связки `get_pending_order` ищет только `payment_pending`, поэтому создаётся **второй** заказ (новая связка created). В итоге могут накапливаться «висящие» заказы в `created`.  
**Рекомендация:** Либо не считать `created` активным для правила «один pending на связку» и при следующем нажатии переиспользовать такой заказ (и повторять создание платежа), либо периодически переводить старые `created` без `yookassa_payment_id` в `failed` (отдельная задача/скрипт).

### 3.2 Повторный запуск deliver_unlock при двойном webhook
**Файл:** `app/workers/tasks/deliver_unlock.py`.  
**Поведение:** При двух вызовах (например, два ретрая webhook) первый вызов переводит заказ в `delivered`, второй получает из `get_order_for_delivery` `(order, None)` (т.к. status уже не `paid`) и вызывает `mark_delivery_failed`. В `mark_delivery_failed` есть проверка `order.status != "paid"` → выхода без изменений, поэтому статус не перезаписывается. Логика корректна, но второй вызов логируется как `deliver_unlock_no_path` и возвращает `reason: "no_path"`, что может путать в логах.  
**Рекомендация:** В задаче при `order.status == "delivered"` сразу возвращать `{"ok": True, "reason": "already_delivered"}` без вызова `mark_delivery_failed` и без лога «no_path».

---

## 4. Edge cases missed

### 4.1 callback_data длина (unlock_resend / unlock_check)
**Файл:** `app/bot/main.py`.  
**Факт:** `callback_data` в Telegram ограничен 64 байтами. `unlock_resend:{order_id}` при UUID (36 символов) — около 50 символов, укладывается. Запас есть, но при смене формата id нужно учитывать лимит.

### 4.2 return_url и длина start-параметра
**Файл:** `app/services/yookassa/client.py`, return_url.  
**Факт:** `start=unlock_done_<uuid>` — длина в норме. Следить при смене формата order_id (например, длинные токены).

### 4.3 Статус delivery_failed и кнопка «Получить фото снова»
**Файл:** `app/bot/main.py`, unlock_resend.  
**Факт:** Для статусов `paid`, `delivered`, `delivery_failed` показывается возможность переотправки. При `delivery_failed` повторная отправка может снова не пройти (например, файл удалён). Логика допустима; при повторной неудаче снова будет `delivery_failed`. Имеет смысл в логах и, при желании, в админке отслеживать заказы в `delivery_failed` для ручной проверки.

### 4.4 Исключение в choose_variant до ответа пользователю
**Файл:** `app/bot/main.py`.  
**Факт:** Весь блок unlock обёрнут в общий `try/except`; при любой ошибке пользователь видит общее «Ошибка. Попробуйте снова.» и `callback.answer` с алертом. Хорошо для стабильности, но теряется деталь ошибки. Для отладки стоит логировать полный traceback (уже есть logger.exception).

---

## 5. What must be fixed before release

**Обязательно:**

1. **deliver_unlock.py:** добавить `db.commit()` после успешного `mark_delivered` и после `mark_delivery_failed`; при исключении перед закрытием сессии — явный `rollback()` при необходимости, затем один раз `commit()` только для обновления статуса.
2. **webhooks.py:** убрать поиск заказа по `metadata.order_id`. Использовать только `get_by_yookassa_payment_id(payment_id)`. Если заказ не найден — не вызывать `mark_paid` и не ставить задачу, ответ 200.
3. **choose_variant (bot):** не показывать кнопку «Перейти к оплате» и не писать «Оплатите по ссылке», если `confirmation_url` пустой. В таком случае — сообщение об ошибке и не вызывать `set_payment_created`.
4. **choose_variant (existing_paid):** перед `get_variant_paths` проверять `take` на None; при отсутствии take — сообщение «Фото не найдено», без попытки отправить файл.
5. **choose_variant (existing_paid):** если файл не найден или не отправлен — не писать «Отправили ещё раз»; писать «Файл временно недоступен» и дать кнопку «Получить фото снова» или «В меню».

**Желательно до прода:**

6. Webhook: проверка источника/подписи ЮKassa (IP или подпись по документации).
7. deliver_unlock: при уже доставленном заказе (`order.status == "delivered"`) возвращать `{"ok": True, "reason": "already_delivered"}` без вызова `mark_delivery_failed` и без лога no_path.
8. Документировать/проверить, что API и Celery worker имеют доступ к одному и тому же `storage_base_path` (общий том или одинаковый путь).

---

## 6. Final verdict

**Ready для прода** после внесённых исправлений (см. ниже).

### Исправления внесены (в коде)

- **1.1** — В `deliver_unlock.py` добавлены `db.commit()` после `mark_delivered` и `mark_delivery_failed`, `db.rollback()` в except.
- **1.2** — В webhook поиск заказа только по `get_by_yookassa_payment_id(payment_id)`; fallback по `metadata.order_id` убран.
- **1.3** — В choose_variant при пустом `confirmation_url` или `yookassa_payment_id` не вызывается `set_payment_created`, показывается сообщение об ошибке без кнопки с пустым url.
- **2.2** — При existing_paid: если файл не отправлен (нет take/path/файла), показывается «Файл временно недоступен» и кнопка «Получить фото снова».
- **2.3** — Перед `get_variant_paths` проверяется `take_for_path` (take) на None.
- **3.2** — В deliver_unlock при `order.status == "delivered"` сразу возврат `{"ok": True, "reason": "already_delivered"}` без вызова `mark_delivery_failed`.

Условия для прода:
- Инфраструктура: API и Celery worker имеют доступ к одному и тому же `storage_base_path`.
- Рекомендуется внедрить проверку источника/подписи webhook ЮKassa (п. 6 раздела 5) в ближайшем релизе.
- **Переменные окружения (в .env на проде):** для оплаты по ссылке ЮKassa (unlock A/B/C) в окружении **бота** должны быть заданы (то же, что в `env.example`):
  ```
  # Для оплаты по ссылке: кнопка «Выбрать и оплатить A/B/C» в боте (разблокировка одного фото). Без них показывается старое меню пакетов.
  YOOKASSA_SHOP_ID=...
  YOOKASSA_SECRET_KEY=...
  ```
  Без них при нажатии «Выбрать и оплатить A/B/C» показывается старое меню пакетов вместо ссылки на оплату.
