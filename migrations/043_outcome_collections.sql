-- 043: Outcome Collections

-- Pack: collection fields
ALTER TABLE packs ADD COLUMN IF NOT EXISTS pack_subtype TEXT NOT NULL DEFAULT 'standalone';
ALTER TABLE packs ADD COLUMN IF NOT EXISTS playlist JSONB;
ALTER TABLE packs ADD COLUMN IF NOT EXISTS favorites_cap INTEGER;
ALTER TABLE packs ADD COLUMN IF NOT EXISTS collection_label TEXT;
ALTER TABLE packs ADD COLUMN IF NOT EXISTS upsell_pack_ids JSONB;
ALTER TABLE packs ADD COLUMN IF NOT EXISTS hd_sla_minutes INTEGER NOT NULL DEFAULT 10;

-- Session: collection runtime
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS playlist JSONB;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS current_step INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS hd_limit INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS hd_used INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS collection_run_id TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS input_photo_path TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS input_file_id TEXT;

-- Take: step tracking
ALTER TABLE takes ADD COLUMN IF NOT EXISTS step_index INTEGER;
ALTER TABLE takes ADD COLUMN IF NOT EXISTS is_reroll BOOLEAN NOT NULL DEFAULT FALSE;

-- User: consent / data deletion
ALTER TABLE users ADD COLUMN IF NOT EXISTS consent_accepted_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS data_deletion_requested_at TIMESTAMPTZ;

-- Favorite: explicit HD selection + idempotent compensation flag
ALTER TABLE favorites ADD COLUMN IF NOT EXISTS selected_for_hd BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE favorites ADD COLUMN IF NOT EXISTS compensated_at TIMESTAMPTZ;

-- Compensation log
CREATE TABLE IF NOT EXISTS compensation_log (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    favorite_id TEXT REFERENCES favorites(id),
    session_id  TEXT REFERENCES sessions(id),
    reason      TEXT NOT NULL,
    comp_type   TEXT NOT NULL DEFAULT 'hd_credit',
    amount      INTEGER NOT NULL DEFAULT 1,
    correlation_id TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_compensation_log_user ON compensation_log(user_id);

-- MVP SKU: Dating Pack & Avatar Pack
-- enabled=FALSE until playlist is filled via admin UI.
-- Collection with playlist=NULL MUST NOT be sold (enforced in PaymentService).
INSERT INTO packs (id, name, emoji, tokens, stars_price, description,
    takes_limit, hd_amount, is_trial, pack_type, pack_subtype,
    playlist, favorites_cap, collection_label, enabled, order_index)
VALUES
    ('dating_pack', 'Dating Pack', '💕', 0, 499,
     '6 образов для дейтинга — 18 превью, до 10 HD',
     6, 10, FALSE, 'session', 'collection',
     NULL, 20, 'Dating Pack — 6 образов', FALSE, 10),
    ('avatar_pack', 'Avatar Pack', '🎭', 0, 349,
     '4 стиля аватара — 12 превью, до 6 HD',
     4, 6, FALSE, 'session', 'collection',
     NULL, 12, 'Avatar Pack — 4 стиля', FALSE, 11)
ON CONFLICT (id) DO NOTHING;
