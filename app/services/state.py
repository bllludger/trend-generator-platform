"""
User state management using Redis with signed serialization.
Uses itsdangerous for secure serialization (FastAPI Sessions pattern).
"""
import json
from typing import Any

import redis
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.core.config import settings


class StateStore:
    """
    Redis-backed state store with signed serialization.
    Uses itsdangerous for tamper-proof state (FastAPI Sessions pattern).
    """

    def __init__(self) -> None:
        self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.serializer = URLSafeTimedSerializer(
            settings.admin_ui_session_secret,
            salt="user-state",
        )
        self.default_ttl = settings.user_state_ttl

    def _key(self, telegram_id: str) -> str:
        return f"state:{telegram_id}"

    def get(self, telegram_id: str) -> dict[str, Any]:
        """Get user state. Returns empty dict if not found or expired."""
        raw = self.client.get(self._key(telegram_id))
        if not raw:
            return {}
        try:
            # Verify signature and decode
            data = self.serializer.loads(raw, max_age=self.default_ttl)
            return data if isinstance(data, dict) else {}
        except (BadSignature, SignatureExpired):
            # Invalid or expired signature - clear state
            self.clear(telegram_id)
            return {}

    def set(self, telegram_id: str, payload: dict[str, Any], ttl_seconds: int | None = None) -> None:
        """Set user state with signed serialization."""
        ttl = ttl_seconds or self.default_ttl
        # Sign and serialize
        signed = self.serializer.dumps(payload)
        self.client.setex(self._key(telegram_id), ttl, signed)

    def clear(self, telegram_id: str) -> None:
        """Clear user state."""
        self.client.delete(self._key(telegram_id))

    def update(self, telegram_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update user state (merge with existing)."""
        current = self.get(telegram_id)
        current.update(updates)
        self.set(telegram_id, current)
        return current

    def get_field(self, telegram_id: str, field: str, default: Any = None) -> Any:
        """Get single field from state."""
        state = self.get(telegram_id)
        return state.get(field, default)

    def set_field(self, telegram_id: str, field: str, value: Any) -> None:
        """Set single field in state."""
        self.update(telegram_id, {field: value})


class AsyncStateStore:
    """
    Async Redis-backed state store.
    For use in async FastAPI endpoints.
    """

    def __init__(self) -> None:
        # Using sync redis for now - can be replaced with aioredis if needed
        self._sync_store = StateStore()

    async def get(self, telegram_id: str) -> dict[str, Any]:
        return self._sync_store.get(telegram_id)

    async def set(self, telegram_id: str, payload: dict[str, Any], ttl_seconds: int | None = None) -> None:
        self._sync_store.set(telegram_id, payload, ttl_seconds)

    async def clear(self, telegram_id: str) -> None:
        self._sync_store.clear(telegram_id)

    async def update(self, telegram_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        return self._sync_store.update(telegram_id, updates)
