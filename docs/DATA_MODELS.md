# Ключевые сущности (модели данных)

Краткий обзор основных сущностей БД и связей для онбординга и отладки. Полные определения — в `app/models/`.

## Основные сущности

| Сущность | Таблица | Назначение |
|----------|---------|------------|
| **User** | `users` | Пользователь Telegram: балансы (token_balance), лимиты (free_generations_used, copy_generations_used), безопасность (ban, suspend, rate_limit), реферальный код, трафик (traffic_source, campaign). |
| **Session** | `sessions` | Активная фотосессия после покупки пакета: pack_id, takes_limit / takes_used, hd_limit / hd_used. Для коллекций: playlist, current_step, input_photo_path. Связь: user_id → User. |
| **Take** | `takes` | Один «снимок» в контексте сессии: 3 варианта (A/B/C), превью и оригиналы, тип (TREND / COPY). Связи: user_id → User, session_id → Session (опционально), trend_id → Trend. |
| **Job** | `jobs` | Legacy-задача генерации одного изображения (без сессии): trend_id, статус, input/output пути, флаги unlock (unlocked_at, unlock_method). Связь: user_id → User. |
| **Payment** | `payments` | Транзакция оплаты (Stars/ЮMoney): user_id, pack_id, stars_amount, amount_kopecks, tokens_granted, session_id/job_id, payload. Уникален telegram_payment_charge_id (рефанды). |
| **UnlockOrder** | `unlock_orders` | Заказ разблокировки одного фото по ЮKassa: telegram_user_id, take_id, variant (A/B/C), amount_kopecks, status (created → payment_pending → paid → delivered). yookassa_payment_id — связь с платёжом ЮKassa. |
| **PackOrder** | `pack_orders` | Заказ покупки пакета по ссылке ЮKassa: telegram_user_id, pack_id, amount_kopecks, status (created → payment_pending → paid → completed). yookassa_payment_id — связь с платёжом. |
| **Favorite** | `favorites` | Выбранный пользователем вариант (Take): user_id, take_id, variant, флаг «забрать в HD». Используется для доставки 4K и экрана «Избранное». |
| **Trend** | `trends` | Тренд генерации: name, описание, промпты, настройки. Связь с Theme (тематика). |
| **Theme** | `themes` | Тематика трендов (категория). |

## Связи (для отладки)

- **User** → много **Session** (активная обычно одна на пользователя по логике приложения).
- **User** → много **Take**, **Job**, **Payment**, **UnlockOrder**, **PackOrder**, **Favorite**.
- **Session** → много **Take** (снимки в рамках сессии).
- **Take** → один **UnlockOrder** на вариант при оплате по ссылке (по take_id + variant).
- **UnlockOrder** / **PackOrder** идентифицируются в webhook ЮKassa по **yookassa_payment_id**.

## Статусы

- **Take**: `generating` → по готовности варианты заполнены; ошибки в error_code / error_variants.
- **Job**: `PENDING` → `SUCCEEDED` / `FAILED`; разблокировка — unlocked_at не null.
- **UnlockOrder**: `created` → `payment_pending` → `paid` → `delivered` (или `canceled`, `failed`, `delivery_failed`).
- **PackOrder**: `created` → `payment_pending` → `paid` → `completed` (или `canceled`, `failed`).

## Где смотреть в коде

- Модели: `app/models/*.py` (user, session, take, job, payment, unlock_order, pack_order, favorite, trend, theme и др.).
- Сервисы: `app/services/` (users, takes, payments, unlock_order, pack_order, favorites, hd_balance и т.д.).
