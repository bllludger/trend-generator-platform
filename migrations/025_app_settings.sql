-- Global app settings (single row): feature toggles and overrides
CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    use_nano_banana_pro BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

INSERT INTO app_settings (id, use_nano_banana_pro)
VALUES (1, FALSE)
ON CONFLICT (id) DO NOTHING;
