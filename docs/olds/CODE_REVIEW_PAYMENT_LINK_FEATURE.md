# Code review: оплата по ссылке (createInvoiceLink)

## 1. Critical bugs

### 1.1 Коллизия хендлеров: «Оплатить по ссылке» ведёт в sendInvoice

**Суть:** `callback_data` для кнопки «Оплатить по ссылке» — `pay_method:yoomoney_link:{pack_id}`. Хендлер `pay_method_yoomoney` зарегистрирован первым и с фильтром `F.data.startswith("pay_method:yoomoney:")`. Строка `"pay_method:yoomoney_link:neo_start"` начинается с `"pay_method:yoomoney:"`, поэтому обрабатывается хендлером **pay_method_yoomoney**, а не **pay_method_yoomoney_link**. Пользователь, нажав «Оплатить по ссылке», получает инвойс в чате (sendInvoice), а не сообщение со ссылкой.

**Исправление (внесено):** У хендлера `pay_method_yoomoney` фильтр сужён до  
`F.data.startswith("pay_method:yoomoney:") & ~F.data.startswith("pay_method:yoomoney_link:")`,  
чтобы callback `pay_method:yoomoney_link:*` обрабатывался только хендлером `pay_method_yoomoney_link`.

---

## 2. High-risk issues

### 2.1 Нет явного ответа на callback при частичных early return

В `pay_method_yoomoney_link` при раннем выходе (пакет не найден, trial уже использован) вызывается `await callback.answer(...)` и `return` — всё ок. При успехе вызываются `callback.message.answer(...)` и `callback.answer()`. В блоке `except` тоже есть `callback.answer()`. Риск: если внутри первого `with get_db_session()` произойдёт исключение до любого `callback.answer()`, Telegram может показать «загрузку» до таймаута. Сейчас весь код после проверки pack/user обёрнут в один `try`, так что необработанное исключение попадёт в общий `except Exception` и пользователь получит ответ. Оценка: низкий риск при текущей структуре.

### 2.2 Аналитика pay_failed при отклонении pre_checkout

В `handle_pre_checkout` при отклонении раньше всегда передавался `payment_method: "stars"`. **Исправлено:** метод выставляется по payload (`yoomoney` для `yoomoney_session:...`, иначе `stars`).

---

## 3. Logic problems

### 3.1 Парсинг pack_id через split(":")[-1]

Используется `callback.data.split(":")[-1]` для извлечения `pack_id`. Для текущих значений `PRODUCT_LADDER_IDS` (`trial`, `neo_start`, `neo_pro`, `neo_unlimited`) колонов в id нет, парсинг корректен. Если в будущем появится pack_id с двоеточием, значение будет неверным. Для текущего набора — ок, на будущее лучше явно парсить по префиксу, например `callback.data.split(":", 2)[2]` для `pay_method:yoomoney_link:pack_id`.

### 3.2 Двойная оплата одного пакета по двум ссылкам

Пользователь может нажать «Оплатить по ссылке» дважды, получить две ссылки и оплатить обе. Два разных `provider_payment_charge_id` → два платежа и две сессии. Идемпотентность по `charge_id` есть, но ограничения «один пакет — одна покупка» нет (кроме trial). Для платных пакетов это может быть осознанное решение (доп. квота). Стоит явно решить на продуктовом уровне.

---

## 4. Edge cases missed

- **Истечение ссылки:** Ссылка createInvoiceLink может иметь TTL на стороне Telegram. Поведение при переходе по протухшей ссылке на нашей стороне не обрабатывается (ошибка у Telegram) — приемлемо.
- **Отмена оплаты по ссылке:** Пользователь перешёл по ссылке и закрыл окно без оплаты. Никакого колбэка нет, дополнительная логика не требуется.
- **provider_token пустой:** Проверка есть в начале хендлера, пользователь видит «Оплата ЮMoney временно недоступна» — ок.
- **Длина callback_data:** Лимит Telegram 64 байта. `pay_method:yoomoney_link:` + самый длинный pack_id = 40 символов — в пределах лимита.

---

## 5. What must be fixed before release

1. ~~**Обязательно:** Исправить коллизию хендлеров (п. 1.1).~~ **Сделано.**
2. ~~**Желательно:** Корректный `payment_method` в аналитике при отклонении pre_checkout.~~ **Сделано.**

---

## 6. Final verdict

**Ready** — критический баг с коллизией хендлеров и аналитика pay_failed исправлены. Кнопка «Оплатить по ссылке» обрабатывается хендлером `pay_method_yoomoney_link` и выдаёт ссылку. Оставшиеся замечания (парсинг pack_id при возможном появлении двоеточия в id, политика двойной покупки) не блокируют релиз.
