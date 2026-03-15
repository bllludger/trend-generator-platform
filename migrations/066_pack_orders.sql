-- Pack orders: заказы на покупку пакета (Neo Start / Neo Pro / Neo Unlimited) по ссылке ЮKassa.
CREATE TABLE IF NOT EXISTS pack_orders (
    id VARCHAR PRIMARY KEY,
    telegram_user_id VARCHAR NOT NULL,
    pack_id VARCHAR NOT NULL,
    amount_kopecks INTEGER NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'created',
    yookassa_payment_id VARCHAR,
    confirmation_url VARCHAR,
    idempotence_key VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS idx_pack_orders_telegram_user_id ON pack_orders (telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_pack_orders_pack_id ON pack_orders (pack_id);
CREATE INDEX IF NOT EXISTS idx_pack_orders_yookassa_payment_id
    ON pack_orders (yookassa_payment_id) WHERE yookassa_payment_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pack_orders_status ON pack_orders (status);

COMMENT ON TABLE pack_orders IS 'Заказы пакетов по ссылке ЮKassa. Статусы: created, payment_pending, paid, completed, canceled, failed.';
