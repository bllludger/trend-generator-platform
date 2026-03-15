# Архитектура: Мастер промпт (централизация)

Обновлено после внедрения раздела «Мастер промпт» и единого билдера.

## Источники данных

| Блок в промпте | Источник |
|----------------|----------|
| [INPUT] | Generation Prompt Settings (мастер) |
| [TASK] | Generation Prompt Settings (мастер) |
| [IDENTITY TRANSFER] | Transfer Policy **для трендов** (scope=trends) |
| [COMPOSITION] | Transfer Policy для трендов |
| [SCENE] | Тренд (scene_prompt) |
| [STYLE] | Тренд (style_preset) |
| [AVOID] | Transfer Policy для трендов (avoid_default_items) + тренд (negative_scene) |
| [SAFETY] | Generation Prompt Settings (мастер) |
| [OUTPUT] | size, format (job/дефолты мастера) |

## Два набора переноса личности

- **Глобально (scope=global)** — для Copy style, Playground и прочих сценариев не по тренду.
- **Для трендов (scope=trends)** — подставляется воркером при генерации по тренду.

Оба набора редактируются в админке на странице **«Мастер промпт»** (вкладки «Перенос (глобально)» и «Перенос (для трендов)»).

## Точка сборки

Единый билдер: `_build_prompt_for_job()` в [app/workers/tasks/generation_v2.py](app/workers/tasks/generation_v2.py).  
Исключение: если у тренда заданы `prompt_sections` (Playground), промпт собирается только из секций, без блоков мастера.

## Админка

- **Мастер промпт** (`/master-prompt`): три вкладки — «Системный промпт», «Перенос (глобально)», «Перенос (для трендов)».
- **Тренды**: структура тренда = [SCENE], [STYLE], [AVOID] (negative_scene). Ссылка на настройку глобальных блоков ведёт в «Мастер промпт».
