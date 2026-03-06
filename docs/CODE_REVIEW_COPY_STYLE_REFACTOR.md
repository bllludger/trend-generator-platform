# Код-ревью: переработка «Сделать такую же»

## Проверенные компоненты

### 1. Vision-анализатор (`app/services/llm/vision_analyzer.py`)

| Что проверено | Статус |
|---------------|--------|
| `analyze_for_copy_style(reference_path, identity_path)` принимает оба пути | OK |
| Оба изображения в одном запросе (text + image1 + image2), порядок SCENE_REFERENCE → IDENTITY | OK |
| Настройки из `CopyStyleSettingsService.get_effective()` (model, system_prompt, user_prompt, max_tokens) | OK |
| Обработка `max_completion_tokens` / `max_tokens` для разных версий OpenAI API | OK |
| Извлечение содержимого из code block (```...```) | OK |
| Удаление первой строки-идентификатора языка (python, text, json) после извлечения code block | **Исправлено** — добавлено, иначе в промпт попадало бы `python\n[GOAL]...` |
| Ограничение длины промпта 4000 символов | OK |
| Логирование и проброс ошибок | OK |

### 2. Бот (`app/bot/main.py`)

| Что проверено | Статус |
|---------------|--------|
| Референс: сохранение пути, переход в `waiting_for_self_photo` без вызова Vision | OK |
| Своё фото: проверка `reference_path`, вызов `analyze_for_copy_style`, запись `custom_prompt`, переход в `waiting_for_format` | OK |
| Удалены выбор «1/2 фото», `waiting_for_self_photo_2`, хендлеры второго фото | OK |
| `select_format_and_generate`: один identity в `input_local_paths`, `is_copy_flow` по `reference_path` | OK |
| **Списание квоты «Сделать такую же»** | **Исправлено** — при `is_copy_flow` вызывается `try_use_copy_generation(user)`; при исчерпании квоты — сообщение и return; сессия для copy — `create_free_preview_session` |
| Модератор для copy не списывает квоту (через `try_use_copy_generation` внутри) | OK |
| `take_type = "COPY"`, `copy_reference_path` передаётся в Take | OK |

### 3. Воркер (`app/workers/tasks/generate_take.py`)

| Что проверено | Статус |
|---------------|--------|
| Условие `take.take_type in ("CUSTOM", "COPY") and take.custom_prompt` | OK |
| Для COPY: `prompt_text = take.custom_prompt`, один `input_image_path` из `take.input_local_paths[0]` (identity) | OK |
| 3 варианта A/B/C, прогресс-бар, выбор, 4K — общий пайплайн Take | OK |

### 4. Настройки и миграция

| Что проверено | Статус |
|---------------|--------|
| `_FALLBACK_SYSTEM` / `_FALLBACK_USER` в `settings_service.py` — Nano Banana Prompt Builder | OK |
| Миграция `051_copy_style_nano_banana_prompt.sql`: обновление только при пустом или старом русском промпте | OK |

### 5. Потенциальные замечания (без изменений кода)

- **`REFERENCE_NOTE_DEFAULT`** в `main.py` — константа не используется после удаления флоу «2 фото». Оставлена как возможная подсказка для сообщений; при желании можно удалить.
- **Документация** (`DATA_FLOWS.md`, `DATA_FLOW_AND_ARCHITECTURE_RU.md`) — описывает старый флоу (copy_photos_received, 2 фото). Имеет смысл обновить отдельным коммитом.

---

## Внесённые исправления

1. **Квота «Сделать такую же» в Take-флоу.**  
   Раньше при выборе формата в copy-флоу использовалась общая логика сессии (free_takes_used или пакет), и copy-квота не списывалась. Добавлена отдельная ветка для `is_copy_flow`: вызов `user_service.try_use_copy_generation(user)`; при успехе — создание free_preview-сессии и создание Take; при неуспехе — сообщение об исчерпании copy-квоты и выход.

2. **Извлечение code block в Vision.**  
   При ответе вида ` ```python\n[GOAL]\n...``` ` в промпт попадало `python\n[GOAL]...`. Добавлена проверка: если первая строка внутри блока — `python`, `text` или `json`, она отбрасывается и в промпт идёт только остаток.

---

## Админка UI («Сделать такую же»)

### Маршрут и API

- Роут: `/copy-style`, компонент `CopyStylePage`, пункт сайдбара «Стиль копирования».
- API: `GET /admin/settings/copy-style` → `CopyStyleSettingsService.get_effective()`, `PUT` → `update(payload)`.

### Проверка полей

| Вкладка | Поля | Соответствие бэку |
|--------|------|-------------------|
| Анализ референса | model, max_tokens, system_prompt, user_prompt, prompt_suffix | Используются в `analyze_for_copy_style` (Vision) |
| Инструкции (лица) | prompt_instruction_3_images, prompt_instruction_2_images | В текущем флоу не используются (1 ref + 1 identity); отображаются для совместимости |
| Промпт генерации | generation_system_prompt_prefix, generation_* (model, size, format, negative, safety, constraints) | В воркере Take для COPY не используются; сохранены в БД и в UI |

### Внесённые правки в UI

1. **Ошибка загрузки:** при `isError` отображается блок с текстом ошибки (вместо пустого экрана).
2. **Порядок проверок:** сначала проверка `isError`, затем `isLoading || !settings`, чтобы при падении запроса показывалась ошибка.
3. **max_tokens:** значение в payload при сохранении ограничивается диапазоном 256–4096; ввод числа обрабатывается через `parseInt(..., 10)`.
4. **Типизация:** в `api.ts` для `CopyStyleSettings` добавлены явные поля (model, system_prompt, user_prompt, max_tokens, generation_*, updated_at) для типобезопасности формы.
5. **Вкладка «Инструкции (лица)»:** подпись обновлена: указано, что в текущем флоу используется только «1 референс + 1 своё фото», поля сохранены для совместимости.

### Стабильность

- Сохранение: одна кнопка «Сохранить все настройки», отправляется полный payload по всем вкладкам; при успехе — инвалидация запроса и toast; при ошибке — toast с `response.data.detail` или `message`.
- Кнопка блокируется на время `updateMutation.isPending`.
- Форма инициализируется из `settings` в `useEffect`; после успешного сохранения данные перезапрашиваются и форма обновляется.

---

## Итог

Реализация соответствует плану. Критичный пропуск (списание copy-квоты) и мелкий баг (языковая метка в code block) исправлены. Остальной код согласован: один референс + одно своё фото → Vision → один промпт → тот же пайплайн Take (3 варианта, прогресс, A/B/C, 4K).
