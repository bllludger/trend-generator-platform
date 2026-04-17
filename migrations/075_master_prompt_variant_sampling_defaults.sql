-- Master Prompt: per-variant sampling defaults for TREND A/B/C previews.
ALTER TABLE generation_prompt_settings
    ADD COLUMN IF NOT EXISTS default_temperature_a DOUBLE PRECISION;

ALTER TABLE generation_prompt_settings
    ADD COLUMN IF NOT EXISTS default_temperature_b DOUBLE PRECISION;

ALTER TABLE generation_prompt_settings
    ADD COLUMN IF NOT EXISTS default_temperature_c DOUBLE PRECISION;

ALTER TABLE generation_prompt_settings
    ADD COLUMN IF NOT EXISTS default_top_p_a DOUBLE PRECISION;

ALTER TABLE generation_prompt_settings
    ADD COLUMN IF NOT EXISTS default_top_p_b DOUBLE PRECISION;

ALTER TABLE generation_prompt_settings
    ADD COLUMN IF NOT EXISTS default_top_p_c DOUBLE PRECISION;
