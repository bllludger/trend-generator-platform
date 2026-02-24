# Потоки данных в Trend Generator Platform

Документ описывает, как данные движутся через систему: от входа пользователя (Telegram, админка) до БД, очередей и внешних сервисов.

---

## 1. Поток генерации изображения (основной сценарий)

### 1.1 Вход: Telegram-бот

```
Пользователь → [Фото] → Бот (FSM: waiting_for_photo)
                ↓
         handle_photo_step1 / handle_photo_as_document_step1
         - Скачивание файла через bot.get_file() → сохранение в storage_base_path/inputs/{file_id}.jpg
         - state.set_data(photo_file_id, photo_local_path)
         - Реферальная атрибуция: /start ref_XXXX → ReferralService.attribute(user, code)
         - Показ тематик (ThemeService) и трендов (TrendService) из БД
                ↓
         Выбор тематики → select_theme_or_theme_page (callback theme:{id}:page)
         Выбор тренда или «Своя идея» → select_trend_or_idea (callback trend:{id} или custom)
         «Своя идея» → ввод текста → handle_custom_prompt → state (custom_prompt)
                ↓
         Выбор формата (1:1, 16:9, …) → select_format_and_generate (callback format:{key})
```

**Данные в FSM к моменту генерации:**

- `photo_file_id`, `photo_local_path` (или для copy-flow: `copy_photos_received`, `reference_path`)
- `trend_id` (или `TREND_CUSTOM_ID`), при необходимости `custom_prompt`
- `format_key` → `IMAGE_FORMATS[format_key]` (например `1024x1024`)

### 1.2 Создание задачи (Job) и отправка в Celery

**Где:** `app/bot/main.py` → `select_format_and_generate` (и аналогично `regenerate_same`).

1. **Проверки доступа:**
   - `UserService.get_or_create_user(telegram_id, …)` → User из БД (или создание).
   - Квота:
     - copy-flow: `user_service.try_use_copy_generation(user)` (лимит из SecuritySettings.copy_generations_per_user).
     - иначе: `user_service.try_use_free_generation(user)` (лимит free_generations_per_user).
   - Если квота не использована: `user_service.can_reserve(user, generation_cost_tokens)` и `user_service.hold_tokens(user, job_id, cost)` → списание с `User.token_balance`, запись в `TokenLedger` (HOLD).

2. **Создание Job:**
   - `JobService.create_job(user_id, trend_id, input_file_ids, input_local_paths, reserved_tokens, used_free_quota, used_copy_quota, job_id?, custom_prompt?, image_size?)`
   - Пишется в таблицу `jobs`: job_id, user_id, trend_id, status=CREATED, input_file_ids (Telegram file_id), input_local_paths (локальные пути), reserved_tokens, квоты.

3. **Аудит:** `AuditService.log(actor_type="user", actor_id=telegram_id, action="job_created", entity_type="job", entity_id=job_id, payload={...})`.

4. **Очередь:**
   - `celery_app.send_task("app.workers.tasks.generation_v2.generate_image", args=[job_id], kwargs={status_chat_id, status_message_id})`.

**Поток данных:** Telegram (фото + выбор тренда/формата) → Bot (FSM, UserService, JobService, AuditService) → PostgreSQL (users, jobs, token_ledger, audit_log) → Redis (Celery broker) → Worker.

---

## 2. Поток Celery: генерация изображения (worker)

**Вход:** задача `generate_image(job_id, status_chat_id, status_message_id)`.

### 2.1 Чтение и подготовка

1. **JobService.get(job_id)** → Job (user_id, trend_id, input_local_paths, reserved_tokens, used_free_quota, used_copy_quota).
2. **TrendService.get(trend_id)** → Trend (prompt_sections / scene_prompt, style_preset, negative_scene, prompt_model, prompt_size, prompt_temperature, prompt_seed, …).
3. **Сборка промпта:** `_build_prompt_for_job(db, job, trend)`:
   - если у тренда есть `prompt_sections` (Playground) — только секции;
   - иначе блоки: [INPUT], [TASK], [IDENTITY TRANSFER], [COMPOSITION], [SCENE], [STYLE], [AVOID], [SAFETY], [OUTPUT] из GenerationPromptSettingsService и TransferPolicy (trends scope).
4. **Входное изображение:** `job.input_local_paths[0]` (файл на диске).

### 2.2 Генерация

- **AppSettingsService.get_effective_provider(settings)** → выбор провайдера (IMAGE_PROVIDER / app settings).
- **ImageProviderFactory.create_from_settings(settings, provider)** → провайдер (openai, gemini, replicate, huggingface).
- **ImageGenerationRequest(prompt, model, size, negative_prompt, input_image_path, temperature, seed, image_size_tier)**.
- **generate_with_retry(provider, request, …)** → вызов API провайдера → `result.image_content` (bytes).

### 2.3 Сохранение и paywall

1. Сохранение сырого результата: `data/outputs/{job_id}_{attempt}.{ext}`.
2. **Paywall:**
   - **User** по job.user_id (subscription_active, hd_credits_balance, …).
   - **AccessContext(user_id, subscription_active, used_free_quota, used_copy_quota, is_unlocked=job.unlocked_at, reserved_tokens)**.
   - **decide_access(ctx)** → AccessDecision(show_preview, unlock_options):
     - subscription_active / is_unlocked / reserved_tokens > 0 → full (без превью);
     - иначе при used_free_quota или used_copy_quota → show_preview=True (watermark).
   - **prepare_delivery(decision, raw_path, out_dir, job_id, attempt)**:
     - при show_preview: копия _original, превью с watermark → preview_path, original_path;
     - иначе: original_path = raw_path.
3. **JobService:** либо `set_output_with_paywall(job, preview_path, original_path)` (is_preview=True), либо `set_output(job, original_path)`; затем `set_status(job, "SUCCEEDED")`.
4. При успехе: **JobService.clear_inputs(job)** (очистка input_local_paths для последующей очистки файлов).
5. При платной генерации (reserved_tokens): **capture_tokens(user, job_id, amount)** (TokenLedger CAPTURE, токены не возвращаются); при ошибке — **release_tokens**.

### 2.4 Уведомление пользователя

- Удаление сообщения «Генерация начинается...» (status_chat_id, status_message_id).
- **TelegramClient.send_photo(chat_id, photo_path, reply_markup)**. При превью — reply_markup от **build_unlock_markup(job_id, unlock_options, show_hd_credits)** (кнопки «Токены», «Stars», HD credits при наличии).

**Поток данных:** Redis (задача) → Worker → PostgreSQL (Job, User, Trend, настройки) → внешний API (OpenAI/Gemini/Replicate/HF) → диск (outputs) → Telegram (фото + кнопки).

---

## 3. Разблокировка фото (paywall)

Пользователь видит превью с watermark и кнопки «Разблокировать токенами / Stars / HD credits».

### 3.1 Разблокировка токенами

**Обработчик:** `unlock_photo_with_tokens` (callback `unlock_tokens:{job_id}`).

1. Проверка: Job существует, user — владелец, job.is_preview, есть output_path_original.
2. **PaymentService.** расчёт стоимости разблокировки (get_unlock_cost_tokens).
3. **payment_service.record_unlock_tokens(user.id, job_id, unlock_cost):**
   - списание с User.token_balance;
   - запись Payment(pack_id="unlock", tokens_amount=..., payload=job_id);
   - Job: unlocked_at, unlock_method="tokens".
4. **paywall_record_unlock(job_id, user_id, "tokens", price_tokens=...)** (логирование).
5. Отправка пользователю файла по output_path_original (answer_document).

### 3.2 Разблокировка HD credits (реферальные бонусы)

**Обработчик:** `unlock_photo_with_hd_credits` (callback `unlock_hd:{job_id}`).

1. Проверка job, user, hd_credits_balance, hd_credits_debt.
2. **ReferralService.spend_hd_credits(user, 1)** — уменьшение hd_credits_balance, увеличение hd_credits_debt.
3. Job: unlocked_at, unlock_method (например "hd_credits").
4. record_unlock(…, method="tokens" или отдельный путь для HD).
5. Отправка оригинала пользователю.

### 3.3 Разблокировка через Stars (покупка пака «Unlock»)

Реализовано через Telegram Payments (см. раздел 4). В successful_payment при pack_id=unlock привязывается к job_id из payload, выставляется job.unlocked_at и отправляется оригинал.

**Поток данных:** Callback от кнопки → Bot → PaymentService / ReferralService → PostgreSQL (users, jobs, payments) → Telegram (документ с фото).

---

## 4. Платежи (Stars и банковский перевод)

### 4.1 Telegram Stars (паки токенов или unlock)

**Pre-checkout:**

- **handle_pre_checkout:** payload (например `pack_id:starter` или `unlock:{job_id}`) → **PaymentService.validate_pre_checkout(payload, telegram_id)** (проверка пака, лимиты покупок, для unlock — проверка job и владельца). Ответ в Telegram: ok=True/False.

**Successful payment:**

- **handle_successful_payment:** message.successful_payment (telegram_payment_charge_id, total_amount, invoice_payload).
- **PaymentService.record_stars_payment(telegram_id, charge_id, payload, amount, provider_payment_charge_id):**
  - идемпотентность по charge_id;
  - разбор payload → pack_id или unlock+job_id;
  - создание **Payment** (user_id, pack_id, stars_amount, payload, charge_id, ...);
  - начисление **User.token_balance** (+ pack.tokens или только разблокировка);
  - при pack: **User.total_purchased** += 1;
  - при unlock: привязка к job, **job.unlocked_at**, отправка оригинала, **paywall_record_unlock**.
- **Реферальный бонус:** если у user есть referred_by_user_id, **ReferralService.create_bonus(referrer, user, payment)** — создаётся **ReferralBonus** (status=pending, available_at = now + hold_hours). Лимиты: min_stars, daily/monthly limit, не для pack_id=unlock.

**Поток данных:** Telegram (pre_checkout_query, successful_payment) → Bot → PaymentService → PostgreSQL (payments, users, jobs, referral_bonuses).

### 4.2 Банковский перевод

1. Пользователь нажимает «Не знаю как купить Stars» → **bank_transfer_start**: показ реквизитов, генерация уникального кода (redis incr `bank_transfer:receipt_code_seq`), state → bank_transfer_waiting_receipt.
2. Пользователь отправляет фото чека (или документ) → обработчик (F.photo / F.document):
   - сохранение файла;
   - вызов сервиса распознавания чека (vision): сумма, номер карты, комментарий и т.д.;
   - запись **BankTransferReceiptLog** (match_success, extracted_amount_rub, pack_id, payment_id, …);
   - при успехе: **PaymentService.record_bank_transfer_payment(telegram_id, reference, pack_id, amount_rub, …)** — создание Payment(payload=f"bank_transfer:{reference}"), начисление токенов;
   - при успехе: **ReferralService.create_bonus** при наличии реферера (аналогично Stars).
3. Ответ пользователю: успех или «сумма/реквизиты не совпали».

**Поток данных:** Telegram (фото чека) → Bot → Vision API / настройки BankTransfer → PostgreSQL (bank_transfer_receipt_log, payments, users, referral_bonuses).

---

## 5. Реферальная программа

### 5.1 Атрибуция

- При **/start ref_XXXX** (referrer_code в deep link): после создания/получения User вызывается **ReferralService.attribute(referral_user, referrer_code)**.
- Условия: у пользователя ещё нет referred_by_user_id; код валиден; не сам себя; пользователь создан в пределах attribution_window_days.
- Запись: **User.referred_by_user_id**, **User.referred_at**.

### 5.2 Создание бонуса

- После квалифицирующей покупки (Stars или банковский перевод) вызывается **ReferralService.create_bonus(referrer, referral, payment)**.
- Условия: payment.stars_amount >= min_pack_stars, pack_id != "unlock", лимиты (daily/monthly), referrer != referral.
- Создаётся **ReferralBonus**: referrer_user_id, referral_user_id, payment_id, status=pending, credits, available_at = now + hold_hours.

### 5.3 Обработка pending → available (Celery Beat)

- **Таск:** `app.referral.tasks.process_pending_bonuses` (каждые 30 минут по crontab).
- Выборка: ReferralBonus где status=pending и available_at <= now.
- **ReferralService.process_pending()** — перевод в status=available, начисление **User.hd_credits_balance** рефереру.
- Уведомление реферера в Telegram: «Бонус доступен: +HD credits».

**Поток данных:** Deep link / Payment → ReferralService → PostgreSQL (users, referral_bonuses) → Celery Beat → process_pending_bonuses → User.hd_credits_balance, Telegram.

---

## 6. Админка (React SPA) → API

Админка ходит в **FastAPI** по базовому URL (прокси или напрямую), с JWT после **POST /admin/auth/login**.

### 6.1 Аутентификация

- **POST /admin/auth/login** { username, password } → проверка verify_admin_credentials → **create_access_token** → { access_token, token_type, user }.
- Дальнейшие запросы: заголовок **Authorization: Bearer &lt;token&gt;**.
- **GET /admin/auth/me** → текущий пользователь.

### 6.2 Основные потоки данных админки

| Область        | Методы API (примеры) | Данные |
|----------------|----------------------|--------|
| Security       | GET/PUT /admin/security/settings, GET /admin/security/overview, GET /admin/security/users, POST ban/suspend/rate-limit/moderator | SecuritySettings, User list, модерация |
| Users          | GET /admin/users, GET /admin/users/analytics | Список, аналитика |
| Transfer policy| GET/PUT /admin/settings/transfer-policy | Глобальные и трендовые правила переноса |
| Master prompt  | GET/PUT /admin/settings/master-prompt | INPUT, TASK, SAFETY, default model/size/format |
| Telegram texts | GET /admin/telegram-messages, POST bulk, POST reset | Шаблоны сообщений бота |
| Telemetry      | GET /admin/telemetry, trends, history, product-metrics | Дашборд, тренды, история |
| Bank transfer  | GET/PUT /admin/bank-transfer/settings, GET receipt-logs, GET receipt-logs/:id/file | Реквизиты, логи чеков |
| Payments       | GET /admin/payments, GET stats, POST refund | Список платежей, возвраты |
| Packs          | GET /admin/packs, PUT/POST/DELETE packs/:id | Токен-паки |
| Themes         | GET/POST/PUT/PATCH/DELETE /admin/themes | Тематики трендов |
| Trends         | GET/POST/PUT/DELETE /admin/trends, example/style-reference upload, prompt-preview, order | Тренды, промпты, примеры |
| Playground     | GET /admin/playground/config, PUT trends/:id, POST /admin/playground/test | Конфиг промпта, сохранение в тренд, тест генерации (config + image1 → image_url) |
| Audit          | GET /admin/audit, GET /admin/audit/stats | Лог действий |
| Broadcast      | GET /admin/broadcast/preview, POST /admin/broadcast/send | Предпросмотр числа получателей, отправка → Celery broadcast_message.delay(text, include_blocked) |
| Jobs           | GET /admin/jobs, GET stats, GET jobs/:id | Задачи генерации |
| Copy style     | GET/PUT /admin/settings/copy-style | Настройки «Сделать такую же» |
| Cleanup        | GET /admin/cleanup/preview, POST /admin/cleanup/run | Превью и запуск очистки временных файлов (вызов cleanup-сервиса или внутренний сервис) |
| Referrals      | GET /admin/referrals/stats, GET /admin/referrals/bonuses, POST bonuses/:id/freeze | Статистика, бонусы, заморозка |

**Поток данных:** Browser → React (api.ts, axios + JWT) → FastAPI (admin routes) → сервисы (SecuritySettingsService, TrendService, PaymentService, ReferralService, CleanupService, …) → PostgreSQL; при broadcast → Celery → Redis → Worker → Telegram.

---

## 7. Публичный API и вспомогательные сервисы

### 7.1 Публичный список трендов

- **GET /trends** (без авторизации): **TrendService.list_active()** → список TrendOut (id, name, emoji, description, max_images, enabled, order_index). Используется для отображения трендов (например, в боте данные могут кэшироваться или запрашиваться из БД напрямую; в коде бота тренды идут через TrendService из БД).

### 7.2 Playground (админ)

- **GET /admin/playground/config** — конфиг по умолчанию из GenerationPromptSettingsService (секции Scene/Style/Avoid).
- **PUT /admin/playground/trends/:id** — сохранение конфига (PlaygroundPromptConfig) в Trend (prompt_sections, model, size, format, temperature, seed, image_size_tier).
- **POST /admin/playground/test** — multipart: config (JSON), image1 (опционально). Сборка промпта, вызов ImageProviderFactory + generate_with_retry, ответ { image_url (data URL) } или { error }.

### 7.3 Cleanup-сервис (отдельный процесс)

- Отдельное приложение **app.cleanup.main** (порт 8001), защита заголовком **X-Admin-Key**.
- **POST /cleanup/run?older_than_hours=...** → **CleanupService.cleanup_temp_files(older_than_hours)**: удаление временных файлов (inputs/outputs старше N часов) и при необходимости обновление/очистка записей.

**Поток данных:** Админка или скрипт → Cleanup API → CleanupService → ФС (удаление файлов), при необходимости БД.

---

## 8. Сводная схема хранилищ и очередей

| Хранилище   | Что хранится |
|-------------|--------------|
| **PostgreSQL** | users, jobs, trends, themes, packs, payments, token_ledger, referral_bonuses, bank_transfer_receipt_log, bank_transfer_settings, security_settings, audit_log, настройки промптов (master, transfer, app, copy-style), telegram_messages (шаблоны) |
| **Redis**      | Celery broker + result backend; rate_limit:{user_id}:{YYYYMMDDHH}; idempotency (job:...); bank_transfer:receipt_code_seq; login rate limit (auth) |
| **Диск**       | storage_base_path/inputs (входящие фото), data/generated_images/outputs (результаты: raw, _preview, _original) |
| **Внешние API**| Telegram Bot API; OpenAI / Gemini (Vertex) / Replicate / Hugging Face (генерация изображений); при банковском переводе — Vision API для чека |

---

## 9. Важные зависимости порядка

1. **Генерация:** Job создаётся с актуальными input_local_paths; воркер читает файлы с диска до вызова провайдера; после успеха clear_inputs для последующей очистки.
2. **Токены:** HOLD при создании job → CAPTURE при успехе генерации или RELEASE при ошибке; разблокировка токенами списывает баланс и фиксирует unlocked_at.
3. **Реферальный бонус:** создаётся только после реального платежа (Stars или банковский перевод); переход из pending в available — только по истечении hold в process_pending_bonuses.
4. **Paywall:** решение о превью/full принимается в воркере по состоянию User и Job на момент завершения генерации; последующее разблокирование обновляет Job (unlocked_at, unlock_method) и отправляет оригинал из output_path_original.
