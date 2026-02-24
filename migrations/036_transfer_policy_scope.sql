-- Transfer Policy: два набора — global и trends (Мастер промпт).
-- Убираем ограничение id=1, добавляем scope, создаём вторую запись для трендов.
ALTER TABLE transfer_policy DROP CONSTRAINT IF EXISTS transfer_policy_id_check;
ALTER TABLE transfer_policy ADD COLUMN IF NOT EXISTS scope VARCHAR(32) NOT NULL DEFAULT 'global';

UPDATE transfer_policy SET scope = 'global' WHERE scope IS NULL OR scope = '';

-- Вторая запись для трендов (копия глобальной, если ещё нет)
INSERT INTO transfer_policy (id, scope, identity_lock_level, identity_rules_text, composition_rules_text, subject_reference_name, avoid_default_items, updated_at)
SELECT 2, 'trends', identity_lock_level, identity_rules_text, composition_rules_text, subject_reference_name, COALESCE(avoid_default_items, ''), NOW()
FROM transfer_policy WHERE id = 1
ON CONFLICT (id) DO NOTHING;

CREATE UNIQUE INDEX IF NOT EXISTS ix_transfer_policy_scope ON transfer_policy(scope);
