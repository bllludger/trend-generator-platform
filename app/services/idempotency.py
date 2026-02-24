import redis

from app.core.config import settings


class IdempotencyStore:
    def __init__(self) -> None:
        self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.default_ttl = settings.idempotency_ttl

    def check_and_set(self, key: str, ttl_seconds: int | None = None) -> bool:
        """Atomic operation: setnx + expire in one call."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        created = self.client.set(f"idempotency:{key}", "1", nx=True, ex=ttl)
        return created is not None
