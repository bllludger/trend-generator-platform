# Telegram Bot Business Follow-Up

## Scope

Этот документ описывает только Telegram-бота проекта `ai_slop_2`.

Что входит в scope:

- пользовательский Telegram flow
- дерево модулей, связанных с ботом
- продуктовая и платежная логика
- доставка результата пользователю
- риски и узкие места текущей реализации

Что исключено:

- `admin-frontend`
- админские страницы и админские UX-сценарии
- не связанные с ботом части API

---

## 1. Executive Summary

Проект реализует Telegram-бота для AI-фотогенерации с тремя основными пользовательскими сценариями:

- `Создать фото`
- `Сделать такую же`
- `Соединить фото`

Ключевая бизнес-модель сейчас построена вокруг двух монетизационных путей:

- продажа session-паков с лимитом генераций и лимитом 4K-выдач
- разовая разблокировка одного выбранного фото

Бесплатный вход в продукт организован через free preview: пользователь получает превью-результат, затем выбирает лучший вариант и либо:

- покупает пакет
- оплачивает unlock одного фото
- использует уже имеющийся платный 4K-доступ

Текущий production-контур оплаты ориентирован на `YooKassa` и `ЮMoney`. Legacy-ветки для `Stars` и `bank transfer` частично остаются в коде, но являются вторичными или отключенными в UX.

---

## 2. Bot Entry Points And Runtime

Основная точка входа бота:

- [app/bot/main.py](/root/ai_slop_2/app/bot/main.py)

Запуск:

- `main()` поднимает polling-бота, Redis FSM storage, middleware, router и metrics server
- используется `long polling`, а не webhook

Связанные runtime-компоненты:

- [app/core/config.py](/root/ai_slop_2/app/core/config.py)
- [app/core/celery_app.py](/root/ai_slop_2/app/core/celery_app.py)
- [app/db/session.py](/root/ai_slop_2/app/db/session.py)
- [docker-compose.yml](/root/ai_slop_2/docker-compose.yml)
- [start.sh](/root/ai_slop_2/start.sh)

Инфраструктурная зависимость бота:

- PostgreSQL
- Redis
- Celery worker
- Telegram Bot API
- YooKassa / ЮMoney
- AI providers для генерации и vision-задач

---

## 3. Module Tree Of The Bot

### 3.1 Core Orchestrator

- [app/bot/main.py](/root/ai_slop_2/app/bot/main.py)

Назначение:

- все команды и callback handlers
- FSM состояния
- главное меню
- flow генерации
- flow покупок
- flow избранного и 4K
- интеграция с Celery-задачами

### 3.2 Product Catalog And Session Domain

- [app/services/themes/service.py](/root/ai_slop_2/app/services/themes/service.py)
- [app/services/trends/service.py](/root/ai_slop_2/app/services/trends/service.py)
- [app/services/sessions/service.py](/root/ai_slop_2/app/services/sessions/service.py)
- [app/services/takes/service.py](/root/ai_slop_2/app/services/takes/service.py)
- [app/models/pack.py](/root/ai_slop_2/app/models/pack.py)
- [app/models/take.py](/root/ai_slop_2/app/models/take.py)
- [app/models/session.py](/root/ai_slop_2/app/models/session.py)

Назначение:

- каталог тематик и трендов
- активная сессия пользователя
- лимиты по пакетам
- сущность `take` как единица генерации

### 3.3 Payments And Monetization

- [app/services/payments/service.py](/root/ai_slop_2/app/services/payments/service.py)
- [app/services/pack_order/service.py](/root/ai_slop_2/app/services/pack_order/service.py)
- [app/services/unlock_order/service.py](/root/ai_slop_2/app/services/unlock_order/service.py)
- [app/services/yookassa/client.py](/root/ai_slop_2/app/services/yookassa/client.py)
- [app/api/routes/webhooks.py](/root/ai_slop_2/app/api/routes/webhooks.py)
- [app/paywall/config.py](/root/ai_slop_2/app/paywall/config.py)
- [app/services/balance_tariffs.py](/root/ai_slop_2/app/services/balance_tariffs.py)

Назначение:

- продажа пакетов
- продажа unlock одного фото
- создание и подтверждение платежей
- активация пакета после оплаты

### 3.4 User Access, Favorites And HD Delivery

- [app/services/users/service.py](/root/ai_slop_2/app/services/users/service.py)
- [app/services/favorites/service.py](/root/ai_slop_2/app/services/favorites/service.py)
- [app/services/hd_balance/service.py](/root/ai_slop_2/app/services/hd_balance/service.py)
- [app/services/compensations/service.py](/root/ai_slop_2/app/services/compensations/service.py)

Назначение:

- пользовательские квоты и free-preview
- избранное
- баланс 4K
- компенсации при сбоях

### 3.5 Generation, Vision And Delivery Workers

- [app/workers/tasks/generate_take.py](/root/ai_slop_2/app/workers/tasks/generate_take.py)
- [app/workers/tasks/generation_v2.py](/root/ai_slop_2/app/workers/tasks/generation_v2.py)
- [app/workers/tasks/deliver_unlock.py](/root/ai_slop_2/app/workers/tasks/deliver_unlock.py)
- [app/workers/tasks/deliver_hd.py](/root/ai_slop_2/app/workers/tasks/deliver_hd.py)
- [app/workers/tasks/merge_photos.py](/root/ai_slop_2/app/workers/tasks/merge_photos.py)
- [app/services/llm/vision_analyzer.py](/root/ai_slop_2/app/services/llm/vision_analyzer.py)
- [app/services/llm/receipt_parser.py](/root/ai_slop_2/app/services/llm/receipt_parser.py)

Назначение:

- генерация трех вариантов результата
- генерация legacy job flow
- разблокировка оригиналов
- выдача 4K
- vision-анализ референса и чеков

### 3.6 Analytics, Audit And Templates

- [app/services/product_analytics/service.py](/root/ai_slop_2/app/services/product_analytics/service.py)
- [app/services/audit/service.py](/root/ai_slop_2/app/services/audit/service.py)
- [app/services/telegram_messages/runtime.py](/root/ai_slop_2/app/services/telegram_messages/runtime.py)
- [app/utils/metrics.py](/root/ai_slop_2/app/utils/metrics.py)

Назначение:

- продуктовая аналитика
- аудит действий
- runtime-тексты сообщений
- Prometheus-метрики

### 3.7 Referral Layer

- [app/referral/service.py](/root/ai_slop_2/app/referral/service.py)
- [app/referral/config.py](/root/ai_slop_2/app/referral/config.py)
- [app/models/referral_bonus.py](/root/ai_slop_2/app/models/referral_bonus.py)

Назначение:

- атрибуция реферала
- создание бонусов
- холд бонусов
- списание бонусных 4K-кредитов

---

## 4. Main User Flows

## 4.1 Global Gates Before Any Main Action

До выполнения сценариев работают два общих слоя:

- security middleware
- subscription middleware

Что проверяется:

- ban / suspend
- rate limit
- обязательная подписка на канал для новых пользователей

Код:

- [app/bot/main.py](/root/ai_slop_2/app/bot/main.py)

---

## 4.2 Start Flow

### User Journey

1. Пользователь открывает бота и отправляет `/start`
2. Бот создает или обновляет пользователя
3. Пишется аудит и аналитика старта
4. Парсятся deep links:
- `trend_*`
- `theme_*`
- `ref_*`
- `src_*`
- `unlock_done_*`
- `pack_done_*`
5. Если подписка на канал обязательна и не пройдена, пользователь попадает на экран подписки
6. Если ограничений нет, бот показывает welcome screen и главное меню

### Business Meaning

`/start` используется не только как onboarding, но и как точка:

- маркетинговой атрибуции
- реферальной атрибуции
- возврата после оплаты
- deeplink-навигации в конкретный тренд или тематику

---

## 4.3 Main Menu

Главные пользовательские CTA:

- `🔥 Создать фото`
- `🔄 Сделать такую же`
- `🧩 Соединить фото`
- `🛒 Купить пакет`
- `👤 Мой профиль`

Это фактически 5 верхнеуровневых продуктовых веток.

---

## 4.4 Flow: Create Photo

### Шаг 1. Выбор ЦА

FSM:

- `waiting_for_audience`

Кнопки:

- `👩 Я — женщина`
- `👨 Я — мужчина`
- `👩‍❤️‍👨 Мы — пара`

Особенность:

- для `men` сейчас срабатывает off-ramp: мужской профиль не обслуживается и пользователь уводится в информационную ветку

### Шаг 2. Загрузка фото

FSM:

- `waiting_for_photo`

Поддержка:

- фото
- документ-изображение

Проверки:

- consent
- размер файла
- допустимый формат

### Шаг 3. Выбор тематики и тренда

FSM:

- `waiting_for_trend`
- `waiting_for_prompt`

Ветвления:

- deep link на тренд: генерация может стартовать сразу
- deep link на тематику: открывается сразу выбранная тематика
- стандартный flow: тематики -> тренды
- пользователь может выбрать `Своя идея` и ввести custom prompt

### Шаг 4. Создание take и постановка генерации

Происходит:

- проверка лимитов
- создание `Take`
- привязка к `Session`
- постановка Celery-задачи `generate_take`

### Шаг 5. Получение результата

Воркер генерирует 3 варианта:

- `A`
- `B`
- `C`

Пользователь получает:

- превью
- выбор лучшего варианта
- rescue-сценарии, если не подошло

---

## 4.5 Flow: Copy Style

### Пользовательский путь

1. Пользователь выбирает `Сделать такую же`
2. Загружает референс
3. Загружает свое фото
4. Vision-анализатор строит prompt на основе референса
5. Запускается генерация

### Business Meaning

Это отдельный продуктовый сценарий с более понятной ценностью:

- пользователь не выбирает готовый тренд
- пользователь приносит внешний образец
- система превращает референс в генеративный prompt

Это хороший кандидат на premium/upsell-позиционирование.

---

## 4.6 Flow: Merge Photos

### Пользовательский путь

1. Пользователь выбирает `Соединить фото`
2. Указывает количество: `2` или `3`
3. Загружает фотографии по шагам
4. Запускается merge worker
5. Бот отправляет итоговый результат документом

### Business Meaning

Это отдельный продуктовый сценарий, отличающийся от обычной генерации:

- другой пользовательский мотив
- другая логика входных данных
- потенциально отдельная unit economics

---

## 4.7 Flow After Generation

После генерации пользователь выбирает лучший вариант.

Что происходит дальше:

1. вариант автоматически попадает в `favorites`
2. система смотрит, есть ли у пользователя платный остаток
3. если платного остатка нет, показывается paywall
4. если остаток есть, можно сразу забирать 4K

Это ключевой monetization pivot продукта.

---

## 4.8 Favorites And 4K Flow

После выбора лучшего варианта пользователь может:

- открыть избранное
- отметить кадры для 4K
- забрать один 4K
- забрать альбом 4K

Есть два механизма доступа:

- paid HD balance
- referral HD credits

Фактически `favorites` являются промежуточной зоной между preview и paid delivery.

---

## 4.9 Rescue Flow

Если результат не подошел, бот дает rescue-сценарии:

- лицо не похоже
- стиль не подошел
- хочу еще варианты
- попробовать другое фото
- попробовать другой тренд

Business role rescue flow:

- снижает отток после неудачной генерации
- оттягивает негативный момент до монетизации
- повышает вероятность дожать пользователя до paywall или повторной генерации

---

## 5. Monetization Model

## 5.1 What The Bot Sells

Сейчас бот продает три основных типа ценности:

### A. Session Packs

Пакеты:

- `trial`
- `neo_start`
- `neo_pro`
- `neo_unlimited`

Что дает пакет:

- лимит `takes`
- лимит `4K`
- активную `session`

Это основная продуктовая модель.

### B. Single Unlock

Если пользователь находится в free-preview сценарии, он может купить одно фото:

- разовая разблокировка выбранного варианта
- цена сейчас: `129 ₽`

Это low-friction путь монетизации после бесплатной демонстрации ценности.

### C. Referral 4K Credits

Пользователь может тратить бонусные 4K-кредиты, полученные по реферальной программе.

Это не прямой revenue-stream, а retention/invite-механика.

---

## 5.2 Free-To-Paid Logic

Текущая продуктовая логика:

1. пользователь получает free preview
2. выбирает лучший вариант
3. если пакета нет:
- либо покупает unlock одного фото
- либо покупает пакет
4. если пакет есть:
- сразу использует paid HD delivery

Это означает, что paywall встроен не в момент генерации, а в момент выбора лучшего результата.

С точки зрения UX это сильное решение:

- ценность уже показана
- пользователь эмоционально вовлечен
- paywall стоит ближе к моменту желания владеть результатом

---

## 5.3 Pricing As-Is

Цены в системе размазаны по нескольким слоям.

Основные публичные цены:

- `trial`: `129 ₽`
- `neo_start`: `199 ₽`
- `neo_pro`: `499 ₽`
- `neo_unlimited`: `990 ₽`
- `unlock`: `129 ₽`

Источники:

- [app/services/balance_tariffs.py](/root/ai_slop_2/app/services/balance_tariffs.py)
- [app/services/pack_order/service.py](/root/ai_slop_2/app/services/pack_order/service.py)
- [app/paywall/config.py](/root/ai_slop_2/app/paywall/config.py)

Это отдельный операционный риск: цена не централизована в одном источнике.

---

## 6. Payment Flows

## 6.1 Current Payment Channels

Актуальные каналы оплаты:

- `YooKassa link payment`
- `ЮMoney via Telegram invoice/provider token`

Неактуальный или legacy-контур:

- `Stars`
- `bank transfer`

Они частично остались в коде для совместимости или старых веток, но не являются основной текущей стратегией.

---

## 6.2 Pack Payment Flow

### Вариант 1. YooKassa link для основных паков

Используется для:

- `neo_start`
- `neo_pro`
- `neo_unlimited`

Flow:

1. пользователь нажимает `paywall:{pack_id}`
2. создается `PackOrder`
3. создается платеж в YooKassa
4. пользователю дается `confirmation_url`
5. после оплаты:
- либо приходит webhook
- либо пользователь нажимает `pack_check`
6. пакет активируется, создается session

### Вариант 2. ЮMoney invoice

Используется в Telegram payment flow через:

- `send_invoice`
- `create_invoice_link`

Flow:

1. payload валидируется в `pre_checkout`
2. Telegram присылает `successful_payment`
3. вызывается логика активации session purchase

---

## 6.3 Unlock Payment Flow

### Когда включается

Когда пользователь уже увидел результат, выбрал лучший вариант, но:

- находится на free preview
- не имеет платного остатка

### Flow

1. создается `UnlockOrder`
2. создается YooKassa payment
3. пользователь уходит по ссылке
4. webhook или `unlock_check` подтверждает оплату
5. Celery доставляет оригинальный файл в чат

Это отдельный checkout-контур, отличный от покупки пакета.

---

## 7. Delivery Of Value

## 7.1 Delivery After Pack Purchase

После оплаты пака происходит:

1. создание `Session`
2. начисление paid HD balance
3. перенос free-preview take в новую session, если он уже был
4. пользователь получает сообщение об активации

То есть ценность доставляется как доступ к дальнейшему использованию продукта, а не как единичный готовый файл.

---

## 7.2 Delivery After Single Unlock

После подтверждения unlock оплаты:

1. order становится `paid`
2. enqueue `deliver_unlock_file`
3. воркер отправляет оригинал
4. order становится `delivered`

Это доставка уже готового результата, а не доступа к новому использованию.

---

## 7.3 Delivery After HD Selection

Для HD flow:

1. пользователь выбирает favorite
2. выбирает `deliver_hd_one`, `deliver_hd` или `deliver_hd_album`
3. запускается worker `deliver_hd`
4. выполняется upscale
5. списывается HD-баланс
6. файл приходит пользователю

Это уже post-purchase delivery layer.

---

## 8. Referral Model

Текущая реферальная механика:

1. пользователь получает referral code
2. новый пользователь приходит по `ref_*`
3. происходит attribution
4. при qualifying purchase должен создаваться bonus
5. bonus сначала находится в `pending`
6. после hold периода переходит в `available`
7. user может тратить HD credits

Сильная сторона:

- механика не выдает кэш, а выдает внутренний продуктовый актив

Ограничение:

- текущая основная денежная ветка не полностью синхронизирована с начислением referral-бонусов

---

## 9. Product Analytics Layer

В боте активно трекаются:

- button clicks
- funnel steps
- pack selection
- payment initiated
- payment success
- generation feedback
- likeness feedback
- rescue events
- referral attribution

Это дает хорошую базу для продуктовой аналитики, но есть риск неполной консистентности между платежными каналами.

---

## 10. Main Risks And Bottlenecks

## 10.1 Critical

### 1. Referral logic partially tied to legacy payment model

`create_bonus()` не выглядит полноценно встроенным в актуальный YooKassa / ЮMoney денежный контур.

Следствие:

- реферальная программа может не монетизироваться корректно
- часть реальных продаж может не давать bonus events

### 2. Webhook processing can fail silently from business perspective

Webhook всегда отвечает `200`, чтобы не провоцировать ретраи YooKassa.

Следствие:

- при внутреннем сбое заказ может остаться в недообработанном состоянии
- пользователь доходит до результата только через ручной `pack_check` или `unlock_check`

---

## 10.2 High

### 3. Unlock fallback confirmation can break unified payment accounting

В ручном `unlock_check` подтверждение оплаты и доставка возможны без полного симметричного прохождения через единый финансовый контур.

Следствие:

- возможна разница между фактом доставки и фактом финансовой записи

### 4. Metrics are not fully normalized across all payment channels

Часть событий считается по-разному в зависимости от типа оплаты.

Следствие:

- продуктовая аналитика и revenue analytics могут расходиться

---

## 10.3 Medium

### 5. Redis is a critical dependency for commercial flow

Redis используется для:

- rate limit
- idempotency
- FSM

При деградации часть коммерческой логики может блокироваться.

### 6. Too much legacy code in payment area

В коде сохраняются следы:

- Stars
- bank transfer
- legacy unlock/job flow

Следствие:

- выше стоимость изменений
- выше вероятность регрессий

### 7. Business idempotency is partly implemented at service level, not at DB level

Многое защищено кодом, но не везде закреплено жесткими unique constraints на бизнес-смысл.

---

## 10.4 Low / Operational

### 8. Price duplication

Цены живут в нескольких местах.

Следствие:

- риск дрейфа цен
- риск рассинхрона между UI, валидацией и order processing

---

## 11. Business Interpretation

В текущем виде бот уже выглядит как воронка с хорошей логикой демонстрации ценности:

1. сначала пользователь видит результат
2. потом выбирает лучший вариант
3. потом сталкивается с paywall

Это сильная часть продукта.

Главный business challenge не в базовом UX, а в надежности денежного контура и в консистентности слоев:

- payment state
- analytics
- referral bonus
- delivery confirmation

То есть продуктовая воронка уже понятна и жизнеспособна, но финансовый и операционный контур нуждаются в выравнивании.

---

## 12. Recommended Next Actions

### P0

- унифицировать все `pay_success` сценарии в один финансовый контур
- выровнять `unlock_check` и webhook по записи оплаты
- встроить referral bonus в актуальный YooKassa / ЮMoney purchase flow

### P1

- централизовать цены в одном источнике
- сократить legacy payment branches в bot UX
- собрать единый funnel dashboard: `paywall -> payment initiated -> payment success -> delivery`

### P2

- усилить DB-level guarantees для order idempotency
- формализовать AS-IS / TO-BE payment architecture
- выделить отдельный business KPI set по free-preview conversion

---

## 13. Key Code References

- [app/bot/main.py](/root/ai_slop_2/app/bot/main.py)
- [app/services/payments/service.py](/root/ai_slop_2/app/services/payments/service.py)
- [app/services/pack_order/service.py](/root/ai_slop_2/app/services/pack_order/service.py)
- [app/services/unlock_order/service.py](/root/ai_slop_2/app/services/unlock_order/service.py)
- [app/services/yookassa/client.py](/root/ai_slop_2/app/services/yookassa/client.py)
- [app/api/routes/webhooks.py](/root/ai_slop_2/app/api/routes/webhooks.py)
- [app/services/sessions/service.py](/root/ai_slop_2/app/services/sessions/service.py)
- [app/services/favorites/service.py](/root/ai_slop_2/app/services/favorites/service.py)
- [app/workers/tasks/generate_take.py](/root/ai_slop_2/app/workers/tasks/generate_take.py)
- [app/workers/tasks/deliver_unlock.py](/root/ai_slop_2/app/workers/tasks/deliver_unlock.py)
- [app/workers/tasks/deliver_hd.py](/root/ai_slop_2/app/workers/tasks/deliver_hd.py)
- [app/referral/service.py](/root/ai_slop_2/app/referral/service.py)
