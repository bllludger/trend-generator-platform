-- Backfill scene_prompt from legacy system_prompt when empty
UPDATE trends
SET scene_prompt = system_prompt
WHERE (scene_prompt IS NULL OR scene_prompt = '')
  AND system_prompt IS NOT NULL
  AND system_prompt <> '';
