-- 039: Premium packs for referral program threshold (>= 249 Stars)

INSERT INTO packs (id, name, emoji, tokens, stars_price, description, enabled, order_index)
VALUES
    ('premium', 'Premium', '👑', 80, 249, '80 фото без watermark', TRUE, 4),
    ('ultra', 'Ultra', '🚀', 170, 499, '170 фото без watermark', TRUE, 5)
ON CONFLICT (id) DO NOTHING;
