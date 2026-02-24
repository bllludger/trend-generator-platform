-- 041: Migrate token economy to session-based HD model

-- 1. Mark all existing packs as legacy and disable them
UPDATE packs SET pack_type = 'legacy' WHERE pack_type IS NULL OR pack_type = 'legacy';
UPDATE packs SET enabled = FALSE WHERE pack_type = 'legacy';

-- 2. Insert new session-based packs
INSERT INTO packs (id, name, emoji, tokens, stars_price, description, takes_limit, hd_amount, is_trial, pack_type, enabled, order_index)
VALUES
    ('trial',   'Trial',   '🎬', 0, 99,  '1 снимок + 1 HD финал',              1,  1,  TRUE,  'session', TRUE, 0),
    ('session', 'Session', '📸', 0, 229, '4 снимка + 5 HD финалов',            4,  5,  FALSE, 'session', TRUE, 1),
    ('studio',  'Studio',  '🎬', 0, 349, 'Фотосессия: 6 снимков + 10 HD',     6,  10, FALSE, 'session', TRUE, 2),
    ('creator', 'Creator', '🚀', 0, 699, 'Студия: 10 снимков + 25 HD финалов', 10, 25, FALSE, 'session', TRUE, 3)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    emoji = EXCLUDED.emoji,
    tokens = EXCLUDED.tokens,
    stars_price = EXCLUDED.stars_price,
    description = EXCLUDED.description,
    takes_limit = EXCLUDED.takes_limit,
    hd_amount = EXCLUDED.hd_amount,
    is_trial = EXCLUDED.is_trial,
    pack_type = EXCLUDED.pack_type,
    enabled = EXCLUDED.enabled,
    order_index = EXCLUDED.order_index;

-- 3. Set upgrade paths
UPDATE packs SET upgrade_target_pack_ids = '["session","studio","creator"]' WHERE id = 'trial';
UPDATE packs SET upgrade_target_pack_ids = '["studio","creator"]' WHERE id = 'session';
UPDATE packs SET upgrade_target_pack_ids = '["creator"]' WHERE id = 'studio';

-- 4. Migrate existing token balances to HD paid balance (1 token = 1 HD)
UPDATE users SET hd_paid_balance = token_balance WHERE token_balance > 0;
