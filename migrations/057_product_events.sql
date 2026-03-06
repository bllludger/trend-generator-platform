-- 057: Product analytics events — funnel, quality, trends, attribution (single source of truth for product metrics)

CREATE TABLE IF NOT EXISTS product_events (
    id TEXT PRIMARY KEY,
    event_name VARCHAR NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT,
    "timestamp" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trend_id VARCHAR,
    pack_id VARCHAR,
    source VARCHAR,
    campaign_id VARCHAR,
    creative_id VARCHAR,
    deep_link_id VARCHAR,
    device_type VARCHAR,
    country VARCHAR,
    take_id TEXT,
    job_id TEXT,
    entity_type VARCHAR,
    entity_id TEXT,
    properties JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_product_events_event_name_timestamp ON product_events(event_name, "timestamp");
CREATE INDEX IF NOT EXISTS idx_product_events_user_id_timestamp ON product_events(user_id, "timestamp");
CREATE INDEX IF NOT EXISTS idx_product_events_session_id_timestamp ON product_events(session_id, "timestamp") WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_product_events_trend_id_timestamp ON product_events(trend_id, "timestamp") WHERE trend_id IS NOT NULL;
