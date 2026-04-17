-- Face-ID v1: assets + settings + take linkage.

CREATE TABLE IF NOT EXISTS face_assets (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    session_id VARCHAR NULL,
    chat_id VARCHAR NULL,
    flow VARCHAR(32) NOT NULL DEFAULT 'trend',
    source_path VARCHAR NOT NULL,
    processed_path VARCHAR NULL,
    selected_path VARCHAR NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    faces_detected INTEGER NULL,
    primary_face_bbox JSONB NULL,
    crop_bbox JSONB NULL,
    reason_code VARCHAR(64) NULL,
    request_id VARCHAR(128) NULL,
    last_event_id VARCHAR(128) NULL,
    latency_ms INTEGER NULL,
    detector_meta JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_face_assets_user_id ON face_assets(user_id);
CREATE INDEX IF NOT EXISTS ix_face_assets_session_id ON face_assets(session_id);
CREATE INDEX IF NOT EXISTS ix_face_assets_request_id ON face_assets(request_id);
CREATE INDEX IF NOT EXISTS ix_face_assets_created_at ON face_assets(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_face_assets_status ON face_assets(status);

CREATE TABLE IF NOT EXISTS face_id_settings (
    id INTEGER PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    min_detection_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.6,
    model_selection INTEGER NOT NULL DEFAULT 1,
    crop_pad_left DOUBLE PRECISION NOT NULL DEFAULT 0.35,
    crop_pad_right DOUBLE PRECISION NOT NULL DEFAULT 0.35,
    crop_pad_top DOUBLE PRECISION NOT NULL DEFAULT 0.7,
    crop_pad_bottom DOUBLE PRECISION NOT NULL DEFAULT 0.35,
    max_faces_allowed INTEGER NOT NULL DEFAULT 1,
    no_face_policy VARCHAR(64) NOT NULL DEFAULT 'fallback_original',
    multi_face_policy VARCHAR(64) NOT NULL DEFAULT 'fail_generation',
    callback_timeout_seconds DOUBLE PRECISION NOT NULL DEFAULT 2.0,
    callback_max_retries INTEGER NOT NULL DEFAULT 3,
    callback_backoff_seconds DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO face_id_settings (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

ALTER TABLE takes
    ADD COLUMN IF NOT EXISTS face_asset_id VARCHAR NULL;

CREATE INDEX IF NOT EXISTS ix_takes_face_asset_id ON takes(face_asset_id);

