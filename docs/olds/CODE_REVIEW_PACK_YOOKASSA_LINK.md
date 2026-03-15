# Code review: покупка пакетов по ссылке ЮKassa

## 1. Critical bugs

### 1.1 Orphan PackOrder при сбое create_order (исправлено в коде)
**Проблема:** В `PackOrderService.create_order()` после `self.db.add(order)` и `self.db.flush()` при любом сбое (ЮKassa не настроена, YooKassaClientError, отсутствие confirmation_url) метод возвращает `(None, None)`, но заказ уже в сессии. Контекст `get_db_session()` при нормальном выходе делает `db.commit()` — в БД остаётся заказ со статусом `created` без `yookassa_payment_id` (мусор, повторные попытки создают новые заказы).

**Исправление:** На всех путях отказа после добавления заказа вызывать `self.db.delete(order)`, `self.db.flush()` и только потом возвращать `(None, None)`.

### 1.2 start=pack_done_: статус "paid" показывается как успех (исправлено в коде)
**Проблема:** В обработчике `start=pack_done_` для статусов `("paid", "completed")` показывается одно и то же поздравление. При статусе `paid` webhook мог уже сделать `mark_paid`, но ещё не выполнить `process_session_purchase_yookassa_link` или `mark_completed` (например, падение между коммитами). Сессии тогда нет, `remaining = 0` — пользователь видит «Доступно фото: 0» и непонятное состояние.

**Исправление:** Показывать полное поздравление только при `status == "completed"`. При `status == "paid"` показывать «Оплата принята, пакет активируется…» и кнопку «Проверить оплату».

---

## 2. High-risk issues

### 2.1 Webhook: process_session_purchase_yookassa_link без коммита до mark_completed
**Риск:** После `mark_paid` и `db.commit()` вызывается `process_session_purchase_yookassa_link()` — он создаёт Payment и Session в той же сессии, но не коммитит. Коммит делается только после `mark_completed`. Если между ними исключение (например, при отправке сообщения в Telegram в другом коде), FastAPI закроет сессию — откат. В итоге: PackOrder остаётся `paid`, а Payment/Session не созданы. При следующем «Проверить оплату» или повторном webhook идемпотентность восстановит активацию — данные не теряются, но первый раз пользователь может не получить сообщение.

**Рекомендация:** После успешного `process_session_purchase_yookassa_link` сразу делать `db.commit()` (как сейчас после `mark_completed`). Отправку сообщения в Telegram выполнять после коммита и не включать в ту же транзакцию. Текущая реализация уже так и делает (commit до _send_pack_success_message), риск только в падении между commit и send — тогда заказ уже completed, повторный webhook ничего не изменит, пользователь просто не получит одно сообщение. Приемлемо.

### 2.2 Двойной коммит в pack_check
В `pack_check_callback` вызывается явный `db.commit()` после `mark_completed`, а при выходе из `with get_db_session()` контекст снова делает `commit()`. Второй коммит пустой — лишний, но не ошибочный. Можно оставить как есть или убрать явный `db.commit()` для единообразия.

### 2.3 TelegramClient.send_message и reply_markup
В webhook передаётся `reply_markup=json.dumps({"inline_keyboard": rows})` (строка). В `TelegramClient.send_message` тип указан как `dict | None`, но при отправке через `json=data` строка сериализуется в JSON-строку — Telegram API принимает. В других местах (send_photo, send_document) для reply_markup делают `json.dumps(reply_markup)`. Для send_message в клиенте json.dumps не вызывается — то есть клиент допускает и dict, и строку; при передаче строки всё корректно. Риск низкий.

---

## 3. Logic problems

### 3.1 pack_check: статус "paid"
В `pack_check_callback` условие `if pack_order.status not in ("payment_pending", "paid")` — при `paid` мы идём проверять платёж в ЮKassa и при succeeded вызываем `process_session_purchase_yookassa_link`. Если webhook уже выполнил активацию, метод вернёт existing — ок. Если webhook ещё не дошёл, активация произойдёт здесь — ок. Логика верная.

### 3.2 Отсутствие перехода PackOrder в canceled/failed
Статусы `canceled` и `failed` в модели и в start=pack_done_ обрабатываются, но нигде не выставляются. ЮKassa может присылать, например, payment.canceled — мы его не обрабатываем. Заказ остаётся в `payment_pending` навсегда. Для первой версии допустимо: пользователь может нажать «Выбрать тариф» и создать новый заказ. В перспективе можно обрабатывать отмену в webhook и ставить `canceled`/`failed`.

---

## 4. Edge cases missed

### 4.1 Пакет отключён (enabled=False) после создания заказа
При активации вызывается `get_pack(pack_id)` — в PaymentService фильтра по `enabled` нет, пакет находится. Активация идёт по коду пакета (neo_start и т.д.), не по флагу. Ок.

### 4.2 Два быстрых клика по одному тарифу
Первый запрос создаёт заказ и коммитит. Второй находит тот же заказ через `get_pending_order` и показывает ту же ссылку. Если оба запроса параллельны, возможны два заказа для одного user+pack — оба payment_pending. Пользователь может оплатить один; второй так и останется в ожидании. Критичной ошибки нет, при желании можно добавить частичный уникальный индекс по (telegram_user_id, pack_id) WHERE status = 'payment_pending'.

### 4.3 Истечение ссылки ЮKassa
Ссылка на оплату может иметь срок жизни. Если пользователь вернулся по pack_done_ через долгое время и платёж уже отменён/истёк, мы всё равно показываем «Платёж обрабатывается» и «Проверить оплату». По нажатию get_payment вернёт не succeeded — покажем «Платёж ещё обрабатывается». Не идеально, но не ломает сценарий. При необходимости можно по статусу из get_payment выставлять PackOrder в canceled.

### 4.4 pack_id в PRODUCT_LADDER_IDS, но пакет удалён из БД
Маловероятно для neo_start/neo_pro/neo_unlimited. Если pack удалён, `get_pack(pack_id)` в create_order вернёт None — description будет "Оплата пакета {pack_id}", заказ создаётся. При активации get_pack снова может вернуть None — в process_session_purchase_yookassa_link при отсутствии pack возвращается (None, None, None, 0). Webhook тогда не активирует пакет и не шлёт поздравление. Нужно не допускать удаления этих пакетов из админки (бизнес-правило).

---

## 5. What must be fixed before release

- **Обязательно:** Устранение orphan PackOrder в create_order (удаление заказа на путях отказа после add+flush).
- **Обязательно:** В start=pack_done_ различать "paid" и "completed": при "paid" не показывать поздравление с «Доступно фото», а показывать «Оплата принята, пакет активируется» и «Проверить оплату».
- Желательно: не полагаться на то, что pack_check делает явный commit — либо оставить один явный commit и не дублировать в контексте, либо убрать явный commit (достаточно commit при выходе из with). Не блокер.

---

## 6. Final verdict

Два обязательных исправления внесены в коде:
- В `PackOrderService.create_order` при любом сбое после добавления заказа вызывается `_rollback_order()` (delete + flush), мусорных записей не остаётся.
- В `start=pack_done_` полное поздравление показывается только при `status == "completed"`; при `status == "paid"` показывается «Оплата принята, пакет активируется…» и кнопка «Проверить оплату».

**Ready** для выката в прод с приёмлемым риском. Остальные пункты (обработка payment.canceled, частичный уникальный индекс на дубликаты) — по желанию в следующих итерациях.
