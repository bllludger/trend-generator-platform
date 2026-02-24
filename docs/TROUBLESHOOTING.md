# Устранение неполадок

## Расширенный ответ Gemini: почему модель не обработала запрос

При использовании провайдера **Gemini** (IMAGE_PROVIDER=gemini) можно получать от API пояснение, *почему* запрос был заблокирован или модель не справилась с генерацией.

**Что возвращает API** ([документация](https://ai.google.dev/api/generate-content#GenerateContentResponse)):

- **promptFeedback** (если запрос заблокирован до генерации, нет `candidates`):
  - `blockReason`: SAFETY, OTHER, BLOCKLIST, PROHIBITED_CONTENT, IMAGE_SAFETY
  - `safetyRatings[]`: категории и уровни по промпту
- **candidates[0]** (если кандидат есть, но генерация не удалась):
  - `finishReason`: STOP, SAFETY, IMAGE_OTHER, IMAGE_SAFETY, RECITATION и др.
  - **finishMessage** — текстовое пояснение от модели (например: "Could not generate the image based on the prompt")
  - `safetyRatings[]`: рейтинги по ответу

В коде провайдера Gemini при ошибке нужно:
1. Собрать эти поля в dict через `build_gemini_error_detail(result)` (из `app.services.image_generation.base`).
2. Выбросить `ImageGenerationError(сообщение_пользователю, detail=этот_dict)` вместо обычного `ValueError`.

Воркер при поимке `ImageGenerationError` пишет `detail` в лог и отправляет пользователю в Telegram поле **finish_message** (если оно есть), чтобы пользователь видел пояснение от модели. В логах также будут `finish_reason`, `prompt_feedback`, `safety_ratings` для отладки.

**Максимальное логирование ответа Gemini (в консоль и в админку):**  
В провайдере после успешного парсинга ответа вызовите `sanitize_gemini_response_for_log(result)` (из `app.services.image_generation.base`) и передайте результат в `ImageGenerationResponse(..., raw_response_sanitized=этот_dict)`. Воркер запишет полный ответ (без base64) в аудит и в лог; в админке на странице «Аудит» в записи «Ответ от провайдера» появится таб «Полный ответ API» с полным JSON ответа Gemini.

---

## Одна база для всего

API, бот, воркер и админка подключаются к **одной и той же** базе `trends` (из `.env`: `DATABASE_URL`). Отдельной «второй» базы в проекте нет. Если в боте видны одни тренды, а в админке нули по пользователям/задачам — это одна и та же БД: тренды заполнены сидом, а пользователи и задачи появляются только после использования бота или ручного добавления.

**Разные списки трендов** в боте (на двух скриншотах) означают, что в разное время использовалась разная БД: например, том PostgreSQL пересоздавался (`stop.sh -v`, новый сервер), получилась новая пустая БД, сид заполнил только тренды из текущего `001_trends.sql`, а старые правки/кастомные тренды и все пользователи и задачи остались в старом томе и потерялись.

**Чтобы не терять данные:** делайте резервную копию БД перед пересозданием томов и при переносе на другой сервер:
```bash
docker compose exec -T db pg_dump -U trends trends > backup_$(date +%Y%m%d).sql
```
Восстановление на новой БД: создать базу `trends`, затем `psql -U trends -d trends -f backup_YYYYMMDD.sql`.

---

## База данных «пустая»

### Причины

1. **Смотрите не ту базу**  
   Данные приложения лежат в базе **`trends`**, пользователь **`trends`** (или `postgres` после `fix_postgres_role.sh`).  
   Если в IDE/pgAdmin подключиться к базе **`postgres`** (по умолчанию), там будет пусто — это не та база.

2. **Удаляли volumes**  
   Команда `./stop.sh -v` или `./stop.sh --full` удаляет том с данными PostgreSQL. После следующего `./start.sh` БД создаётся заново и заполняется только если миграции и сид отработали.

3. **Сид не выполнился**  
   Сид трендов (`migrations/seed/001_trends.sql`) запускается только когда в таблице `trends` 0 записей. Раньше при ошибке проверки (например, таблица ещё не создана) скрипт ошибочно считал, что тренды уже есть, и сид пропускался. Это исправлено: при ошибке проверки сид теперь выполняется.

### Что сделать

- **Подключение к БД:** база **`trends`**, хост/порт — как у контейнера `db` (обычно localhost:5432). Пользователь: `trends`, пароль из `.env` (`POSTGRES_PASSWORD`, по умолчанию `trends`). Для доступа под `postgres`: после первого запуска выполнить `./scripts/fix_postgres_role.sh`, затем подключаться как `postgres` / `postgres` к базе **`trends`**.

- **Полная пересборка с нуля (с сохранением кода):**
  ```bash
  ./stop.sh -v
  ./start.sh
  ```
  Миграции и сид выполнятся заново, в БД появятся таблицы и дефолтные тренды.

- **Вручную применить сид один раз** (если таблицы есть, но трендов нет):
  ```bash
  docker compose exec -T db psql -U trends -d trends -f - < migrations/seed/001_trends.sql
  ```

## Ошибка: `database "trends" does not exist`

Появляется, если том PostgreSQL был впервые создан с другой конфигурацией (например, без `POSTGRES_DB=trends` или с `POSTGRES_DB=postgres`). В таком случае в контейнере есть только база `postgres`, а приложение подключается к `trends`.

**Что сделать:**

1. **Перезапуск с созданием базы** — в `start.sh` добавлена проверка: если базы `trends` нет, она создаётся. Выполните:
   ```bash
   ./restart.sh
   ```
   или полный цикл:
   ```bash
   ./stop.sh
   ./start.sh
   ```

2. **Создать базу вручную (контейнер уже запущен):**
   ```bash
   docker compose exec -T db psql -U trends -d postgres -c "CREATE DATABASE trends;"
   ```
   Если пользователь `trends` не подключается к `postgres`, попробуйте:
   ```bash
   docker compose exec -T db psql -U postgres -d postgres -c "CREATE DATABASE trends;"
   ```
   После этого снова запустите миграции (или выполните `./restart.sh`).

## Ошибки PostgreSQL: `FATAL: password authentication failed for user "postgres"`

Это попытки входа под пользователем `postgres` с неверным паролем (часто из IDE или pgAdmin). Само приложение использует пользователя `trends` и при корректном `.env` подключается нормально.

**Что сделать:** выполнить `./scripts/fix_postgres_role.sh` (устанавливает пароль `postgres` для роли `postgres` и выдаёт права на БД `trends`). В клиентах подключаться к базе **`trends`** с логином/паролем `postgres`/`postgres` либо `trends`/значение из `POSTGRES_PASSWORD` в `.env`.
