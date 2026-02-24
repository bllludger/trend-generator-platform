# Сущности промптов и пример запроса к Gemini

## 1. Где лежат сущности промптов

| Сущность | Где | Назначение |
|----------|-----|------------|
| **prompt_generation.yaml** | `prompts/prompt_generation.yaml` | Базовый конфиг генерации: префикс системного промпта, negative prefix, safety, размер/формат, модель. |
| **prompt_admin.yaml** | `prompts/prompt_admin.yaml` | Промпт для админ-ассистента (не для генерации картинок). |
| **Тренды (YAML)** | `prompts/trends/<slug>__<trend_id>.yaml` | Один файл на тренд: `name`, `display_name`, `trend_id`, `system_prompt`, `negative_prompt`, `style_preset`. Опционально: `scene_prompt`, `subject_prompt`. |
| **Настройки генерации (БД)** | Таблица `generation_prompt_settings` | Включённые блоки и текст: system_prompt_prefix, definitions, priority_order, identity_rules, negative_constraints, negative_prompt_prefix, safety_constraints, image_constraints_template, default_model/size/format/temperature. |
| **Тренд (БД)** | Таблица `trends` | `system_prompt`, `scene_prompt`, `subject_prompt`, `negative_prompt`, `style_preset` (JSONB). При генерации используется либо YAML тренда (если есть файл), либо данные из БД. |

---

## 2. Схема «разнесения»

```
prompts/prompt_generation.yaml     →  базовые строки (prefix, safety, template размера)
         +
generation_prompt_settings (БД)    →  эффективный cfg для build_trend_prompt (может переопределять YAML)
         +
prompts/trends/<slug>__<id>.yaml   →  trend: system_prompt, scene_prompt, subject_prompt, negative_prompt, style_preset
   или
trends (БД)                       →  те же поля, если YAML нет
         ↓
app/services/generation_prompt/builder.py  →  build_trend_prompt(cfg, trend, size, format, model)
         ↓
Один текст промпта с блоками: [SYSTEM], [DEFINITIONS], [PRIORITY ORDER], [IDENTITY RULES], [SCENE], [SUBJECT TRANSFER], [NEGATIVE CONSTRAINTS], [NEGATIVE APPEND], [SAFETY], [OUTPUT]
         ↓
ImageGenerationRequest(prompt=..., negative_prompt=..., input_image_path=...)
         ↓
Gemini provider: contents[0].parts = [ image(s), text(prompt + "\n\nAvoid: " + negative) ]
```

---

## 3. Поля тренда (YAML или БД)

| Поле | Описание |
|------|----------|
| **name** | Слаг (идент в файле). |
| **display_name** | Человекочитаемое название. |
| **trend_id** | UUID тренда. |
| **system_prompt** | Основной текст сцены/стиля (или JSON с subject/pose/environment/camera и т.д.). |
| **scene_prompt** | Отдельный блок сцены (если нет — берётся system_prompt). |
| **subject_prompt** | Перенос субъекта (лицо/тело с фото). |
| **negative_prompt** | Что избегать в картинке. |
| **style_preset** | Словарь ключ–значение (vibe, style, lighting, aspect_ratio и т.д.), подставляется в шаблоны и выводится в [SCENE]. |

---

## 4. Пример: что получает Gemini

Запрос в API Gemini имеет вид:

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        { "inline_data": { "mime_type": "image/jpeg", "data": "<base64 фото пользователя>" } },
        { "text": "<единая строка промпта (см. ниже)>" }
      ]
    }
  ],
  "generationConfig": {
    "responseModalities": ["TEXT", "IMAGE"],
    "imageConfig": { "aspectRatio": "3:4" },
    "temperature": 0.7
  }
}
```

Текстовая часть `parts[].text` формируется так:

- Основной промпт = результат `build_trend_prompt(...)["prompt"]` (см. пример ниже).
- Если задан `negative_prompt`, провайдер дописывает: `prompt_text += "\n\nAvoid: " + negative_prompt`.

---

## 5. Пример текста промпта для одного тренда (как уходит в Gemini)

Тренд: **90** (Портрет с вспышкой в стиле 90-х), `prompt_generation.yaml` + дефолтный cfg из БД.

**Итоговая строка `prompt` (то, что уходит в Gemini как одна текстовая часть):**

```
[SYSTEM]
You are an image generation system. Follow the trend instructions precisely.

[SCENE]
Without changing her original face, create a portrait of a beautiful young woman with porcelain-white skin, captured with a 1990s-style camera using a direct front flash. Her messy dark brown hair is tied up, posing with a calm yet playful smile. She wears a modern oversized cream sweater. The background is a dark white wall covered with aesthetic magazine posters and stickers, evoking a cozy bedroom or personal room atmosphere under dim lighting. The 35mm lens flash creates a nostalgic glow.

{"vibe": "calm_playful_intimate", "grain": "subtle_analog", "style": "90s_flash_portrait_photorealism", "framing": "portrait_close_up", "quality": "8k", "lighting": "direct_front_flash", "aspect_ratio": "3:4", "color_grading": "warm_flash_neutral_shadows", "identity_lock": "strict_face_preservation", "texture_focus": true, "camera_profile": "35mm_point_and_shoot", "skin_rendering": "porcelain_soft_glow", "background_style": "nostalgic_bedroom_collage"}

[NEGATIVE APPEND]
negative_prompt: 

[SAFETY]
no text generation, no chat.

[OUTPUT]
image_constraints: size=1024x1024, format=png
```

Если у тренда был бы непустой `negative_prompt` (например, «студийный свет»), провайдер добавит в конец текста, который видит модель:

```
Avoid: студийный свет
```

Порядок частей в `contents[0].parts`: сначала все входные изображения (base64), затем одна часть `text` с этой строкой.

---

## 6. Где изображение в запросе и нужно ли объединять его с промптом

### Где изображение

- **В поле `prompt` (текст) изображения нет** — там только строка с блоками [INPUT], [TASK], [SCENE] и т.д.
- **Изображение уходит в запросе к Gemini отдельно:**
  - `contents[0].parts[0]` (и при необходимости `parts[1]`, …) — **inline_data** с `mime_type` и `data` (base64 фото пользователя).
  - `contents[0].parts[n]` — **text** с этим промптом.

В аудите (action `generation_request`) в payload есть:
- **`gemini_request_structure`** — псевдо-JSON структуры запроса: какие части (parts), в каком порядке, что в каждой (без байтов изображения).
- **`where_is_the_image`** — кратко: фото в `contents[0].parts[0]`, промпт в `contents[0].parts[1]`.
- **`architecture_note`** — почему изображение и промпт не объединяем в одно поле.

### Нужно ли объединять изображение с промптом

**Нет.** Текущая схема корректна:

1. **Gemini — мультимодальный API:** одно сообщение = массив `parts`. Часть может быть `inline_data` (картинка) или `text`. Порядок частей фиксирован: сначала картинки, потом текст.
2. **Связка «IMAGE_1» ↔ картинка** задаётся порядком: `parts[0]` = первое изображение (фото пользователя), `parts[1]` = текст промпта. В тексте мы пишем «IMAGE_1: subject photo (user). Use as the sole identity source.» — модель получает сначала картинку, потом этот текст и понимает, что IMAGE_1 = первая часть (фото).
3. **Вставлять байты изображения в текст промпта** нельзя (и не нужно): API ожидает отдельные части; объединение в одну строку не предусмотрено и ухудшило бы интерпретацию.

Итог: изображение и промпт **не объединяем**; порядок `parts` (сначала изображение, потом текст) и есть то, как Gemini понимает, что «IMAGE_1» — это приложенное фото.
