-- 040: Session-based model — sessions, takes, favorites + pack/user/payment extensions

-- Sessions
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    pack_id     TEXT NOT NULL,
    takes_limit INTEGER NOT NULL DEFAULT 0,
    takes_used  INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'active',
    upgraded_from_session_id TEXT REFERENCES sessions(id),
    upgrade_credit_stars INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_sessions_user_status ON sessions(user_id, status);

-- Takes
CREATE TABLE IF NOT EXISTS takes (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT REFERENCES sessions(id),
    user_id             TEXT NOT NULL REFERENCES users(id),
    take_type           TEXT NOT NULL DEFAULT 'TREND',
    trend_id            TEXT,
    custom_prompt       TEXT,
    image_size          TEXT,
    input_file_ids      JSONB NOT NULL DEFAULT '[]'::jsonb,
    input_local_paths   JSONB NOT NULL DEFAULT '[]'::jsonb,
    copy_reference_path TEXT,
    status              TEXT NOT NULL DEFAULT 'generating',
    variant_a_preview   TEXT,
    variant_b_preview   TEXT,
    variant_c_preview   TEXT,
    variant_a_original  TEXT,
    variant_b_original  TEXT,
    variant_c_original  TEXT,
    seed_a              INTEGER,
    seed_b              INTEGER,
    seed_c              INTEGER,
    error_code          TEXT,
    error_variants      JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_takes_session_id ON takes(session_id);
CREATE INDEX IF NOT EXISTS ix_takes_user_id ON takes(user_id);

-- Favorites
CREATE TABLE IF NOT EXISTS favorites (
    id            TEXT PRIMARY KEY,
    session_id    TEXT REFERENCES sessions(id),
    user_id       TEXT NOT NULL REFERENCES users(id),
    take_id       TEXT NOT NULL REFERENCES takes(id),
    variant       TEXT NOT NULL,
    preview_path  TEXT NOT NULL,
    original_path TEXT NOT NULL,
    hd_status     TEXT NOT NULL DEFAULT 'none',
    hd_path       TEXT,
    hd_job_id     TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_favorites_user_take_variant UNIQUE (user_id, take_id, variant)
);

CREATE INDEX IF NOT EXISTS ix_favorites_session_id ON favorites(session_id);
CREATE INDEX IF NOT EXISTS ix_favorites_user_id ON favorites(user_id);
CREATE INDEX IF NOT EXISTS ix_favorites_take_id ON favorites(take_id);

-- Pack extensions for session-based model
ALTER TABLE packs ADD COLUMN IF NOT EXISTS takes_limit INTEGER;
ALTER TABLE packs ADD COLUMN IF NOT EXISTS hd_amount INTEGER;
ALTER TABLE packs ADD COLUMN IF NOT EXISTS is_trial BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE packs ADD COLUMN IF NOT EXISTS pack_type TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE packs ADD COLUMN IF NOT EXISTS upgrade_target_pack_ids JSONB;

-- User extensions for HD balance
ALTER TABLE users ADD COLUMN IF NOT EXISTS hd_paid_balance INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS hd_promo_balance INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS free_takes_used INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_purchased BOOLEAN NOT NULL DEFAULT FALSE;

-- Payment link to session
ALTER TABLE payments ADD COLUMN IF NOT EXISTS session_id TEXT REFERENCES sessions(id);
