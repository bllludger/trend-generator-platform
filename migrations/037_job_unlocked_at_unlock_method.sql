-- Job: источник истины оплаты/разблокировки (целевой).
-- reserved_tokens в paywall access — временная совместимость; после перехода на
-- unlocked_at/unlock_method убрать ветку по reserved_tokens в app/paywall/access.py.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS unlocked_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS unlock_method VARCHAR;
