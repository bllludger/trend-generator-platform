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
            "watermark_text": getattr(row, "watermark_text", None),
            "watermark_opacity": getattr(row, "watermark_opacity", 60),
            "watermark_tile_spacing": getattr(row, "watermark_tile_spacing", 200),
            "take_preview_max_dim": getattr(row, "take_preview_max_dim", 800),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        row = self.get_or_create()
        if "use_nano_banana_pro" in data and data["use_nano_banana_pro"] is not None:
            row.use_nano_banana_pro = bool(data["use_nano_banana_pro"])
        if "watermark_text" in data:
            row.watermark_text = data["watermark_text"] if data["watermark_text"] else None
        if "watermark_opacity" in data and data["watermark_opacity"] is not None:
            row.watermark_opacity = int(data["watermark_opacity"])
        if "watermark_tile_spacing" in data and data["watermark_tile_spacing"] is not None:
            row.watermark_tile_spacing = int(data["watermark_tile_spacing"])
        if "take_preview_max_dim" in data and data["take_preview_max_dim"] is not None:
            row.take_preview_max_dim = int(data["take_preview_max_dim"])
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self.as_dict()

    def get_watermark_params(self, env_watermark_text: str = "NanoBanan Preview") -> dict[str, Any]:
        """Параметры вотермарка для воркеров: из БД или дефолты/env."""
        row = self.get_or_create()
        return {
            "text": getattr(row, "watermark_text", None) or env_watermark_text,
            "opacity": getattr(row, "watermark_opacity", 60),
            "tile_spacing": getattr(row, "watermark_tile_spacing", 200),
        }

    def get_take_preview_max_dim(self) -> int:
        """Макс. сторона превью для 3 вариантов Take (даунскейл перед вотермарком)."""
        row = self.get_or_create()
        return getattr(row, "take_preview_max_dim", 800)
