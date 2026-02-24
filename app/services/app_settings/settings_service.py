"""Глобальные настройки приложения из админки: тумблеры и переопределения (например Nano Banana Pro)."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings


class AppSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self) -> AppSettings | None:
        return self.db.query(AppSettings).filter(AppSettings.id == 1).first()

    def get_or_create(self) -> AppSettings:
        row = self.get()
        if row:
            return row
        row = AppSettings(id=1, use_nano_banana_pro=False)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_effective_provider(self, settings) -> str:
        """
        Эффективный провайдер генерации изображений.
        Если в админке включён «Nano Banana Pro» — возвращаем "gemini", иначе — из .env (settings.image_provider).
        """
        row = self.get_or_create()
        if row.use_nano_banana_pro:
            return "gemini"
        return getattr(settings, "image_provider", "openai")

    def as_dict(self) -> dict[str, Any]:
        row = self.get_or_create()
        return {
            "use_nano_banana_pro": row.use_nano_banana_pro,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        row = self.get_or_create()
        if "use_nano_banana_pro" in data and data["use_nano_banana_pro"] is not None:
            row.use_nano_banana_pro = bool(data["use_nano_banana_pro"])
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self.as_dict()
