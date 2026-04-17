-- Единый мастер-промпт: legacy prompt_task сливается в prompt_input, prompt_task очищается.
-- Убирает дефолты из migrations/034 (IMAGE_1 / Generate a single image...) из раздельных колонок.

UPDATE generation_prompt_settings
SET
  prompt_input = CASE
    WHEN NULLIF(BTRIM(prompt_task), '') IS NOT NULL AND NULLIF(BTRIM(prompt_input), '') IS NOT NULL
      THEN BTRIM(prompt_input) || E'\n\n' || BTRIM(prompt_task)
    WHEN NULLIF(BTRIM(prompt_task), '') IS NOT NULL
      THEN BTRIM(prompt_task)
    ELSE BTRIM(COALESCE(prompt_input, ''))
  END,
  prompt_task = ''
WHERE TRUE;
