-- Master Prompt: Gemini advanced defaults parity with Playground.
ALTER TABLE generation_prompt_settings
    ADD COLUMN IF NOT EXISTS default_top_p DOUBLE PRECISION;

ALTER TABLE generation_prompt_settings
    ADD COLUMN IF NOT EXISTS default_seed INTEGER;

ALTER TABLE generation_prompt_settings
    ADD COLUMN IF NOT EXISTS default_candidate_count INTEGER;

ALTER TABLE generation_prompt_settings
    ADD COLUMN IF NOT EXISTS default_media_resolution VARCHAR(16);

ALTER TABLE generation_prompt_settings
    ADD COLUMN IF NOT EXISTS default_thinking_config JSONB;

ALTER TABLE generation_prompt_settings
    ALTER COLUMN default_candidate_count SET DEFAULT 1;

UPDATE generation_prompt_settings
SET default_candidate_count = 1
WHERE default_candidate_count IS NULL;
