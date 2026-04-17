-- 074: cleanup legacy prompt defaults that could shadow Master Prompt release defaults.

-- Ensure advanced candidate count aligns with ORM/service expectation.
UPDATE generation_prompt_settings
SET default_candidate_count = 1
WHERE default_candidate_count IS NULL;

ALTER TABLE generation_prompt_settings
    ALTER COLUMN default_candidate_count SET NOT NULL;

-- Keep DB default for aspect ratio aligned with model/service fallback.
ALTER TABLE generation_prompt_settings
    ALTER COLUMN default_aspect_ratio SET DEFAULT '3:4';

-- Stop implicit trend-level overrides for aspect/image tier/temperature.
ALTER TABLE trends ALTER COLUMN prompt_aspect_ratio DROP DEFAULT;
ALTER TABLE trends ALTER COLUMN prompt_image_size_tier DROP DEFAULT;
ALTER TABLE trends ALTER COLUMN prompt_temperature DROP DEFAULT;

-- Backfill likely auto-defaulted legacy values to NULL when the trend has no explicit Playground advanced overrides.
UPDATE trends
SET
    prompt_aspect_ratio = NULL,
    prompt_image_size_tier = NULL,
    prompt_temperature = NULL
WHERE
    prompt_aspect_ratio = '1:1'
    AND prompt_image_size_tier = '1K'
    AND (prompt_temperature = 0.7 OR prompt_temperature IS NULL)
    AND prompt_model IS NULL
    AND prompt_size IS NULL
    AND prompt_format IS NULL
    AND prompt_seed IS NULL
    AND prompt_top_p IS NULL
    AND prompt_candidate_count IS NULL
    AND prompt_media_resolution IS NULL
    AND prompt_thinking_config IS NULL;
