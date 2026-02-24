-- Split trend prompt into scene and subject-transfer blocks
ALTER TABLE trends ADD COLUMN IF NOT EXISTS scene_prompt TEXT;
ALTER TABLE trends ADD COLUMN IF NOT EXISTS subject_prompt TEXT;
