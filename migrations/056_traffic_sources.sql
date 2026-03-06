-- 056: Traffic sources and ad campaigns — deep links (?start=src_<slug>) and budget tracking

-- User: first-touch traffic source (set once on first /start with src_*)
ALTER TABLE users ADD COLUMN IF NOT EXISTS traffic_source VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS traffic_campaign VARCHAR;
CREATE INDEX IF NOT EXISTS idx_users_traffic_source ON users(traffic_source);

-- Traffic sources (channels, publics — where we place links)
CREATE TABLE IF NOT EXISTS traffic_sources (
    id TEXT PRIMARY KEY,
    slug VARCHAR NOT NULL UNIQUE,
    name VARCHAR NOT NULL,
    url TEXT,
    platform VARCHAR NOT NULL DEFAULT 'other',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_traffic_sources_slug ON traffic_sources(slug);
CREATE INDEX IF NOT EXISTS idx_traffic_sources_is_active ON traffic_sources(is_active);

-- Ad campaigns: budget and period for ROI (CPA, ROAS) calculation
CREATE TABLE IF NOT EXISTS ad_campaigns (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES traffic_sources(id) ON DELETE CASCADE,
    name VARCHAR NOT NULL,
    slug VARCHAR,
    budget_rub NUMERIC(12, 2) NOT NULL DEFAULT 0,
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_ad_campaigns_source ON ad_campaigns(source_id);
CREATE INDEX IF NOT EXISTS idx_ad_campaigns_dates ON ad_campaigns(date_from, date_to);
