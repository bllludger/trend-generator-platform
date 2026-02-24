-- Add updated_at to favorites for watchdog rendering timeout detection
ALTER TABLE favorites
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
