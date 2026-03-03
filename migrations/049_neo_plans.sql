-- 049: Neo plans — replace avatar_pack/dating_pack/creator with neo_start/neo_pro/neo_unlimited

-- Disable old product ladder packs
UPDATE packs SET enabled = FALSE WHERE id IN ('avatar_pack', 'dating_pack', 'creator');

-- Insert new Neo plans (Stars = round(rub / 1.3))
INSERT INTO packs (id, name, emoji, tokens, stars_price, description,
    takes_limit, hd_amount, is_trial, pack_type, enabled, order_index)
VALUES
    ('neo_start',     'Neo Start',     '🚀', 0, 153,  '10 образов + 10 4K без watermark',   10,  10, FALSE, 'session', TRUE, 1),
    ('neo_pro',       'Neo Pro',       '⭐', 0, 538,  '40 образов + 40 4K без watermark',   40,  40, FALSE, 'session', TRUE, 2),
    ('neo_unlimited', 'Neo Unlimited', '👑', 0, 1531, '120 образов + 120 4K без watermark', 120, 120, FALSE, 'session', TRUE, 3)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    emoji = EXCLUDED.emoji,
    stars_price = EXCLUDED.stars_price,
    description = EXCLUDED.description,
    takes_limit = EXCLUDED.takes_limit,
    hd_amount = EXCLUDED.hd_amount,
    is_trial = EXCLUDED.is_trial,
    pack_type = EXCLUDED.pack_type,
    order_index = EXCLUDED.order_index,
    enabled = EXCLUDED.enabled;
