# AS-IS: потоки данных, персистентность, риски при перезапуске Docker

Краткий отчёт по состоянию сервиса: генерация, тренды, картинки трендов, диплинки и что переживёт `docker compose` перезапуск/редеплой.

---

## 1. Где что хранится

| Данные | Хранилище | Где в коде |
|--------|-----------|------------|
| Тренды (метаданные, промпты, `example_image_path`) | PostgreSQL (volume `postgres_data`) | `app/models/trend.py`, `TrendService` |
| Файлы примеров трендов (картинки) | Файловая система хоста: `./data/trend_examples/` | API: `admin.py` `_save_trend_file`, `_get_trend_examples_dir`; бот: `_resolve_trend_example_path` |
| Входные фото пользователей | `./data/generated_images/inputs/` | `storage_base_path` в config, бот сохраняет при загрузке |
| Результаты генерации (превью, оригинал) | `./data/generated_images/outputs/` | Воркеры `generate_take`, `generation_v2`, `deliver_hd` |
| Чеки (оплата) | `./data/generated_images/receipts/` | Бот + логи в БД |
| FSM бота, кеш Celery | Redis (volume `redis_data`) | aiogram, Celery broker/backend |

---

## 2. Docker: что примонтировано

Из `docker-compose.yml`:

- **api**: `./data/generated_images`, `./data/trend_examples` → `/data/generated_images`, `/app/data/trend_examples`
- **worker**: только `./data/generated_images` → `/data/generated_images` (примеры трендов воркеру не нужны)
- **bot**: `./data/generated_images`, `./data/trend_examples` → те же пути
- **cleanup**: только `./data/generated_images`
- **db**: `postgres_data` (named volume)
- **redis**: `redis_data` (named volume)

Конфиг (`app/core/config.py`):

- `storage_base_path` = `/data/generated_images` (в контейнере = хостовая `./data/generated_images`)
- `trend_examples_dir` = `data/trend_examples` → в контейнере резолвится в `/app/data/trend_examples` (так как cwd = `/app`)

---

## 3. Примеры трендов (фото к трендам): не пропадут при редеплое

- Загрузка: админка вызывает `POST /admin/trends/{id}/example` → API пишет файл в `_get_trend_examples_dir()` = `/app/data/trend_examples` и в БД сохраняет путь в `Trend.example_image_path` (полный путь, например `/app/data/trend_examples/<uuid>_example.png`).
- Этот путь внутри контейнера — это bind mount хостовой `./data/trend_examples`. Файлы лежат на хосте.
- При перезапуске/редеплое контейнеров том не удаляется, каталог `./data/trend_examples` на хосте остаётся. Новый контейнер снова монтирует тот же каталог в `/app/data/trend_examples`.
- Резолв при отдаче: в API и боте используется `_resolve_trend_media_path` / `_resolve_trend_example_path`: сначала проверяется путь из БД (если абсолютный и файл есть), иначе поиск по шаблону `{trend_id}_example.{ext}` в `trend_examples_dir`. Так что даже если бы в БД хранился относительный путь, после редеплоя файл всё равно найден (тот же mount).

**Итог: фотографии к трендам не пропадут при перезапуске/пушe Docker, если вы не удаляете каталог `./data/trend_examples` на хосте и не делаете `docker compose down -v` (см. ниже).**

---

## 4. Риски при перезапуске Docker

- **Обычный перезапуск** (`docker compose restart`, `up -d` после `down` без `-v`):  
  - Named volumes (`postgres_data`, `redis_data`) сохраняются.  
  - Bind mount’ы (`./data/generated_images`, `./data/trend_examples`) — это каталоги на хосте, они не удаляются Docker’ом.  
  → Тренды, примеры трендов, сгенерированные картинки, пользователи, сессии — всё остаётся.

- **Полное удаление volumes** (`docker compose down -v`):  
  - Удаляются только **named** volumes: `postgres_data`, `redis_data`.  
  - БД и Redis будут пустыми после следующего `up`.  
  - Каталоги `./data/trend_examples` и `./data/generated_images` при этом **не** удаляются (это не volumes, а bind mount’ы).  
  → Метаданные трендов и путь `example_image_path` в БД пропадут; файлы примеров трендов на диске останутся, но будут «осиротевшими» (до повторной загрузки через админку и привязки к тренду).

- **Рекомендация**: перед первым деплоем создать на хосте `./data/trend_examples` (и при необходимости `./data/generated_images`), чтобы не было проблем с правами и путями. В архитектуре это уже указано.

---

## 5. Генерация (кратко)

- **Take (основной сценарий)**: бот → `TakeService.create_take` → Celery `generate_take` → чтение входов из `storage_base_path/inputs` и сессии, запись в `storage_base_path/outputs`; пути в БД в `Take`. Всё использует примонтированный `./data/generated_images`.
- **Job (перегенерация/legacy)**: бот → `JobService.create_job` → Celery `generate_image` (generation_v2) → те же пути. Cleanup удаляет только временные **входные** файлы старых Job (`input_local_paths`), не трогает outputs, примеры трендов и чеки.

---

## 6. Диплинки

- **Формат**: `/start trend_<trend_id>`, `/start ref_<referral_code>`.
- Парсинг в боте: `_parse_start_arg`, `_parse_referral_code` в `app/bot/main.py`. При `trend_<id>` бот проверяет тренд в БД (`TrendService.get`), кладёт `selected_trend_id` в FSM и переводит в `waiting_for_photo`. Данные трендов и диплинки берутся из PostgreSQL; при редеплое без `-v` БД сохраняется — диплинки продолжают работать.
- В админке/схемах есть поле `deeplink` (ссылка «Попробовать этот тренд») — оно формируется на основе `TELEGRAM_BOT_USERNAME` и `trend_id`; эндпоинт списка с диплинками описан в схемах (`GET /admin/trends/deeplinks`). Логика диплинков не зависит от файлов примеров трендов.

---

## 7. Проверка целостности (что можно быстро проверить)

1. **Тренды и примеры**: в админке список трендов и `has_example` считаются через `_resolve_trend_media_path` (по факту наличия файла). Если после редеплоя примеры отображаются — путь и mount в порядке.
2. **Генерация**: создание Take/Job и сохранение в `outputs/` идут через `storage_base_path`; при том же mount после редеплоя пути остаются валидными.
3. **Cleanup**: не трогает `outputs/`, `trend_examples`, `receipts` — только старые `input_local_paths` у Job.

---

## 8. Итог

- **Генерация, сохранение трендов, картинок трендов и диплинки** настроены корректно: данные в БД и на диске в примонтированных каталогах.
- **Фото к трендам не пропадут** при обычном перезапуске/редеплое Docker (без `down -v`), так как лежат в bind mount `./data/trend_examples`.
- Для полной сохранности не использовать `docker compose down -v` без необходимости (это очистит БД и Redis).
