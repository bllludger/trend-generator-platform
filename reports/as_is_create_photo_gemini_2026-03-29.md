# AS IS: флоу `🔥 Создать фото` → запрос в Gemini (снято 2026-03-29)

## 1) Где и как собирается флоу

1. Бот выбирает тренд и запускает генерацию:
   - [app/bot/handlers/themes.py](/root/ai_slop_2/app/bot/handlers/themes.py#L231) — кнопка `format:{DEFAULT_ASPECT_RATIO}`.
   - [app/bot/handlers/generation.py](/root/ai_slop_2/app/bot/handlers/generation.py#L369) — `celery_app.send_task("app.workers.tasks.generate_take.generate_take", ...)`.

2. Worker `generate_take` собирает prompt/параметры:
   - [app/workers/tasks/generate_take.py](/root/ai_slop_2/app/workers/tasks/generate_take.py#L107) — `_build_prompt_for_take`.
   - [app/workers/tasks/generate_take.py](/root/ai_slop_2/app/workers/tasks/generate_take.py#L605) — формирование `ImageGenerationRequest(...)`.

3. Провайдер Gemini собирает JSON и шлёт в API:
   - [app/services/image_generation/providers/gemini_nano_banana.py](/root/ai_slop_2/app/services/image_generation/providers/gemini_nano_banana.py#L275) — `payload = {"contents": ..., "generationConfig": ...}`.
   - [app/services/image_generation/providers/gemini_nano_banana.py](/root/ai_slop_2/app/services/image_generation/providers/gemini_nano_banana.py#L283) — URL `.../models/{model}:generateContent`.
   - [app/services/image_generation/providers/gemini_nano_banana.py](/root/ai_slop_2/app/services/image_generation/providers/gemini_nano_banana.py#L288) — `client.post(url, params={"key": api_key}, json=payload)`.

## 2) Где хранятся настройки, влияющие на запрос

- `.env` / runtime settings:
  - [app/core/config.py](/root/ai_slop_2/app/core/config.py#L100) (`GEMINI_*`, `IMAGE_PROVIDER`, retry и т.д.)
- Глобальный тумблер провайдера из админки:
  - [app/services/app_settings/settings_service.py](/root/ai_slop_2/app/services/app_settings/settings_service.py#L41) (`use_nano_banana_pro` может принудительно выбрать `gemini`)
- Master Prompt release/defaults:
  - таблица `generation_prompt_settings`, сервис [app/services/generation_prompt/settings_service.py](/root/ai_slop_2/app/services/generation_prompt/settings_service.py#L55)
- Transfer Policy (для трендов):
  - таблица `transfer_policy`, сервис [app/services/transfer_policy/service.py](/root/ai_slop_2/app/services/transfer_policy/service.py#L24)
- Поля конкретного тренда:
  - таблица `trends`, модель [app/models/trend.py](/root/ai_slop_2/app/models/trend.py#L34)

## 3) Текущий AS IS (из живой БД/рантайма)

- Runtime settings (контейнер `api`):
  - `image_provider=gemini`
  - `gemini_image_model=gemini-2.5-flash-image`
  - `gemini_api_endpoint=https://generativelanguage.googleapis.com`
  - `gemini_location=us-central1`
  - `gemini_timeout=180.0`
  - `gemini_safety_settings=''` (пусто)
  - retry: `max_attempts=2`, `backoff=2.0`, `respect_retry_after=True`

- `app_settings` (id=1):
  - `use_nano_banana_pro=true`

- `generation_prompt_settings` (release, id=2 effective):
  - `prompt_input='Привет, помоги сгенерировать:'`
  - `prompt_task=''`
  - `prompt_identity_transfer=''`
  - `safety_constraints=''`
  - `default_model='gemini-3.1-flash-image-preview'`
  - `default_size='1024x1024'`
  - `default_format='png'`
  - `default_temperature=1.0`
  - `default_image_size_tier='4K'`
  - `default_aspect_ratio='1:1'`

- `transfer_policy` (scope=`trends` effective):
  - `identity_rules_text=''`
  - `composition_rules_text=''`
  - `avoid_default_items=''`

- `trends`:
  - всего: `206`, enabled: `204`
  - с `prompt_sections` (array > 0): `34`
  - enabled-трендов с **непустым контентом** в секциях: `1`
  - enabled-трендов без `prompt_model` (берут release default): `170`
  - enabled-трендов без `prompt_temperature`: `170`

## 4) Правила сборки запроса (точно по коду)

### 4.1 Prompt-текст

1. Если `trend.prompt_sections` — это список (даже если контент секций пустой), включается ветка секций:
   - [app/workers/tasks/generate_take.py](/root/ai_slop_2/app/workers/tasks/generate_take.py#L117)
   - Берутся только `enabled && content != ""`.
   - Если после фильтра ничего не осталось: fallback на `trend.scene_prompt || trend.system_prompt`.
   - В этой ветке master/transfer-блоки не добавляются.

2. Если `prompt_sections` отсутствует/пустой:
   - builder добавляет блоки в порядке:
     - `[INPUT]` (из release master prompt)
     - `[TASK]` (из release master prompt)
     - `[IDENTITY TRANSFER]` (из transfer_policy.trends.identity_rules_text)
     - `[COMPOSITION]` (из `trend.composition_prompt` или transfer_policy)
     - `[]` (из `trend.scene_prompt || trend.system_prompt`)
     - `[STYLE]` (из `trend.style_preset`)
     - `[AVOID]` (из transfer `avoid_default_items` + `trend.negative_scene`)
     - `[SAFETY]` (из release master prompt)
     - `[OUTPUT] size=..., format=...`
   - [app/workers/tasks/generate_take.py](/root/ai_slop_2/app/workers/tasks/generate_take.py#L142)

### 4.2 GenerationConfig Gemini

- Всегда:
  - `responseModalities=["IMAGE"]`
  - `temperature` (из request, иначе default провайдера `1.0`)
  - `seed`
  - `imageConfig.aspectRatio` (из `size` через `_size_to_aspect_ratio`)

- Условно:
  - `imageConfig.imageSize` добавляется **только** для моделей:
    - `gemini-3-pro-image-preview`
    - `gemini-3.1-flash-image-preview`
  - [app/services/image_generation/providers/gemini_nano_banana.py](/root/ai_slop_2/app/services/image_generation/providers/gemini_nano_banana.py#L45)

- Для `imageSize` действует clamp:
  - minimum `2K` для поддерживающих моделей (если пришло `1K`, на выходе будет `2K`)
  - [app/services/image_generation/providers/gemini_nano_banana.py](/root/ai_slop_2/app/services/image_generation/providers/gemini_nano_banana.py#L167)

## 5) 1:1 JSON (redacted) — фактически сформированные payload

Ниже JSON получен из runtime-кода провайдера (`provider.generate(...)`) на живых данных take/trend; `key` и base64 картинки заменены.

### 5.1 Реальный take: `ГТА Вайб 🎮` (sections_count=2, но контент пустой → fallback scene_prompt)

```json
{
  "take_id": "f2f5d7b7-15ed-4a97-b443-93d4c000eb48",
  "trend_id": "77cc3658-1aa2-4d50-9af8-b6f775722b42",
  "trend_name": "ГТА Вайб 🎮",
  "request_fields": {
    "model": "gemini-2.5-flash-image",
    "size": "1024x768",
    "temperature": 0.7,
    "seed": 1631017942,
    "image_size_tier": "1K",
    "input_image_path": "/data/generated_images/inputs/AgACAgIAAxkBAAJBgGnGgUHS_OhNlQABkUznwRpi0k8EZwACWBVrG2X8MEpWyxoJPuIWEgEAAwIAA3kAAzoE.jpg"
  },
  "gemini_url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent",
  "gemini_params": {
    "key": "[REDACTED]"
  },
  "gemini_payload_redacted": {
    "contents": [
      {
        "role": "user",
        "parts": [
          {
            "text": "[GOAL]\ntype: edit\nintent: \"Identity-locked photoshoot: keep the same person and face from the identity photo; copy the target scene with high fidelity; apply requested wardrobe if provided.\"\n\n[IDENTITY]\nidentity_lock: on\nmandatory: \"The face must remain strictly unchanged. STRICTLY.\"\nkeep: \"facial geometry, proportions, age markers, distinctive features; hair color + hairstyle silhouette\"\nperson_count: 1\nvisibility_notes: \"full illustrated face visible; hair fully visible with shoulder-length wavy silhouette; ears partially_visible due to hair and glasses arms; neck visible; torso partially_visible; lower body partially_visible\"\n\n[SCENE SOURCE]\nscene_reference_used: \"no\"\nrule: \"If yes: copy scene 1:1 from SCENE_REFERENCE (layout, counts, positions, colors). If no: follow user SCENE text or keep original.\"\n\n[SUBJECT - FROM IDENTITY PHOTO]\npose_expression: \"calm confident expression; direct gaze toward viewer; lips softly closed; head slightly tilted; upper body leaning diagonally toward the foreground\"\nhair: \"light brown to dark blonde wavy shoulder-length hair with volume and side sweep\"\naccessories: \"round eyeglasses x1; small earrings partially_visible\"\n\n[SCENE - COPY WITH FIDELITY]\nobjects_inventory: \"person:illustrated female x1; sleeveless high-neck red top x1; dark belt/waist detail x1 partially_visible; stylized title text block x1; palm trees multiple; skyline buildings multiple; helicopter x1; convertible car x1; people in car x2; hillside sign x1; sunset sky x1\"\nlayout_map: \"single main subject occupies left and center foreground; title text block at upper-right center; city skyline across right and far background; helicopter in upper-right sky; convertible car with two people at lower-right; palm trees on left and right background; hillside sign on left mid-background\"\nbackground: \"sunset Los Angeles-like city scene with warm orange-pink sky, palm trees, distant skyline, cinematic game-poster atmosphere; visible stylized title text is part of the original scene\"\n\n[TARGET WARDROBE - FROM USER REQUEST]\nwardrobe: \"keep original outfit\"\nwardrobe_constraints: \"preserve sleeveless red high-neck fitted top\"\n\n[COMPOSITION | LIGHT | STYLE | OUTPUT]\ncomposition: \"wide poster-style framing, foreground character enlarged, dynamic diagonal pose, layered background elements, clean readable poster balance\"\nlighting_color: \"warm sunset lighting with orange-pink sky tones and soft golden highlights\"\nstyle: \"stylized illustrated game-poster artwork, polished digital painting, cinematic retro-action aesthetic\"\n\n[NEGATIVE - LIGHT]\navoid: \"extra people beyond original scene, any face change, altered facial geometry, low-res, blur, muddy details, deformed hands, extra fingers, incorrect object counts, removed skyline, removed helicopter, removed car, missing title block, random added logos or text outside the original scene\"\n\nAvoid: размытие, артефакты, низкое качество"
          },
          {
            "inlineData": {
              "mimeType": "image/jpeg",
              "data": "[BASE64_IMAGE_REDACTED]"
            }
          }
        ]
      }
    ],
    "generationConfig": {
      "responseModalities": [
        "IMAGE"
      ],
      "temperature": 0.7,
      "seed": 1631017942,
      "imageConfig": {
        "aspectRatio": "3:4"
      }
    }
  }
}
```

### 5.2 Реальный take: `Белая Элегантность 🤍` (sections_count=0 → unified builder с `[INPUT]...[OUTPUT]`)

```json
{
  "take_id": "7358e540-0b09-41b1-8d17-f6ba8d55a571",
  "trend_id": "b8faa57d-04eb-441c-b277-50d15afb4871",
  "trend_name": "Белая Элегантность 🤍",
  "request_fields": {
    "model": "gemini-3.1-flash-image-preview",
    "size": "1024x768",
    "temperature": null,
    "seed": 265462010,
    "image_size_tier": "1K",
    "input_image_path": "/data/generated_images/inputs/AgACAgIAAxkBAAJBmWnGkjpc61XBiqZ8jroWx2Pks7ndAAIPDWsbQTVJSzLdH9gMJdOkAQADAgADeQADOgQ.jpg"
  },
  "gemini_url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent",
  "gemini_params": {
    "key": "[REDACTED]"
  },
  "gemini_payload_redacted": {
    "contents": [
      {
        "role": "user",
        "parts": [
          {
            "text": "[INPUT]\nПривет, помоги сгенерировать:\n\n[]\n[GOAL]\ntype: edit\nintent: \"Identity-locked photoshoot: keep the same person and face from the identity photo; preserve the original studio portrait scene with high fidelity; keep the elegant monochrome wardrobe and refined jewelry styling.\"\n\n[IDENTITY]\nidentity_lock: on\nmandatory: \"The face must remain strictly unchanged. STRICTLY.\"\nkeep: \"facial geometry, proportions, age markers, distinctive features; hair color + hairstyle silhouette\"\nperson_count: 1\nvisibility_notes: \"face fully visible from frontal angle; both ears partially_visible with visible hoop earrings; one hand supporting chin, other hand visible in lower foreground; lower body partially_visible; no identity-critical occlusion\"\n\n[SCENE SOURCE]\nscene_reference_used: \"no\"\nrule: \"No SCENE_REFERENCE provided: keep the original identity photo scene with minimal creative deviation.\"\n\n[SUBJECT - FROM IDENTITY PHOTO]\npose_expression: \"seated portrait, frontal gaze, direct eye contact, calm composed confident expression, chin resting on one hand, other arm relaxed across lap\"\nhair: \"dark hair, center-parted, sleek and tightly pulled back\"\naccessories: \"large gold hoop earrings, thin ring, red manicure\"\n\n[SCENE - COPY WITH FIDELITY]\nobjects_inventory: \"woman:1; white tailored blazer:1; matching white trousers:1 partially_visible; gold hoop earrings:2; ring:1; light-gray seamless studio background:1; small decorative star-like mark in lower-right corner:1 ambiguous\"\nlayout_map: \"subject centered in frame, upper torso dominant in midground, supporting hand under chin in center, crossed arm and knee in lower foreground, neutral background filling full rear plane, no furniture clearly visible, minimal empty negative space around subject\"\nbackground: \"clean seamless light-gray studio backdrop, polished commercial portrait setup, no visible props, no logos, minimal shadowing\"\n\n[TARGET WARDROBE - FROM USER REQUEST]\nwardrobe: \"keep original outfit\"\nwardrobe_constraints: \"do not change the white tailored suit, red lipstick, or gold jewelry styling\"\n\n[COMPOSITION | LIGHT | STYLE | OUTPUT]\ncomposition: \"vertical studio portrait, medium seated shot, centered editorial framing, sharp facial focus, clean luxury composition\"\nlighting_color: \"soft diffused beauty lighting, even frontal illumination, gentle sculpting on face, neutral-gray background, warm natural skin rendering\"\nstyle: \"photoreal luxury fashion editorial portrait\"\n\n[NEGATIVE - LIGHT]\navoid: \"extra people, any face change, beauty retouch, altered facial geometry, plastic skin, deformed hands, extra fingers, blur, low-res, watermark, any text/logos, added objects, missing objects\"\n\n[OUTPUT]\nsize=1024x768, format=png"
          },
          {
            "inlineData": {
              "mimeType": "image/jpeg",
              "data": "[BASE64_IMAGE_REDACTED]"
            }
          }
        ]
      }
    ],
    "generationConfig": {
      "responseModalities": [
        "IMAGE"
      ],
      "temperature": 1.0,
      "seed": 265462010,
      "imageConfig": {
        "aspectRatio": "3:4",
        "imageSize": "2K"
      }
    }
  }
}
```

### 5.3 Тренд с непустыми секциями (`С букетом 101 розы`) — точный payload branch `prompt_sections`

```json
{
  "trend_id": "c8c96d15-ca9e-49df-8e16-c501be301125",
  "trend_name": "С букетом 101 розы",
  "request_fields": {
    "model": "gemini-3.1-flash-image-preview",
    "size": "1024x1024",
    "temperature": 0.3,
    "image_size_tier": "4K",
    "negative_prompt_present": false
  },
  "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent",
  "params": {
    "key": "[REDACTED]"
  },
  "payload_redacted": {
    "contents": [
      {
        "role": "user",
        "parts": [
          {
            "text": "[]\n[GOAL]\ntype: edit\nintent: \"Identity-locked photoshoot: keep the same person and face from the identity photo; copy the target scene with high fidelity; apply requested wardrobe if provided.\"\n\n[IDENTITY]\nidentity_lock: on\nmandatory: \"The face must remain strictly unchanged. STRICTLY.\"\nkeep: \"facial geometry, proportions, age markers, distinctive features; hair color + hairstyle silhouette\"\nperson_count: 1\nvisibility_notes: \"Identity photo is the only identity source. If any features are partially_visible/occluded/not_visible, keep them unchanged and ambiguous. No beautify, no reshaping.\"\n\n[SCENE SOURCE]\nscene_reference_used: \"yes\"\nrule: \"If yes: copy scene 1:1 from SCENE_REFERENCE (layout, counts, positions, colors). If no: follow user SCENE text or keep original.\"\n\n[SUBJECT - FROM IDENTITY PHOTO]\npose_expression: \"keep the exact pose/expression from the identity photo (mirror selfie; expression as-is).\"\nhair: \"keep exact hair color and hairstyle silhouette from the identity photo.\"\naccessories: \"keep only what exists in the identity photo (ambiguous).\"\n\n[SCENE - COPY WITH FIDELITY]\nobjects_inventory: \"full-length mirror x1 (white frame); minimal room interior x1; plain gray wall x1; white baseboard x1; light wood floor x1; large window/light source on right x1 (bright daylight); phone x1 held up near face level; bouquet of red roses x1 with EXACTLY 101 roses (tight, round arrangement), deep red petals, minimal greenery; second bouquet partially_visible x1 at bottom edge (keep as in reference if present); optional film-overlay border text x2 along left/right edges (vertical 'KODAK PORTRA 400' and small numbers).\"\nlayout_map: \"camera view is a mirror selfie. Mirror fills most of frame; white frame visible on both sides. Background inside mirror: empty gray wall center-left, white baseboard, light wood floor. Strong daylight enters from the right side (window area). Foreground inside mirror: one person positioned left-center, kneeling/sitting low; phone held up near upper center. The HUGE bouquet with EXACTLY 101 red roses occupies the right half, overlapping the subject’s torso/arms; a second bouquet is cropped at the bottom edge if present in the reference.\"\nbackground: \"clean modern interior, neutral gray tones, high natural light, no extra decor.\"\n\n[TARGET WARDROBE - FROM USER REQUEST]\nwardrobe: \"keep original outfit from the identity photo (no wardrobe change requested).\"\nwardrobe_constraints: \"no logos, no added text.\"\n\n[COMPOSITION | LIGHT | STYLE | OUTPUT]\ncomposition: \"vertical portrait, mirror selfie framing, medium shot with strong foreground bouquet; shallow-to-moderate depth of field.\"\nlighting_color: \"bright natural daylight from right, warm highlights, soft shadows on the left.\"\nstyle: \"photoreal, crisp rose texture, realistic mirror reflections and natural skin texture.\"\n\n[NEGATIVE - LIGHT]\navoid: \"extra people, any face change, beauty retouch, altered facial geometry, plastic skin, deformed hands, extra fingers, blur, low-res, watermark, any text/logos not present in the scene, added objects, missing objects, wrong rose count (must be exactly 101)\""
          },
          {
            "inlineData": {
              "mimeType": "image/jpeg",
              "data": "[BASE64_IMAGE_REDACTED]"
            }
          }
        ]
      }
    ],
    "generationConfig": {
      "responseModalities": [
        "IMAGE"
      ],
      "temperature": 0.3,
      "seed": 123456789,
      "imageConfig": {
        "aspectRatio": "1:1",
        "imageSize": "4K"
      }
    }
  }
}
```

## 6) Важные AS IS наблюдения

- `GEMINI_API_KEY` передаётся как query-параметр `?key=...` (не в header).
- `gemini_safety_settings` сейчас пустой, значит `safetySettings` в payload не отправляется.
- В `generate_take` для трендов **не передаются** `topP`, `candidateCount`, `mediaResolution`, `thinkingConfig` (они есть в playground, но не в create-photo flow).
- Если `trend.prompt_temperature` пустой, в Gemini уходит `temperature=1.0` (default провайдера), а не `default_temperature` из master prompt.
- Для `gemini-3.1-flash-image-preview` при `image_size_tier=1K` в payload уходит `imageSize=2K` (минимум 2K по clamp-логике).
- `send_style_reference_to_api` есть в settings ([app/core/config.py](/root/ai_slop_2/app/core/config.py#L119)), но в текущем флоу `create photo` не используется.
- Файлы `config/image_generation.yaml` и `app/services/image_generation_config.py` в текущем дереве проекта отсутствуют.

