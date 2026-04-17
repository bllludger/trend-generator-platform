-- Вырезать легаси-фразы из prompt_input в любом месте текста (id=1 Preview, id=2 Release).
-- Идемпотентно: повторный запуск безопасен.

UPDATE generation_prompt_settings
SET
  prompt_task = '',
  prompt_input = BTRIM(
    REGEXP_REPLACE(
      REGEXP_REPLACE(
        REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(prompt_input, ''),
          'IMAGE_1 = trend reference (scene/style). IMAGE_2 = user photo (preserve this identity in output).', ''),
          'Generate a single image: apply the scene and style from the trend to the subject from the user photo.', ''),
          E'Привет, помоги сгенерировать:', ''),
          'Привет, помоги сгенерировать', ''),
      E'\r\n?', E'\n', 'g'),
    E'\n{3,}', E'\n\n', 'g'))
WHERE id IN (1, 2);
