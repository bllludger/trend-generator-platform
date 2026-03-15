# User Flow Tree

Документ восстановлен по коду: `app/bot/main.py`, `app/paywall/*`, `app/workers/tasks/*`, `app/api/routes/*`, `app/services/*`. Только AS-IS потоки.

---

## 1. Entry points

- **Telegram: /start** (`app/bot/main.py` → `@router.message(CommandStart())`)
  - Без аргумента → приветствие + главное меню (или подписка на канал, если `subscription_channel_username` и пользователь не подписан).
  - **Deep link `/start trend_<id>`** → `waiting_for_photo`, пресет тренда в state → пользователь отправляет фото.
  - **Deep link `/start theme_<id>`** → `preselected_theme_id` в state → после выбора пола и фото откроется эта тематика.
  - **Deep link `/start ref_<code>`** → реферальная атрибуция (ReferralService.attribute), затем приветствие.
  - **Deep link `/start src_<slug>` или `src_<slug>_c_<campaign>`** → трафик-атрибуция (traffic_source, campaign), затем приветствие.
  - **Deep link `/start unlock_done_<order_id>`** → экран после оплаты ЮKassa:
    - `order.status == "delivered"` → «Файл уже отправлен» + кнопки «Получить фото снова», «В меню».
    - `order.status == "paid"` → «Файл скоро придёт» + повторная постановка `deliver_unlock_file` при необходимости.
    - `order.status == "payment_pending"` → «Проверить оплату» + кнопка `unlock_check:{order_id}`.
    - `order.status in (canceled, failed, delivery_failed)` → сообщение об ошибке + «В меню».
    - Заказ не найден / не владелец → «Заказ не найден или не принадлежит вам».
  - Неизвестный/невалидный start-аргумент → «Неверная ссылка. Используйте меню бота.» (только внутри ветки unlock_done при пустом order_id).
- **Подписка на канал** (если включена): всё кроме `/start` и callback `subscription_check` блокируется до подписки (`SubscriptionMiddleware`).
- **Кнопка «Я подписался»** (`callback_data == SUBSCRIPTION_CALLBACK`) → проверка подписки → при успехе `waiting_for_photo` или приветствие с кнопкой «Создать фото».
- **Главное меню (ReplyKeyboard):**
  - «🔥 Создать фото» → `waiting_for_audience` (выбор ЦА).
  - «🔄 Сделать такую же» → `waiting_for_reference_photo`.
  - «🧩 Соединить фото» → `merge_waiting_count` (если фича включена), иначе «Сервис временно недоступен».
  - «🛒 Купить пакет» → экран магазина (`_show_shop`).
  - «👤 Мой профиль» → экран профиля (баланс, рефералка, кнопки «Оплата», «Поддержка»).
- **Команды:** `/help`, `/cancel`, `/trends`, `/terms`, `/paysupport`, `/deletemydata`.
- **Блокировки до обработки flow:** `SecurityMiddleware`: бан, suspend до даты, rate limit по часам; при превышении — сообщение и return без вызова handler.

**Файлы:** `app/bot/main.py` (CommandStart, SubscriptionMiddleware, SecurityMiddleware, main_menu_keyboard).

---

## 2. Main flow tree

### 2.1 Создать фото (trend flow)

- Entry: «🔥 Создать фото» или deep link `trend_<id>`.
  - «Создать фото» → **Step 0:** выбор ЦА (`waiting_for_audience`) → callback `audience:women|men|couples`.
  - ЦА «Мужчина» → offramp-текст (тренды для мужчин пока не поддерживаются) + меню.
  - ЦА «Женщина» / «Пара» → **Step 1:** `waiting_for_photo` → запрос фото (RULE_IMAGE_PATH), сохранение в state `photo_file_id`, `photo_local_path`.
- **Consent:** если `require_photo_consent` и пользователь не принял согласие → экран согласия; callback `accept_consent` → продолжение.
- Загрузка фото (F.photo / F.document в `waiting_for_photo`):
  - Валидация формата (JPG, PNG, WEBP), размера (`max_file_size_mb`).
  - **Collection:** если есть активная сессия-коллекция и ещё не задано `input_photo_path` → сохраняем фото в сессию, создаём первый Take, ставим `generate_take` → прогресс → по готовности переход в `viewing_take_result` (см. Take flow).
  - **Обычный flow:** показ тематик (callback `theme:<id>` или `theme:<id>:page`) или плоский список трендов; callback `trend:<id>` или `trend:custom` → при «Своя идея» переход в `waiting_for_prompt` (F.text).
- **Step 2:** выбор тренда → (опционально) выбор формата `format:<ar>`.
- **Step 3:** `_create_job_and_start_generation`:
  - Проверка квот: модератор → free_preview session; иначе активная платная сессия (`can_take`) или первый бесплатный take (`free_takes_used < 1`) или отказ «Бесплатное фото исчерпано / Лимит исчерпан».
  - Создание Take (session flow) или Job (legacy), отправка в Celery: `generate_take` (Take) или `generate_image` (Job).
  - Прогресс в чат (GENERATION_INTRO_IMAGE_PATH, шаги [🟩⬜⬜]), `state.clear()`.
- **Навигация в процессе:** `nav:themes`, `nav:trends`, `nav:menu`, `nav:profile` — сброс/переход без потери данных в state до момента «Генерация запущена».

**Результат генерации (Job, legacy):** воркер `generation_v2.generate_image` → при успехе `decide_access` → `prepare_delivery` (preview с watermark или full) → отправка фото в чат; при preview — клавиатура разблокировки (`build_unlock_markup`: unlock_tokens, unlock_hd при наличии 4K, unlock Stars). При ошибке — job.status=FAILED, пользователь видит сообщение об ошибке (через progress message edit или отдельное сообщение).

**Результат генерации (Take, session):** воркер `generate_take.generate_take` → 3 варианта A/B/C (preview + watermark); отправка в чат с кнопками «Выбрать и оплатить A/B/C», «Все 3 не подходят» → см. раздел Take / Favorites / Paywall.

**Файлы:** `app/bot/main.py` (handle_photo_step1, theme/trend/format callbacks, _create_job_and_start_generation); `app/workers/tasks/generation_v2.py` (generate_image, decide_access, prepare_delivery); `app/paywall/access.py`, `app/paywall/delivery.py`, `app/paywall/keyboard.py`.

### 2.2 Сделать такую же (copy style)

- Entry: «🔄 Сделать такую же» → `waiting_for_reference_photo`.
- Фото референса (F.photo / F.document) → сохранение в state (`reference_path`, `reference_file_id`) → `waiting_for_self_photo`.
- Своё фото → анализ (`analyze_input_photo`), создание Take с `take_type=COPY`, запуск `generate_take` → тот же Take flow (3 варианта, выбор, paywall/unlock).

**Файлы:** `app/bot/main.py` (copy_style handlers, copy_flow_origin в state).

### 2.3 Соединить фото (merge)

- Entry: «🧩 Соединить фото» → проверка фичи (PhotoMergeSettingsService) → `merge_waiting_count`.
- Callback `merge_count:2` или `merge_count:3` → `merge_waiting_photo_1` → по очереди фото 1, 2, (3) → создание PhotoMergeJob, обработка, результат в чат. `merge_cancel` → меню.

**Файлы:** `app/bot/main.py` (merge handlers); `app/services/photo_merge/`, `app/models/photo_merge_job.py`.

### 2.4 Take → выбор варианта → избранное → 4K (HD) / unlock

- После генерации Take приходят 3 варианта A/B/C с кнопками «💎 Выбрать и оплатить A/B/C» и «🔁 Все 3 не подходят».
- **choose:A|B|C** (`choose:take_id:variant`):
  - Добавление в избранное (FavoriteService.add_favorite), телеметрия `favorite_selected`, `trend_favorite_selected`.
  - Если сессия free_preview (или нет session) и не модератор → **Unlock по ЮKassa:** проверка `validate_can_create_unlock`, наличие уже оплаченного заказа; создание UnlockOrder, получение ссылки ЮKassa, сообщение с кнопками «Оплатить», «Проверить оплату», «В меню». Return URL: `https://t.me/{bot}?start=unlock_done_{order.id}`.
  - Если платная сессия / модератор → показ кнопок «💎 Открыть фото в 4K» (deliver_hd_one) и т.д.
- **Просмотр избранного:** «Избранное» из профиля или callback → экран избранного с выбором «Забрать 4K» (по балансу HD), «Забрать 4K альбомом», разблокировка по ЮKassa для бесплатных.
- **Доставка 4K:** `deliver_hd_one:{fav_id}` или `deliver_hd` / `deliver_hd_album` → Celery `deliver_hd.deliver_hd` (upscale + отправка файла); после последнего 4K в сессии — upsell (Trial → Neo Start/Pro или «Купить ещё 4K» / пакеты).

**Файлы:** `app/bot/main.py` (choose_variant, favorites, deliver_hd_one, deliver_hd, deliver_hd_album); `app/workers/tasks/deliver_hd.py`; `app/services/favorites/service.py`, `app/services/hd_balance/service.py`.

### 2.5 Unlock по ЮKassa (одно фото)

- Пользователь переходит по ссылке оплаты ЮKassa → оплата → редирект в бота `?start=unlock_done_{order_id}` (см. Entry points).
- Webhook `POST /webhooks/yookassa` при `payment.succeeded` → UnlockOrderService.mark_paid → Celery `deliver_unlock.deliver_unlock_file` → отправка файла в Telegram → mark delivered (или delivery_failed при ошибке).
- В боте: `unlock_check:{order_id}` — повторная проверка статуса платежа в ЮKassa и при успехе постановка `deliver_unlock_file`. `unlock_resend:{order_id}` — повторная отправка уже доставленного файла (если файл есть).

**Файлы:** `app/bot/main.py` (unlock_done handling, unlock_check, unlock_resend); `app/api/routes/webhooks.py` (yookassa); `app/workers/tasks/deliver_unlock.py`; `app/services/unlock_order/service.py`, `app/services/yookassa/client.py`.

---

## 3. Payment-related branches

### 3.1 Магазин и выбор способа оплаты

- **Магазин:** «🛒 Купить пакет» или `shop:open` → `_show_shop`: баланс (build_balance_tariffs_message) + кнопки пакетов (product ladder). Кнопки ведут на `paywall:{pack_id}` (не `buy:` в основном UI; `buy:` — legacy).
- **paywall:{pack_id}** → проверка pack enabled, trial_already_used → экран «Что получите + сумма», клавиатура способов оплаты: ЮMoney, Stars, «Другие способы», «Перевод на карту».
  - **ЮMoney:** `pay_method:yoomoney:{pack_id}` → send_invoice (RUB, provider_token) или `pay_method:yoomoney_link:{pack_id}` → createInvoiceLink.
  - **Stars:** `pay_method:stars:{pack_id}` → send_invoice (XTR).
  - **Перевод на карту:** `bank_transfer:start` → см. Bank transfer.
- **pre_checkout_query** → PaymentService.validate_pre_checkout (payload, user, amount) → ok=True | ok=False + error_message; при отказе телеметрия pay_failed, метрика pay_pre_checkout_rejected_total (reason).
- **successful_payment** (Message):
  - Payload `session:` → process_session_purchase (Stars) → создание/обновление сессии, при trial_already_used → refund Stars + сообщение.
  - Payload `yoomoney_session:` → process_session_purchase_yoomoney → аналогично; trial_already_used → сообщение «обратитесь в поддержку» (ручной возврат).
  - Payload `upgrade:` → process_session_upgrade (Stars).
  - Payload legacy (pack_id / unlock): credit_tokens или unlock (job_id) → при unlock отправка файла в чат, mark job unlocked; при ошибке credit — сообщение «обратитесь в поддержку». При исключении до commit — refund_star_payment (только Stars).

**Файлы:** `app/bot/main.py` (_show_shop, paywall_pack_selected, pay_method_*, handle_pre_checkout, handle_successful_payment); `app/services/payments/service.py` (process_session_purchase*, credit_tokens, validate_pre_checkout).

### 3.2 Bank transfer (оплата переводом)

- `bank_transfer:start` → список пакетов (из PRODUCT_LADDER_IDS), кнопки `bank_pack:{pack_id}`.
- `bank_pack:{pack_id}` → реквизиты (карта, комментарий/код «оплата № N»), state `bank_transfer_waiting_receipt`.
- Пользователь отправляет фото/документ чека → `_process_bank_receipt`: rate limit (10/час), analyze_receipt (LLM), проверка суммы/карты/свежести/дубликата (fingerprint). При успехе → process_session_purchase_bank_transfer или credit_tokens_manual → сообщение об успехе, state.clear(). При неудаче → счётчик попыток; после 3 попыток — текст поддержки + кнопки «Попробовать снова» (bank_transfer:retry), «В меню» (bank_transfer:cancel).
- `bank_transfer:cancel` → state.clear(), меню. `bank_transfer:retry` → сброс счётчика попыток.

**Файлы:** `app/bot/main.py` (bank_transfer_*, _process_bank_receipt); `app/services/llm/receipt_parser.py`; `app/services/bank_transfer/settings_service.py`.

### 3.3 Unlock одного фото (Stars / токены / 4K-кредиты)

- На превью (Job) кнопки: `unlock_tokens:job_id`, `unlock_hd:job_id`, `unlock:job_id` (Stars invoice).
- **unlock_tokens:** списание unlock_cost_tokens с баланса пользователя, запись payment (unlock_tokens), mark job unlocked, отправка original в чат.
- **unlock_hd:** списание 4K-кредита (ReferralService.spend_credits), mark job unlocked, отправка original.
- **unlock (Stars):** send_invoice (unlock_cost_stars), payload с job_id; successful_payment → credit_tokens(pack_id=unlock, tokens_granted=0), отправка файла, paywall_record_unlock.

**Файлы:** `app/bot/main.py` (unlock_photo_with_tokens, unlock_photo_with_hd_credits, unlock_photo); `app/paywall/config.py` (unlock cost).

---

## 4. Error and fallback branches

### 4.1 Security / доступ

- **Banned** → сообщение с ban_reason, handler не вызывается.
- **Suspended** (до suspended_until) → сообщение с датой и причиной; после истечения — сброс флага и продолжение.
- **Rate limit** (почасовая квота) → сообщение «Превышен лимит запросов», handler не вызывается. VIP (flags.VIP) может обходить при vip_bypass_rate_limit.
- **Subscription:** не подписан → везде кроме /start и subscription_check показывается экран подписки, handler не вызывается.

**Файлы:** `app/bot/main.py` (SecurityMiddleware, SubscriptionMiddleware).

### 4.2 Генерация (Job)

- **generation_v2:** trend_missing → job FAILED, сообщение в чат. generation_failed (ImageGenerationError) → FAILED, сообщение из e.detail. Необработанное исключение → FAILED, «Произошла ошибка при генерации. Попробуйте ещё раз.» После FAILED пользователь видит сообщение об ошибке; кнопки для повтора задаются в боте (error_action:menu, error_action:retry, error_action:replace_photo, error_action:choose_trend:job_id).
- **generate_take:** при падении варианта — retry варианта (до MAX_VARIANT_RETRIES); при полном падении — сообщение с кнопками «В меню», «error_action:menu».

**Файлы:** `app/workers/tasks/generation_v2.py`; `app/workers/tasks/generate_take.py`; `app/bot/main.py` (error_action:*).

### 4.3 Платёж

- **pre_checkout rejected** → pay_failed, pay_pre_checkout_rejected_total; пользователь видит error_message от Telegram.
- **successful_payment:** неверный payload / pack не найден → «Не удалось определить заказ», поддержка. Unlock: не владелец job / файла нет → refund + сообщение. Unlock уже разблокирован → refund + «Фото уже разблокировано. Средства возвращены.» Файл не готов → refund + «Файл ещё не готов…» или сообщение про поддержку (ЮMoney). credit_tokens ошибка → сообщение «обратитесь в поддержку».
- **Bank transfer:** неверная сумма/карта/дата/дубликат → сообщение о несовпадении, счётчик попыток; после 3 — поддержка + retry.

### 4.4 Unlock (ЮKassa) доставка

- deliver_unlock_file: order not found, no path → mark_delivery_failed при отсутствии пути; send_document exception → mark_delivery_failed. Пользователь приходит по unlock_done с status delivery_failed/canceled/failed → сообщение «Заказ отменён или завершён с ошибкой».

**Файлы:** `app/workers/tasks/deliver_unlock.py`; `app/bot/main.py` (unlock_done_*).

---

## 5. Retry and recovery flows

### 5.1 После ошибки генерации (Job)

- **error_action:menu** → state.clear(), главное меню.
- **error_action:retry** → state.clear(), текст «Нажмите «Создать фото» и выберите тренд».
- **error_action:replace_photo** → state.clear(), state → waiting_for_photo, показ правил фото (RULE_IMAGE_PATH).
- **error_action:choose_trend:job_id** → загрузка job, проверка владельца и file_ids; скачивание фото по file_id, state → waiting_for_trend с тем же фото, показ тематик/трендов (другой тренд для того же фото). Для copy flow (ref в file_ids) — отказ «Выберите новое фото».

**Файлы:** `app/bot/main.py` (handle_error_recovery, error_replace_photo, error_choose_trend).

### 5.2 Перегенерация (тот же тренд/настройки)

- **regenerate:job_id** → проверка job SUCCEEDED/FAILED, владелец; при copy flow (ref в file_ids) — отказ. Скачивание input по file_id, проверка квоты (free/copy или reserve tokens), создание нового job, отправка `generation_v2.generate_image` (не generate_take). Progress «Перегенерация с теми же настройками», state.clear().

**Файлы:** `app/bot/main.py` (regenerate_same).

### 5.3 Rescue flow (Take: «Все 3 не подходят»)

- **rescue:reject_set:take_id** → экран C1 (лицо не похоже, стиль, ещё варианты) или E (если уже был reroll/rescue photo).
- **rescue:reason:face** → экран F (другое фото, подсказка «Какое фото подойдёт»).
- **rescue:reason:style** → экран I (другой тренд).
- **rescue:reason:more** → reroll: создание нового Take с is_reroll=True, тот же тренд/фото → generate_take; при лимите reroll — экран E.
- **rescue:other_photo:take_id** → проверка лимита rescue по сессии/тренду; при превышении — экран I; иначе state → rescue_waiting_photo, data (rescue_take_id, rescue_trend_id, …).
- **rescue_waiting_photo** (F.photo / F.document) → _rescue_save_photo_and_start_take: новый Take с is_rescue_photo_replace=True → generate_take.
- **rescue:other_trend:** переход к выбору другого тренда (экран I). **rescue:photo_tip:** экран G (подсказка + другое фото).

**Файлы:** `app/bot/main.py` (_rescue_screen_*, rescue_reject_set, rescue_reason_*, rescue_other_photo, rescue_waiting_photo_*); `app/workers/tasks/generate_take.py` (кнопка «Все 3 не подходят»).

### 5.4 Unlock (ЮKassa)

- **unlock_check:order_id** → запрос статуса в ЮKassa; при succeeded → mark_paid, постановка deliver_unlock_file.
- **unlock_resend:order_id** → если status=delivered и файл есть → отправка файла в чат; иначе сообщение «Файл временно недоступен» или ошибка.

### 5.5 Bank transfer retry

- После 3 неудач — кнопка «Попробовать снова» (bank_transfer:retry) → сброс bank_receipt_attempts, приглашение отправить чек снова.

---

## 6. Admin / manual intervention flows

- **Admin API** (`app/api/routes/admin.py`): JWT-авторизация, все под префиксом `/admin`.
  - Security: настройки (rate limit, bypass, suspend), бан/разбан, список пользователей по статусу.
  - Users: список, поиск, детализация, grant pack (set_admin_grant_response + телеметрия), reset limits (free_takes_used, trial и т.д.).
  - Отправка сообщения пользователю: `send_telegram_to_user` (Celery task).
  - Packs, trends, themes, telegram messages, app settings, bank transfer settings, payments, audit, jobs (фильтр по статусу, в т.ч. FAILED/ERROR), copy style, cleanup, referral, traffic sources, ad campaigns, photo merge settings и др.
- **Влияние на user flow:** grant pack даёт сессию/пакет пользователю; reset limits сбрасывает лимиты; бан/suspend блокируют в боте через SecurityMiddleware; broadcast/send_user_message доставляют сообщения в Telegram.

**Файлы:** `app/api/routes/admin.py`; `app/workers/tasks/send_user_message.py`; `app/bot/main.py` (SecurityMiddleware читает User из БД).

---

## 7. Dead ends and ambiguous branches

### 7.1 Dead ends

- **ЦА «Мужчина»:** после выбора показывается offramp, переход только в меню; тренды для мужчин не выдаются.
- **Неверная ссылка /start:** в ветке unlock_done при пустом order_id после replace выводится «Неверная ссылка. Используйте меню бота.»; общий /start с неизвестным аргументом (не trend/theme/ref/src/unlock_done) не даёт отдельного «неверная ссылка» — идёт приветствие с theme_arg в state если есть.
- **Merge отключён:** единственный переход — «Сервис склейки фото временно недоступен», без состояния.
- **ЮKassa не настроен** при choose variant (free session): «Оплата по ссылке временно недоступна» + «В меню».
- **deliver_unlock:** при delivery_failed пользователь видит статус в unlock_done; явного «retry delivery» из бота нет (только повторный заход по ссылке или поддержка).

### 7.2 Ambiguities

- **Глубина навигации nav:menu / nav:profile:** при nav:menu state очищается; при возврате в «Создать фото» flow начинается с начала (audience). Нет «вернуться на шаг назад» внутри выбора тренда с сохранением только что загруженного фото в части сценариев — только error_action:choose_trend восстанавливает фото из job.
- **Session vs Job:** два параллельных пути генерации — по сессии (Take + коллекция/free_preview) и «классический» Job (format → generate_image). Условие выбора задаётся логикой «есть ли активная коллекция / free session» при первом фото и при выборе формата/тренда.
- **Trial already used (ЮMoney):** refund не автоматический, сообщение «обратитесь в поддержку» — ручной возврат; в коде помечено как yoomoney_trial_already_used_manual_refund_needed.
- **Paywall «Другие способы»:** callback pay_method:other только show_alert с текстом про ЮMoney/Stars/перевод; не ведёт на отдельный экран выбора.
- **Формат (aspect ratio):** в session/Take flow выбор формата может быть скрыт (дефолт из админки); в legacy flow кнопки format: остаются и создают Job.

---

## 8. Missing or unclear transitions

- **Явный переход из «успешная доставка unlock» в «создать ещё»:** после unlock_done с delivered есть только «Получить фото снова» и «В меню»; сценарий «сразу создать ещё» — через меню.
- **Состояние после bank_transfer:retry:** счётчик обнулён, но текст сообщения редактируется на «Отправьте скриншот ещё раз»; следующий шаг — снова отправить фото в bank_transfer_waiting_receipt (явно не переводится state, он уже установлен).
- **Переход из «Соединить фото» в магазин/профиль:** только через меню или inline «В меню»; в merge flow нет кнопки «Купить пакет» на экране.
- **Когда показывается paywall (превью) для Job:** решает paywall.access.decide_access (subscription_active, is_unlocked, reserved_tokens, used_free_quota, used_copy_quota); для Take — всегда превью до выбора варианта и оплаты/4K.
- **Idempotency:** при создании job используется IdempotencyStore (job:chat_id:message_id:format_key), чтобы не создавать дубли при двойном нажатии; при сбое возможен повтор — обрабатывается «Запрос уже обрабатывается».

---

## 9. Executive summary

- **Entry points:** Telegram /start (с deep links trend, theme, ref, src, unlock_done), главное меню (5 кнопок), команды. Обязательная подписка и security (бан, suspend, rate limit) режут поток до входа в сценарии.
- **Основные потоки:** (1) Создать фото: аудитория → фото → тематика/тренд → (формат) → генерация Job или Take; (2) Сделать такую же: референс → своё фото → Take; (3) Соединить фото: 2/3 человека → фото 1–3 → merge; (4) Магазин → paywall пакета → ЮMoney / Stars / банк; (5) Take: выбор варианта → избранное → 4K (deliver_hd) или unlock по ЮKassa/Stars/токенам/4K-кредитам.
- **Платежи:** Stars (session/upgrade/legacy pack/unlock), ЮMoney (session, invoice/link), банковский перевод (чек → распознавание → зачисление), ЮKassa для unlock одного фото (webhook → deliver_unlock).
- **Ошибки и повторы:** security/suspend/rate limit; FAILED генерации → error_action (menu, retry, replace_photo, choose_trend); rescue для Take (лицо/стиль/ещё варианты/другое фото/другой тренд); regenerate для Job; unlock_check/unlock_resend; bank_transfer:retry.
- **Админ:** настройки безопасности, пользователи, grant/reset, рассылка и отправка сообщений, настройки пакетов/трендов/платежей — влияют на доступ и лимиты в боте.
- **Неоднозначности:** два контура генерации (Session/Take vs Job); ручной возврат при trial ЮMoney; нет явного «retry delivery» для unlock при delivery_failed; навигация «назад» внутри создания фото ограничена (в основном через error_choose_trend).

Все переходы привязаны к обработчикам в `app/bot/main.py`, воркерам в `app/workers/tasks/`, paywall в `app/paywall/`, API в `app/api/routes/` и сервисам в `app/services/`.
