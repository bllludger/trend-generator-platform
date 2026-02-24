from datetime import datetime, timezone
import ast
import hashlib
from pathlib import Path
from typing import Any

import redis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.telegram_message_template import TelegramMessageTemplate
from app.services.telegram_messages.defaults import DEFAULT_TELEGRAM_TEMPLATES

INVALIDATION_CHANNEL = "bot:templates:invalidate"


class TelegramMessageTemplateService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def seed_defaults(self) -> int:
        created = 0
        defaults = dict(DEFAULT_TELEGRAM_TEMPLATES)
        defaults.update(self._discover_literal_templates())
        for key, data in defaults.items():
            row = self.db.query(TelegramMessageTemplate).filter(TelegramMessageTemplate.key == key).first()
            if row:
                continue
            row = TelegramMessageTemplate(
                key=key,
                value=data["value"],
                description=data.get("description", ""),
                category=data.get("category", "general"),
                updated_by="system",
            )
            self.db.add(row)
            created += 1
        if created:
            self.db.commit()
        return created

    @staticmethod
    def literal_key(text: str) -> str:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        return f"literal.{digest}"

    def _discover_literal_templates(self) -> dict[str, dict[str, str]]:
        """Auto-discover message literals so ALL hardcoded texts are editable."""
        files = [
            "/root/ai_slop_2/app/bot/main.py",
            "/root/ai_slop_2/app/workers/tasks/generation_v2.py",
        ]
        out: dict[str, dict[str, str]] = {}
        for fpath in files:
            p = Path(fpath)
            if not p.exists():
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    text = node.value.strip()
                    if not text:
                        continue
                    # Heuristic: user-facing strings
                    if len(text) < 4:
                        continue
                    if (
                        any("\u0400" <= ch <= "\u04FF" for ch in text)
                        or text.startswith(("🔥", "🔄", "👤", "🛒", "⚠️", "❌", "⏳", "🎨", "✨", "📸", "📎"))
                        or "\n" in text
                    ):
                        key = self.literal_key(text)
                        out[key] = {
                            "value": text,
                            "category": "literal",
                            "description": f"Auto-discovered literal from {p.name}",
                        }
        return out

    def list_templates(self) -> list[dict[str, Any]]:
        self.seed_defaults()
        rows = self.db.query(TelegramMessageTemplate).order_by(TelegramMessageTemplate.category, TelegramMessageTemplate.key).all()
        return [
            {
                "key": r.key,
                "value": r.value,
                "description": r.description or "",
                "category": r.category or "general",
                "updated_by": r.updated_by,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]

    def get_map(self) -> dict[str, str]:
        self.seed_defaults()
        rows = self.db.query(TelegramMessageTemplate).all()
        return {r.key: (r.value or "") for r in rows}

    def update_one(self, key: str, value: str, updated_by: str | None = None) -> dict[str, Any]:
        self.seed_defaults()
        row = self.db.query(TelegramMessageTemplate).filter(TelegramMessageTemplate.key == key).first()
        if not row:
            defaults = DEFAULT_TELEGRAM_TEMPLATES.get(key, {})
            row = TelegramMessageTemplate(
                key=key,
                value=value,
                description=defaults.get("description", ""),
                category=defaults.get("category", "general"),
                updated_by=updated_by,
            )
            self.db.add(row)
        else:
            row.value = value
            row.updated_by = updated_by
            row.updated_at = datetime.now(timezone.utc)
            self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        self.publish_invalidation()
        return {
            "key": row.key,
            "value": row.value,
            "description": row.description or "",
            "category": row.category or "general",
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def bulk_upsert(self, items: list[dict[str, str]], updated_by: str | None = None) -> dict[str, Any]:
        self.seed_defaults()
        updated = 0
        for item in items:
            key = (item.get("key") or "").strip()
            if not key:
                continue
            value = item.get("value") or ""
            row = self.db.query(TelegramMessageTemplate).filter(TelegramMessageTemplate.key == key).first()
            if not row:
                defaults = DEFAULT_TELEGRAM_TEMPLATES.get(key, {})
                row = TelegramMessageTemplate(
                    key=key,
                    value=value,
                    description=defaults.get("description", ""),
                    category=defaults.get("category", "general"),
                    updated_by=updated_by,
                )
            else:
                row.value = value
                row.updated_by = updated_by
                row.updated_at = datetime.now(timezone.utc)
            self.db.add(row)
            updated += 1
        self.db.commit()
        self.publish_invalidation()
        return {"updated": updated}

    def reset_defaults(self, updated_by: str | None = None) -> dict[str, Any]:
        self.seed_defaults()
        reset = 0
        for key, data in DEFAULT_TELEGRAM_TEMPLATES.items():
            row = self.db.query(TelegramMessageTemplate).filter(TelegramMessageTemplate.key == key).first()
            if not row:
                continue
            row.value = data["value"]
            row.description = data.get("description", "")
            row.category = data.get("category", "general")
            row.updated_by = updated_by
            row.updated_at = datetime.now(timezone.utc)
            self.db.add(row)
            reset += 1
        self.db.commit()
        self.publish_invalidation()
        return {"reset": reset}

    @staticmethod
    def publish_invalidation() -> None:
        try:
            client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            client.publish(INVALIDATION_CHANNEL, datetime.now(timezone.utc).isoformat())
        except Exception:
            # fail-open: runtime also has TTL fallback
            pass
