-- Telemetry snapshots for historical analytics
-- Optional: run manually or via Celery beat

CREATE TABLE IF NOT EXISTS telemetry_snapshots (
    id TEXT PRIMARY KEY,
    snapshot_at TIMESTAMPTZ NOT NULL,
    window_hours INT NOT NULL DEFAULT 24,
    jobs_created INT NOT NULL DEFAULT 0,
    jobs_succeeded INT NOT NULL DEFAULT 0,
    jobs_failed INT NOT NULL DEFAULT 0,
    queue_length INT NOT NULL DEFAULT 0,
    unique_users_active INT NOT NULL DEFAULT 0,
    by_trend JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telemetry_snapshots_at ON telemetry_snapshots(snapshot_at DESC);
