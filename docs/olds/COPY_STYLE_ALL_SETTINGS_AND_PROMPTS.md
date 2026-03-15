# «Стиль копирования» — полный перечень настроек и промптов

Все системные промпты, настройки и тексты, которые участвуют во флоу «Сделать такую же».

---

## 1. Таблица БД `copy_style_settings` (id=1)

**Файл:** `app/models/copy_style_settings.py`  
**Чтение/запись:** `app/services/copy_style/settings_service.py`  
**API:** GET/PUT `/admin/settings/copy-style` → `CopyStyleSettingsService.get_effective()` / `update()`

| Поле | Тип | Дефолт в БД | Fallback в коде (если пусто) | Где используется |
|------|-----|-------------|------------------------------|-------------------|
| `model` | string | `gpt-4o` | `settings.openai_vision_model` (config: `openai_vision_model`) | **Vision** — модель OpenAI для анализа референса + identity |
| `system_prompt` | text | `""` | `_FALLBACK_SYSTEM` (см. ниже) | **Vision** — системное сообщение в `analyze_for_copy_style` |
| `user_prompt` | text | `""` | `_FALLBACK_USER` (см. ниже) | **Vision** — пользовательское сообщение (к нему добавляется image_order_note) |
| `max_tokens` | int | 1536 | 256–4096 (clamp) | **Vision** — max_completion_tokens / max_tokens в OpenAI |
| `prompt_suffix` | text | `""` | — | **Нигде не используется** в текущем коде (есть в get_effective/as_dict) |
| `prompt_instruction_3_images` | text | `""` | `_FALLBACK_INSTRUCTION_3` | Только в as_dict/админке; в флоу 1 ref + 1 identity не используется |
| `prompt_instruction_2_images` | text | `""` | `_FALLBACK_INSTRUCTION_2` | То же |
| `generation_system_prompt_prefix` | text | `""` | `_FALLBACK_GENERATION_SYSTEM_PREFIX` | **Не используется** в воркере generate_take для COPY |
| `generation_negative_prompt` | text | `""` | — | Не используется в generate_take для COPY |
| `generation_safety_constraints` | text | `no text generation, no chat.` | — | Не используется в generate_take для COPY |
| `generation_image_constraints_template` | text | `size={size}, format={format}` | — | Не используется |
| `generation_default_size` | string | `1024x1024` | — | Не используется (воркер берёт size из Take + GenerationPromptSettings) |
| `generation_default_format` | string | `png` | — | Не используется |
| `generation_default_model` | string | `""` | `settings.gemini_image_model` | Не используется (воркер жёстко `gemini-2.5-flash-image`) |

---

## 2. Системные и пользовательские промпты (Vision) — fallback в коде

**Файл:** `app/services/copy_style/settings_service.py`

### 2.1 `_FALLBACK_SYSTEM` (если в БД пустой `system_prompt`)

```
SYSTEM PROMPT - NANO BANANA PROMPT BUILDER (IDENTITY-LOCKED PHOTOSESSION, ENGLISH ONLY, COMPACT)

You analyze the user-provided images and output ONE Nano Banana prompt.

MODE SELECTION
- If the user provides a SCENE_REFERENCE image: copy that scene 1:1 (layout, object count, positions, colors, materials, relative sizes).
- If no SCENE_REFERENCE is provided: use the user SCENE text; if missing, keep the original identity photo scene.

PRIORITY (STRICT)
face unchanged > hair/head look > person count > scene accuracy (if reference) > pose/expression > wardrobe > style

IDENTITY LOCK (ABSOLUTE)
- Identity source = user IDENTITY photo only.
- Mandatory line (verbatim) must appear in final prompt:
  "The face must remain strictly unchanged. STRICTLY."
- Do not beautify or alter facial geometry/proportions/age markers/distinctive features.
- Keep hair color + general hairstyle silhouette and head look from IDENTITY photo (use ambiguous if not visible).
- Person count = 1. No identity merging.

SCENE COPY RULE (1:1 WHEN REFERENCE PROVIDED)
- Treat SCENE_REFERENCE as scene/composition source only, never as identity.
- Recreate the scene with maximum fidelity:
  object list + exact counts + approximate positions (left/right/top/bottom/foreground/background) + relative sizes + dominant colors + occlusions.
- Do not add/remove objects; if something is unclear, label ambiguous and choose the least-creative default.

WHAT MAY CHANGE (DEFAULT)
- Wardrobe may change to the user WARDROBE spec (if none, keep original).
- Pose/expression stays as identity photo unless user requests a different pose.

EVIDENCE RULE
- Describe identity/pose only from visible evidence.
- Unknowns must be labeled: ambiguous / partially_visible / occluded / not_visible.
- Do not invent brands, text, logos.

LANGUAGE LOCK (ABSOLUTE)
- Output ENGLISH ONLY.

OUTPUT RULES
- Output exactly ONE code block and nothing else.
- The code block contains ONE final Nano Banana prompt using the template below.
- Target length: 1000-1700 characters.

FINAL PROMPT TEMPLATE (FILL)

[GOAL]
type: edit
intent: "Identity-locked photoshoot: keep the same person and face from the identity photo; copy the target scene with high fidelity; apply requested wardrobe if provided."

[IDENTITY]
identity_lock: on
mandatory: "The face must remain strictly unchanged. STRICTLY."
keep: "facial geometry, proportions, age markers, distinctive features; hair color + hairstyle silhouette"
person_count: 1
visibility_notes: "<notes using ambiguous/partially_visible/occluded/not_visible>"

[SCENE SOURCE]
scene_reference_used: "<yes/no>"
rule: "If yes: copy scene 1:1 from SCENE_REFERENCE (layout, counts, positions, colors). If no: follow user SCENE text or keep original."

[SUBJECT - FROM IDENTITY PHOTO]
pose_expression: "<from image or ambiguous>"
hair: "<visible or ambiguous>"
accessories: "<visible or none>"

[SCENE - COPY WITH FIDELITY]
objects_inventory: "<bullet-like inline list: object:type x count; color; key attributes>"
layout_map: "<foreground/midground/background + left/center/right + occlusions>"
background: "<materials/colors/lighting cues from reference or text>"

[TARGET WARDROBE - FROM USER REQUEST]
wardrobe: "<replace outfit with ... | keep original outfit>"
wardrobe_constraints: "<optional: do not keep original outfit>"

[COMPOSITION | LIGHT | STYLE | OUTPUT]
composition: "<shot/angle/framing/dof from reference or user>"
lighting_color: "<from reference or user>"
style: "<e.g., photoreal fashion editorial>"

[NEGATIVE - LIGHT]
avoid: "extra people, any face change, beauty retouch, altered facial geometry, plastic skin, deformed hands, extra fingers, blur, low-res, watermark, any text/logos, added objects, missing objects"
```

### 2.2 `_FALLBACK_USER` (если в БД пустой `user_prompt`)

```
You receive two images: Image 1 = SCENE_REFERENCE (copy this scene 1:1). Image 2 = IDENTITY (this person's face and look must be preserved). Analyze both and output exactly ONE code block containing the final Nano Banana prompt as specified in the system prompt. No explanations, no extra text.
```

### 2.3 В Vision к user_prompt добавляется (жёстко в коде)

**Файл:** `app/services/llm/vision_analyzer.py`

```python
image_order_note = (
    "Image 1 = SCENE_REFERENCE (copy this scene 1:1). "
    "Image 2 = IDENTITY (this person's face and look must be preserved)."
)
# user_content[0].text = f"{user_prompt}\n\n{image_order_note}"
```

Итого в запросе к OpenAI (Vision):
- **system:** `opts["system_prompt"]` (из БД или _FALLBACK_SYSTEM)
- **user:** текст = `user_prompt + "\n\n" + image_order_note`, затем image1 (референс), image2 (identity)

---

## 3. Инструкции для 3 и 2 изображений (fallback, в флоу не участвуют)

**Файл:** `app/services/copy_style/settings_service.py`

- **`_FALLBACK_INSTRUCTION_3`:**  
  `Attached images order: (1) Style/scene reference to replicate. (2) Use this person's face for the woman/female character. (3) Use this person's face for the man/male character. Generate the scene in the described style with these two faces.`

- **`_FALLBACK_INSTRUCTION_2`:**  
  `Attached images order: (1) Use this face for the woman/female character. (2) Use this face for the man/male character. Generate the scene with these faces.`

В текущем флоу (1 референс + 1 своё фото) не используются.

---

## 4. Генерация изображения (воркер) — что реально используется для COPY

**Файл:** `app/workers/tasks/generate_take.py`

Для `take_type in ("CUSTOM", "COPY")` и `take.custom_prompt`:

| Параметр | Источник | Значение |
|----------|----------|----------|
| **prompt_text** | `take.custom_prompt` | Результат Vision (Nano Banana промпт), без добавления prompt_suffix и без префиксов из copy_style_settings |
| **negative_prompt** | — | `None` |
| **model** | жёстко в коде | `"gemini-2.5-flash-image"` |
| **size** | `take.image_size` или админка | `take.image_size` или `aspect_ratio_to_size(effective_custom["default_aspect_ratio"])` |
| **image_size_tier** | GenerationPromptSettings (release) | `effective_custom.get("default_image_size_tier") or "4K"` |

**Откуда берётся effective_custom:**  
`GenerationPromptSettingsService(db).get_effective(profile="release")` — это настройки **«Мастер промпт» / профиль release (id=2)**, не copy_style_settings.

То есть для COPY в генерации участвуют:
- системные промпты и настройки из **copy_style** — только на этапе **Vision** (системный + пользовательский промпт, модель, max_tokens);
- на этапе **генерации картинки** — только `take.custom_prompt` (текст от Vision), модель/размер/тир из **GenerationPromptSettingsService** и жёстко заданная модель `gemini-2.5-flash-image`.  
Поля `generation_*` из `copy_style_settings` в воркере не читаются.

---

## 5. GenerationPromptSettings (профиль release, id=2)

**Файл:** `app/services/generation_prompt/settings_service.py`, модель `GenerationPromptSettings`

Для COPY в `generate_take` используются только:

- `default_aspect_ratio` — если у Take нет своего `image_size` (fallback в коде: `"1:1"`).
- `default_image_size_tier` — tier для запроса к провайдеру (fallback в коде: `"4K"` при отсутствии ключа; в get_effective по умолчанию `"1K"`).

Остальные поля (prompt_input, prompt_task, prompt_identity_transfer, safety_constraints, default_model и т.д.) для ветки COPY не используются — промпт один раз взят из `take.custom_prompt`.

---

## 6. Конфиг (env / config)

**Файл:** `app/core/config.py`

| Переменная | Дефолт | Участие во флоу «Стиль копирования» |
|------------|--------|--------------------------------------|
| `openai_api_key` | обязательный | Vision — вызов OpenAI |
| `openai_vision_model` | `gpt-4o` | Fallback модели в copy_style_settings, если в БД пусто |
| `gemini_image_model` | `gemini-2.5-flash-image` | Fallback в copy_style_settings.generation_default_model (но в воркере для COPY модель жёстко `gemini-2.5-flash-image`) |
| `max_file_size_mb` | 10 | Проверка размера референса и своего фото при сохранении |
| `storage_base_path` | `/data/generated_images` | Пути сохранения референса и identity (`inputs/`) |

---

## 7. Квоты и безопасность (Job/регенерация, не Take)

**Файл:** `app/services/security/settings_service.py`, модель `SecuritySettings`

- **`copy_generations_per_user`** — лимит бесплатных генераций «Сделать такую же» на аккаунт (дефолт 1).  
Используется в `UserService.try_use_copy_generation()` при создании **Job** (регенерация), не при создании Take в основном флоу «Сделать такую же».

**Файл:** `app/models/user.py`  
- **`copy_generations_used`** — счётчик использованных copy-генераций.

---

## 8. Тексты бота (локализация / хардкод)

**Файлы:** `app/bot/main.py`, `app/services/telegram_messages/defaults.py`

| Ключ / место | Текст (дефолт или значение) |
|--------------|----------------------------|
| `menu.btn.copy_style` | «🔄 Сделать такую же» |
| `copy.start_text` (fallback в main.py) | «🔄 *Сделать такую же*\n\nЯ могу скопировать 1:1 любой тренд.\n\nЗагрузи картинку-образец в хорошем качестве — я изучу дизайн и подскажу, как сделать такую же.\n\nПоддерживаются: JPG, PNG, WEBP.» |
| После сохранения референса (хардкод) | «✅ Референс сохранён.\n\nОтправьте своё фото — по нему сохраню лицо и перенесу в сцену из образца.» |
| `flow.analyzing` | «⏳ Анализирую дизайн...» |
| После успешного Vision (хардкод) | «✅ Готово! Выбери формат:» |
| `flow.session_expired_copy` | «Сессия истекла. Начните заново: «🔄 Сделать такую же».» |
| `flow.send_reference` | «Отправьте картинку-образец (фото).» |
| `flow.send_your_photo` | «Отправьте свою фотографию.» |
| При ошибке Vision (хардкод) | «Не удалось проанализировать фото. Попробуйте другое изображение в хорошем качестве.» |
| При identity_image_missing в воркере (хардкод) | «❌ Не найден файл с фото. Начните заново: «🔄 Сделать такую же».» |

---

## 9. Дефолт префикса генерации (в коде, в воркере не используется)

**Файл:** `app/services/copy_style/settings_service.py` — `_FALLBACK_GENERATION_SYSTEM_PREFIX`

```
You are an image generation system (Nano Banana / Gemini image editing mode). Follow instructions exactly. No explanations, no captions, no intermediate steps. TREND (text) defines style and scene. Attached images define who must appear. Preserve identity, count, and placement of people from the input images. Return one final image only.
```

Возвращается в `get_effective()` / `as_dict()` как fallback для `generation_system_prompt_prefix`, но в `generate_take` для типа COPY этот префикс не подставляется к промпту.

---

## 10. Миграция 051 (дефолтные промпты в БД)

**Файл:** `migrations/051_copy_style_nano_banana_prompt.sql`

Обновляет `copy_style_settings` (id=1), только если текущий `system_prompt` пустой или старый (русский). Подставляет в БД тот же системный и пользовательский промпт, что и `_FALLBACK_SYSTEM` / `_FALLBACK_USER` в коде (Nano Banana Prompt Builder).

---

## Итоговая таблица: что где участвует

| Этап | Системный промпт / настройки | Источник |
|------|------------------------------|----------|
| Вход в флоу, сообщения пользователю | Тексты кнопок и подсказок | defaults.py + хардкод в main.py |
| Vision (анализ референс + identity) | system_prompt, user_prompt, model, max_tokens | copy_style_settings + fallback в settings_service.py |
| Vision | Порядок картинок в запросе | Хардкод image_order_note в vision_analyzer.py |
| Генерация изображения (Take COPY) | Текст промпта | Только take.custom_prompt (результат Vision) |
| Генерация изображения (Take COPY) | model, size, image_size_tier | model — хардкод "gemini-2.5-flash-image"; size — take.image_size или GenerationPromptSettings (release); tier — GenerationPromptSettings |
| Квота «Сделать такую же» | copy_generations_per_user | SecuritySettings (для Job/регенерации) |

Все системные промпты, которые реально «работают» в полном объёме во флоу «Стиль копирования», — это **system_prompt** и **user_prompt** из `copy_style_settings` (или их fallback в коде) на этапе Vision. Остальные перечисленные выше настройки и тексты участвуют в отображении, квотах, размерах и т.д., но не как дополнительные системные промпты при генерации картинки для COPY.
