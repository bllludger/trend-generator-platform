import json
import logging
import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# TTL for admin grant-pack cached responses (24h)
ADMIN_GRANT_IDEMPOTENCY_TTL = 86400


class IdempotencyStore:
    def __init__(self) -> None:
        self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.default_ttl = settings.idempotency_ttl

    def check_and_set(self, key: str, ttl_seconds: int | None = None) -> bool:
        """Atomic operation: setnx + expire in one call."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        created = self.client.set(f"idempotency:{key}", "1", nx=True, ex=ttl)
        return created is not None

    def get_grant_response(self, idempotency_key: str) -> dict | None:
        """Return cached grant-pack response if key was already processed. None if miss."""
        try:
            raw = self.client.get(f"admin:grant_idempotency:{idempotency_key}")
            if not raw:
                return None
            return json.loads(raw)
        except (json.JSONDecodeError, redis.RedisError) as e:
            logger.warning("idempotency_get_grant_failed", extra={"key": idempotency_key[:32], "error": str(e)})
            return None

    def set_grant_response(self, idempotency_key: str, response: dict, ttl_seconds: int = ADMIN_GRANT_IDEMPOTENCY_TTL) -> None:
        """Cache grant-pack response for idempotent replay."""
        try:
            self.client.setex(
                f"admin:grant_idempotency:{idempotency_key}",
                ttl_seconds,
                json.dumps(response),
            )
        except redis.RedisError as e:
            logger.warning("idempotency_set_grant_failed", extra={"key": idempotency_key[:32], "error": str(e)})


_grant_store: "IdempotencyStore | None" = None


def _get_grant_store() -> IdempotencyStore:
    global _grant_store
    if _grant_store is None:
        _grant_store = IdempotencyStore()
    return _grant_store


def get_admin_grant_response(idempotency_key: str) -> dict | None:
    """Return cached grant-pack response for idempotent replay."""
    return _get_grant_store().get_grant_response(idempotency_key)


def set_admin_grant_response(idempotency_key: str, response: dict) -> None:
    """Cache grant-pack response after successful grant."""
    _get_grant_store().set_grant_response(idempotency_key, response)
