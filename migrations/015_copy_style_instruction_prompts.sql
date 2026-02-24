-- Инструкции для Gemini при флоу «Сделать такую же»: 3 фото (стиль + 2 лица) и 2 фото (2 лица).
-- Редактируются в админке «Сделать такую же» → вклад «Инструкции для генерации».
ALTER TABLE copy_style_settings ADD COLUMN IF NOT EXISTS prompt_instruction_3_images TEXT NOT NULL DEFAULT '';
ALTER TABLE copy_style_settings ADD COLUMN IF NOT EXISTS prompt_instruction_2_images TEXT NOT NULL DEFAULT '';

-- Дефолты на английском для Gemini (1=стиль, 2=лицо девушки, 3=лицо парня)
UPDATE copy_style_settings
SET
  prompt_instruction_3_images = COALESCE(NULLIF(TRIM(prompt_instruction_3_images), ''), 'Attached images order: (1) Style/scene reference to replicate. (2) Use this person''s face for the woman/female character. (3) Use this person''s face for the man/male character. Generate the scene in the described style with these two faces.'),
  prompt_instruction_2_images = COALESCE(NULLIF(TRIM(prompt_instruction_2_images), ''), 'Attached images order: (1) Use this face for the woman/female character. (2) Use this face for the man/male character. Generate the scene with these faces.')
WHERE id = 1;
