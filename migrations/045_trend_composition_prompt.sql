-- 045: Тренд — опциональный блок [COMPOSITION] (правила композиции/размещения субъекта)
ALTER TABLE trends ADD COLUMN IF NOT EXISTS composition_prompt TEXT NULL;
