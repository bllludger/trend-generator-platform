-- Playground advanced generation params persistence on trends
ALTER TABLE trends ADD COLUMN IF NOT EXISTS prompt_top_p DOUBLE PRECISION NULL;
ALTER TABLE trends ADD COLUMN IF NOT EXISTS prompt_candidate_count INTEGER NULL;
ALTER TABLE trends ADD COLUMN IF NOT EXISTS prompt_media_resolution VARCHAR(16) NULL;
ALTER TABLE trends ADD COLUMN IF NOT EXISTS prompt_thinking_config JSONB NULL;

COMMENT ON COLUMN trends.prompt_top_p IS 'Playground/Vertex generationConfig.topP (0.0..1.0).';
COMMENT ON COLUMN trends.prompt_candidate_count IS 'Playground generationConfig.candidateCount (UI-limited to 1..4).';
COMMENT ON COLUMN trends.prompt_media_resolution IS 'Playground generationConfig.mediaResolution: LOW|MEDIUM|HIGH.';
COMMENT ON COLUMN trends.prompt_thinking_config IS 'Playground generationConfig.thinkingConfig payload (stored as JSON).';
