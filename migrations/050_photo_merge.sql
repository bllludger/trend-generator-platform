-- Migration 050: photo_merge_jobs and photo_merge_settings tables

CREATE TABLE IF NOT EXISTS photo_merge_jobs (
    id            TEXT         NOT NULL PRIMARY KEY,
    user_id       TEXT         NOT NULL,
    status        TEXT         NOT NULL DEFAULT 'pending',
    input_paths   JSONB        NOT NULL DEFAULT '[]',
    input_count   INTEGER      NOT NULL DEFAULT 0,
    output_path   TEXT,
    output_format TEXT         NOT NULL DEFAULT 'png',
    input_bytes   BIGINT,
    output_bytes  BIGINT,
    duration_ms   INTEGER,
    error_code    TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_photo_merge_jobs_user_id    ON photo_merge_jobs (user_id);
CREATE INDEX IF NOT EXISTS ix_photo_merge_jobs_status     ON photo_merge_jobs (status);
CREATE INDEX IF NOT EXISTS ix_photo_merge_jobs_created_at ON photo_merge_jobs (created_at);

CREATE TABLE IF NOT EXISTS photo_merge_settings (
    id                  INTEGER     NOT NULL PRIMARY KEY DEFAULT 1,
    output_format       TEXT        NOT NULL DEFAULT 'png',
    jpeg_quality        INTEGER     NOT NULL DEFAULT 92,
    max_output_side_px  INTEGER     NOT NULL DEFAULT 0,
    max_input_file_mb   INTEGER     NOT NULL DEFAULT 20,
    background_color    TEXT        NOT NULL DEFAULT '#ffffff',
    enabled             BOOLEAN     NOT NULL DEFAULT TRUE,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed default settings row (single-row pattern, id=1)
INSERT INTO photo_merge_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
