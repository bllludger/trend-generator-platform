-- 067: Additional indexes for audit and telemetry (filter by entity_type, analytics)
-- Speeds up: GET /admin/audit?entity_type=... and analytics by entity_type

CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_type_created_at ON audit_logs(entity_type, created_at DESC);
