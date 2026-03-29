-- Global default aspect ratio -> 3:4
ALTER TABLE generation_prompt_settings
    ALTER COLUMN default_aspect_ratio SET DEFAULT '3:4';

UPDATE generation_prompt_settings
SET default_aspect_ratio = '3:4'
WHERE id IN (1, 2);
