-- Prompt Sections: храним конфиг из Playground 1:1 в тренде (секции + model/size/format).
-- Если заданы — воркер собирает промпт из секций; иначе используется build_final_prompt_payload.
ALTER TABLE trends ADD COLUMN IF NOT EXISTS prompt_sections JSONB NULL;
ALTER TABLE trends ADD COLUMN IF NOT EXISTS prompt_model VARCHAR(128) NULL;
ALTER TABLE trends ADD COLUMN IF NOT EXISTS prompt_size VARCHAR(32) NULL;
ALTER TABLE trends ADD COLUMN IF NOT EXISTS prompt_format VARCHAR(16) NULL;

COMMENT ON COLUMN trends.prompt_sections IS 'Playground config: list of {id, type, label, content, enabled, order}. When set, worker builds prompt from sections.';
COMMENT ON COLUMN trends.prompt_model IS 'Override model for this trend when prompt_sections is set (e.g. gemini-2.5-flash-image).';
COMMENT ON COLUMN trends.prompt_size IS 'Override size when prompt_sections is set (e.g. 1024x1024).';
COMMENT ON COLUMN trends.prompt_format IS 'Override format when prompt_sections is set (e.g. png).';
