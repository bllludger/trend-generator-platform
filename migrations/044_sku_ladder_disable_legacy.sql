-- 044: SKU ladder — только trial, avatar_pack, dating_pack, creator в продаже

-- Отключить старые session/studio от продажи
UPDATE packs SET enabled = FALSE WHERE id IN ('session', 'studio');

-- Убедиться, что пакеты лестницы существуют с корректными order_index и ценами
INSERT INTO packs (id, name, emoji, tokens, stars_price, description,
    takes_limit, hd_amount, is_trial, pack_type, enabled, order_index)
VALUES
    ('trial',       'Trial',       '🎬', 0, 99,  '1 снимок + 1 HD',                    1,  1,  TRUE,  'session', TRUE, 0),
    ('avatar_pack', 'Avatar Pack',  '🎭', 0, 349, '4 стиля аватара — 12 превью, до 6 HD', 4,  6,  FALSE, 'session', TRUE, 1),
    ('dating_pack',  'Dating Pack', '💕', 0, 499, '6 образов для дейтинга — до 10 HD',  6, 10,  FALSE, 'session', TRUE, 2),
    ('creator',     'Creator',     '🚀', 0, 699, 'Студия: 10 снимков + 25 HD',         10, 25,  FALSE, 'session', TRUE, 3)
ON CONFLICT (id) DO UPDATE SET
    stars_price = EXCLUDED.stars_price,
    order_index = EXCLUDED.order_index,
    enabled = EXCLUDED.enabled;
