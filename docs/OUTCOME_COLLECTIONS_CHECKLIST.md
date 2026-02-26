# Чеклист самопроверки: Outcome Collections (PRD BASELINE v2)

Проверка реализации по ТЗ. Отмечайте `[x]` выполненное, `[ ]` — требующее проверки или доработки.

---

## P0. Коммерческое ядро

### 1) Outcome-пакеты вместо «трендов/кредитов»

| # | Требование | Статус | Где проверить |
|---|------------|--------|----------------|
| 1.1 | Pack: `pack_subtype='collection'`, `playlist=[trend_id...]`, `takes_limit`, `hd_amount` | [x] | `app/models/pack.py`, миграция 043 |
| 1.2 | Session создаётся с копией playlist, hd_limit=pack.hd_amount | [x] | `SessionService.create_collection_session` |
| 1.3 | Обещание в UX: «всего превью N, выбери до M HD, забери альбомом» | [x] | Бот: session_status, open_favorites, choose_variant, collection_complete |

### 2) Preview-first (1 бесплатный Take, paywall после preview)

| # | Требование | Статус | Где проверить |
|---|------------|--------|----------------|
| 2.1 | 1 бесплатный Take только в entry-коллекции | [x] | free_preview session, paywall после выбора варианта |
| 2.2 | После preview сразу paywall («смотри бесплатно, плати если нравится») | [x] | `_show_paywall_after_free_take` |
| 2.3 | Free никогда не даёт HD | [x] | HD только после оплаты/баланса, логика в deliver_hd |

### 3) Trust (согласие, политика, компенсации)

| # | Требование | Статус | Где проверить |
|---|------------|--------|----------------|
| 3.1 | Экран согласия перед первым фото | [x] | `handle_photo_step1` — проверка `consent_accepted_at`, кнопка «Принимаю» |
| 3.2 | Кнопка «Удалить мои данные» / команда | [x] | `/deletemydata` → `delete_user_data` worker |
| 3.3 | Реальное удаление файлов и путей в БД | [x] | `app/workers/tasks/delete_user_data.py` |
| 3.4 | Компенсация при сбое HD (SLA / permanent fail) | [x] | `CompensationService`, watchdog, deliver_hd |
| 3.5 | Кнопка «Проблема с HD» + correlation_id в тикет | [x] | `hd_problem:{fav_id}`, `report_hd_problem` → compensation_log |

### 4) Компенсации и refunds как продукт

| # | Требование | Статус | Где проверить |
|---|------------|--------|----------------|
| 4.1 | SLA: HD не доставлен за N минут → авто-компенсация (возврат HD) | [x] | `check_and_compensate_hd_sla`, watchdog |
| 4.2 | Идемпотентность: `favorite.compensated_at` guard | [x] | `CompensationService` — проверка перед выдачей |
| 4.3 | При permanent failure deliver_hd → возврат HD (идемпотентно) | [x] | `auto_compensate_on_fail` в deliver_hd |

### 5) Ясная математика выбора

| # | Требование | Статус | Где проверить |
|---|------------|--------|----------------|
| 5.1 | «Всего превью: N, выбери до M HD» | [x] | Бот: session_status, open_favorites, choose_variant |
| 5.2 | Счётчики: «HD осталось: Z», «В избранном: K (отмечено для HD: J)» | [x] | От session.hd_limit/hd_used, не от user.hd_balance |
| 5.3 | «Забрать HD альбомом» + подтверждение по выбранным | [x] | `deliver_hd_album` берёт только `selected_for_hd=True` |

### 6) Guardrails по COGS

| # | Требование | Статус | Где проверить |
|---|------------|--------|----------------|
| 6.1 | A/B/C — всегда preview; HD только после выбора | [x] | Логика favorites → selected_for_hd → deliver_hd |
| 6.2 | Favorites cap от session (min(hd_limit*2, cap or 30)), не от user.hd_balance | [x] | `FavoriteService._check_favorites_cap` |
| 6.3 | Коллекция с playlist=NULL не продаётся | [x] | PaymentService + Admin API validation |
| 6.4 | takes_used только при success (take_previews_ready) | [x] | `generate_take` вызывает `use_take` после успеха |
| 6.5 | return_take при fail (идемпотентный) | [x] | `SessionService.return_take` |
| 6.6 | Reroll в коллекции не предлагать / запретить | [x] | В коллекции — «Следующий образ», без повторной генерации того же шага |

---

## P1. Paywall и апсейл

| # | Требование | Статус | Где проверить |
|---|------------|--------|----------------|
| 7.1 | Paywall: макс. 3 кнопки (Trial, текущая коллекция, Creator) | [x] | `_show_paywall_after_free_take` |
| 7.2 | Middle option — «вот этот Dating/Avatar pack» (Популярное) | [x] | Логика выбора collection_pack + label |
| 7.3 | Upsell после hd_delivered (момент удовлетворения) | [x] | `_try_upsell_after_hd` в deliver_hd worker |
| 7.4 | Upsell: следующая коллекция из upsell_pack_ids, иначе Creator | [x] | Там же |

---

## Телеметрия

| # | Требование | Статус | Где проверить |
|---|------------|--------|----------------|
| 8.1 | collection_start | [x] | PaymentService после create_collection_session |
| 8.2 | take_previews_ready (preview_ready) | [x] | generate_take audit |
| 8.3 | pay_success | [x] | handle_successful_payment |
| 8.4 | collection_complete | [x] | Бот take_more при завершении playlist |
| 8.5 | hd_delivered | [x] | deliver_hd worker |
| 8.6 | collection_drop_step (abandoned sessions) | [x] | Beat task `detect_collection_drops` |
| 8.7 | paywall_variant_shown (какие 3 кнопки) | [x] | `_show_paywall_after_free_take` |
| 8.8 | funnel_counts в admin telemetry | [x] | `GET /admin/telemetry/product-metrics` |

---

## Данные и модели

| # | Требование | Статус | Где проверить |
|---|------------|--------|----------------|
| 9.1 | Миграция 043: packs, sessions, takes, users, favorites, compensation_log | [x] | `migrations/043_outcome_collections.sql` |
| 9.2 | Модели: Pack (playlist, pack_subtype, …), Session (playlist, current_step, hd_*, input_photo_path), Take (step_index, is_reroll), User (consent, data_deletion), Favorite (selected_for_hd, compensated_at), CompensationLog | [x] | `app/models/` |
| 9.3 | MVP SKU: dating_pack, avatar_pack (enabled=FALSE, playlist=NULL до заполнения в админке) | [x] | INSERT в 043 |

---

## Collection flow (1 фото на сессию)

| # | Требование | Статус | Где проверить |
|---|------------|--------|----------------|
| 10.1 | После покупки коллекции — «Отправьте одно фото для всей коллекции» | [x] | handle_successful_payment, state=waiting_for_photo |
| 10.2 | Первое фото сохраняется в session.input_photo_path и input_file_id | [x] | handle_photo_step1 — ветка «collection, no input_photo_path» → set_input_photo |
| 10.3 | Авто-старт Take для step 0 по этому фото | [x] | Там же: create_take, advance_step, generate_take.delay |
| 10.4 | Дальше «Следующий образ» без повторной загрузки фото (input_photo_path из session) | [x] | take_more collection branch, generate_take использует session.input_photo_path |

---

## Admin API и UI

| # | Требование | Статус | Где проверить |
|---|------------|--------|----------------|
| 11.1 | Packs CRUD: pack_subtype, playlist, favorites_cap, collection_label, upsell_pack_ids, hd_sla_minutes | [x] | admin.py packs_update/packs_create, packs_list |
| 11.2 | Валидация: коллекция с playlist=NULL не может быть enabled | [x] | admin.py + PaymentService |
| 11.3 | GET /admin/compensations, GET /admin/compensations/stats | [x] | admin.py |
| 11.4 | Admin UI: форма пакетов с полями коллекции (playlist editor, subtype, favorites_cap, upsell, hd_sla_minutes) | [x] | PacksPage.tsx, api.ts Pack type |

---

## Дополнительные проверки (ручные)

| # | Действие |
|---|----------|
| A | Применить миграцию 043 на БД: `psql -f migrations/043_outcome_collections.sql` |
| B | Включить коллекцию только после заполнения playlist в админке (иначе 400 при enabled=true) |
| C | Прогнать сценарий: оплата коллекции → отправка фото → получение step 0 → выбор варианта → «Следующий образ» → … → «Забрать HD альбомом» |
| D | Проверить, что после оплаты коллекции состояние переводится в waiting_for_photo и сообщение про одно фото отображается |

---

**Итог:** все пункты ТЗ из плана Outcome Collections покрыты реализацией. После применения миграции и ручных проверок A–D можно считать внедрение завершённым.
