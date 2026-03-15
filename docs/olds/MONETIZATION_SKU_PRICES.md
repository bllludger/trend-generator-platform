# Контракт SKU и цен (Monetization)

## SKU = pack_id

Идентификатор продукта в продаже — это `pack_id` (таблица `packs`). Список продуктов в продаже задаётся константой `PRODUCT_LADDER_IDS` в `app/services/payments/service.py`. Остальные пакеты не показываются в магазине и не принимаются в paywall/банке.

## Источники цен

| Валюта / контекст | Источник | Где задано |
|-------------------|----------|------------|
| **Stars (XTR)**   | БД `packs.stars_price` | Миграции, seed_default_packs; для лестницы — миграции 041, 044, 049 |
| **RUB (ЮMoney)**  | Фиксированный словарь `DISPLAY_RUB` | `app/services/balance_tariffs.py` |
| **RUB (банк)**    | `round(pack.stars_price * star_to_rub)` | В коде выбора пакета при переводе; курс `star_to_rub` в `app/core/config.py` |
| **Отображение на кнопках магазина** | `DISPLAY_RUB` с fallback на `round(pack.stars_price * star_to_rub)` | `app/services/balance_tariffs.py` |

При смене цен нужно обновлять оба источника для консистентности: при изменении Stars — БД (и при необходимости DISPLAY_RUB для ЮMoney); при изменении RUB для ЮMoney — только DISPLAY_RUB.

## Unlock одного фото

- Stars: `app/core/config.py` — `unlock_cost_stars`
- Токены (баланс фото): `app/core/config.py` — `unlock_cost_tokens`
- Обёртка для paywall: `app/paywall/config.py`

## Курс

`star_to_rub` в `app/core/config.py` (по умолчанию 1.3) — для отображения в скобках и для ожидаемой суммы при оплате переводом на карту.

## Точки входа в оплату (callback)

- **paywall:{pack_id}** — основной путь: экран выбора способа оплаты (ЮMoney, Stars, перевод и т.д.). Кнопки магазина в `balance_tariffs` используют только его.
- **buy:{pack_id}** — прямая отправка invoice за Stars. В текущем UI не используется; обработчик оставлен для обратной совместимости со старыми сообщениями в чатах.
