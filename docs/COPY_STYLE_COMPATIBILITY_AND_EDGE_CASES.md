# «Сделать такую же»: совместимость и граничные случаи

## 1. Совместимость

### 1.1 Флаг copy_flow_origin (критично)

**Проблема:** Если пользователь загружал референс (в FSM есть `reference_path`), затем ушёл в главное меню и прошёл флоу «Создать фото» (фото → тренд → формат), в `select_format_and_generate` в state остаётся `reference_path`. Определение copy-флоу по одному лишь `reference_path` приводило к ложному срабатыванию: списывалась copy-квота и создавался Take с типом COPY при обычном трендовом сценарии.

**Решение:** Ввод отдельного флага `copy_flow_origin`:
- Выставляется в `True` только в `handle_self_photo_for_copy` и `handle_self_photo_as_document_for_copy` при переходе в `waiting_for_format` (после успешного Vision).
- В `select_format_and_generate`: `is_copy_flow = bool(data.get("copy_flow_origin"))`, а не по `reference_path`.
- Квота copy и тип Take COPY используются только при реальном прохождении copy-флоу (референс → своё фото → Vision → формат).

### 1.2 Очистка state при входе в copy flow

При нажатии «Сделать такую же» вызывается `state.clear()`, затем `set_state(waiting_for_reference_photo)`. Так в copy flow не попадают старые ключи из основного флоу (например, `selected_trend_id`, `photo_file_id`) и не остаётся старый `copy_flow_origin` от прошлого сеанса.

### 1.3 Регенерация (Job)

- В `regenerate_same` для Job проверяется `if "ref" in file_ids` → показ сообщения «Перегенерация для этого кадра недоступна». Старые Job с `input_file_ids`, содержащими `"ref"`, не перезапускаются (файлы не скачиваются заново по file_id).
- Copy-квота при регенерации определяется по `job.used_copy_quota` и списывается через `try_use_copy_generation` только для Job, изначально созданных в copy-флоу.

### 1.4 БД и админка

- Таблицы `copy_style_settings`, миграции 011–016: все поля сохранены. Поля `prompt_instruction_3_images`, `prompt_instruction_2_images`, `generation_*` в текущем флоу (1 ref + 1 identity) не используются воркером, но остаются в БД и в UI для обратной совместимости и возможного расширения.
- Админка GET/PUT `/admin/settings/copy-style` отдаёт/принимает тот же набор полей; изменение флоу на «только анализ референса + identity» не ломает API.

---

## 2. Граничные случаи

### 2.1 Референс или identity удалён до вызова Vision/генерации

- **Референс пропал до загрузки своего фото:** в `handle_self_photo_for_copy` проверка `os.path.exists(reference_path)`; при отсутствии файла — «Сессия истекла. Начните заново» и `state.clear()`.
- **Референс удалён после перехода к формату:** в генерацию уходит только identity (`input_local_paths = [photo_local_path]`); референс нужен только для Vision, в Take хранится только `copy_reference_path` для аудита.
- **Identity-файл пропал до/во время воркера:** в `generate_take` для `take_type == "COPY"` добавлена проверка: если `input_image_path` не найден после выбора из `take.input_local_paths`/session — Take переводится в `failed` с кодом `identity_image_missing`, пользователю показывается сообщение «Не найден файл с фото. Начните заново».

### 2.2 Ответ Vision (пустой / некорректный code block)

- Пустой ответ API: `if not content or not content.strip()` → `ValueError("Пустой ответ от модели")`; в боте — «Не удалось проанализировать фото» и повторная попытка с другим изображением.
- После извлечения из code block: если извлечённая строка пустая, используется исходный `prompt` до извлечения; если и тогда пусто — `ValueError("Пустой ответ от модели после извлечения промпта")`.
- Один незакрытый ``` или несколько блоков: при одном блоке без пары используется `prompt.split("```", 1)[-1].strip() or prompt.strip()`; при пустом результате — та же ошибка.

### 2.3 Квоты и сессия

- **Copy-квота:** списывается только при `copy_flow_origin === true` в момент выбора формата; модератор не списывает (в `try_use_copy_generation`).
- **Идемпотентность формата:** `idempotency_key = job:{chat_id}:{message_id}:{format_key}` предотвращает двойное создание Take при повторном нажатии на тот же формат.
- **Race по квоте:** `try_use_copy_generation` выполняет атомарный `UPDATE ... WHERE copy_generations_used < limit`; при исчерпании лимита возвращается False и показывается сообщение об исчерпании copy-квоты.

### 2.4 Неверный ввод в copy flow

- В `waiting_for_reference_photo` не фото/документ: хендлер `copy_flow_wrong_input_ref` — «Отправьте картинку-образец».
- В `waiting_for_self_photo` не фото/документ: хендлер `copy_flow_wrong_input_self` — «Отправьте свою фотографию».
- Документ не изображение: проверка `_document_image_ext`; при неподходящем MIME — «Поддерживаются только изображения: JPG, PNG, WEBP».

### 2.5 Размер файла

- Проверка `max_file_size_mb` при сохранении референса и identity; при превышении — сообщение и удаление сохранённого файла (для референса).

### 2.6 Модель и API Vision

- В `vision_analyzer` используется `max_completion_tokens` с fallback на `max_tokens` при TypeError (разные версии OpenAI API).
- Модель (например, gpt-5.2) задаётся в `copy_style_settings.model` и читается через `get_effective()`; смена модели в админке применяется без смены кода.

---

## 3. Итог

- Copy-флоу определяется только по `copy_flow_origin`; квота и тип COPY не срабатывают при «смешанном» state из основного флоу.
- При входе в «Сделать такую же» state очищается.
- Регенерация для старых Job с `ref` в file_ids отключена.
- Обработаны: пропавшие файлы референса/identity, пустой/некорректный ответ Vision, идемпотентность формата, гонки по квоте, неверный тип ввода и размер файла.
