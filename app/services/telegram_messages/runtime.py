import threading
import time
from string import Formatter
from typing import Any
import hashlib

import redis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.telegram_messages.defaults import DEFAULT_TELEGRAM_TEMPLATES
from app.services.telegram_messages.service import INVALIDATION_CHANNEL, TelegramMessageTemplateService


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


class TelegramTemplateRuntime:
    """
    Runtime resolver for bot + worker.
    - in-memory cache with TTL
    - optional Redis invalidation subscription
    """

    def __init__(self, ttl_seconds: int = 60) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._loaded_at = 0.0
        self._cache: dict[str, str] = {}
        self._stop_event = threading.Event()
        self._listener_thread: threading.Thread | None = None

    def start_listener(self) -> None:
        if self._listener_thread and self._listener_thread.is_alive():
            return
        self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listener_thread.start()

    def stop_listener(self) -> None:
        self._stop_event.set()

    def _listen_loop(self) -> None:
        try:
            client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            pubsub = client.pubsub()
            pubsub.subscribe(INVALIDATION_CHANNEL)
            while not self._stop_event.is_set():
                msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg:
                    self.invalidate()
                time.sleep(0.1)
        except Exception:
            # fail-open: TTL cache still works
            return

    def invalidate(self) -> None:
        with self._lock:
            self._cache = {}
            self._loaded_at = 0.0

    def _load(self) -> dict[str, str]:
        now = time.time()
        with self._lock:
            if self._cache and (now - self._loaded_at) <= self.ttl_seconds:
                return self._cache
        db: Session = SessionLocal()
        try:
            svc = TelegramMessageTemplateService(db)
            data = svc.get_map()
        finally:
            db.close()
        with self._lock:
            self._cache = data
            self._loaded_at = now
            return self._cache

    def get(self, key: str, default: str = "") -> str:
        templates = self._load()
        if key in templates and templates[key]:
            return templates[key]
        if key in DEFAULT_TELEGRAM_TEMPLATES:
            return DEFAULT_TELEGRAM_TEMPLATES[key]["value"]
        return default

    def render(self, key: str, default: str = "", **variables: Any) -> str:
        tpl = self.get(key, default)
        try:
            # Validate placeholders first to avoid unexpected format failures
            for _, field_name, _, _ in Formatter().parse(tpl):
                if field_name and field_name not in variables:
                    variables[field_name] = "{" + field_name + "}"
            return tpl.format_map(_SafeDict(variables))
        except Exception:
            return default.format_map(_SafeDict(variables)) if default else tpl

    def resolve_literal(self, text: str | None) -> str | None:
        if text is None:
            return None
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        key = f"literal.{digest}"
        override = self.get(key, text)
        return override or text


runtime_templates = TelegramTemplateRuntime()
