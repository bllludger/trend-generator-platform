-- Поднять лимит запросов с 20 до 60 в час, чтобы обычное использование + оплата не упирались в лимит
UPDATE security_settings SET default_rate_limit_per_hour = 60 WHERE id = 1 AND default_rate_limit_per_hour = 20;
