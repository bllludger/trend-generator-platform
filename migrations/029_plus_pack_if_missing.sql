-- 029: Добавить пакет Plus для существующих инсталляций (между Standard и Pro)
INSERT INTO packs (id, name, emoji, tokens, stars_price, description, enabled, order_index)
SELECT 'plus', 'Plus', '✨', 30, 115, '30 фото без watermark', TRUE, 2
WHERE NOT EXISTS (SELECT 1 FROM packs WHERE id = 'plus');

-- Сдвинуть order_index у pro на 3, если plus только что добавлен и pro имел order_index 2
UPDATE packs SET order_index = 3 WHERE id = 'pro' AND order_index = 2
  AND EXISTS (SELECT 1 FROM packs WHERE id = 'plus');
