-- Preview rescue flow: one free "replace photo" per trend
ALTER TABLE takes ADD COLUMN IF NOT EXISTS is_rescue_photo_replace BOOLEAN NOT NULL DEFAULT FALSE;
