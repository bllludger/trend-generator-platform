"""Глобальные настройки приложения из админки: тумблеры и переопределения (например Nano Banana Pro)."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings as app_config
from app.models.app_settings import AppSettings

# Допустимые диапазоны для политики превью (валидация API + защита в PreviewService)
PREVIEW_MAX_DIM_MIN = 100
PREVIEW_MAX_DIM_MAX = 4096
PREVIEW_FORMAT_ALLOWED = frozenset({"webp", "jpeg"})


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
        try:
            self.db.commit()
            self.db.refresh(row)
            return row
        except IntegrityError:
            self.db.rollback()
            row = self.get()
            if row is None:
                raise
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
            "preview_format": getattr(row, "preview_format", "webp"),
            "preview_quality": getattr(row, "preview_quality", 85),
            "job_preview_max_dim": getattr(row, "job_preview_max_dim", 800),
            "watermark_use_contrast": getattr(row, "watermark_use_contrast", True),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        row = self.get_or_create()
        if "use_nano_banana_pro" in data and data["use_nano_banana_pro"] is not None:
            row.use_nano_banana_pro = bool(data["use_nano_banana_pro"])
        if "watermark_text" in data:
            row.watermark_text = data["watermark_text"] if data["watermark_text"] else None
        if "watermark_opacity" in data and data["watermark_opacity"] is not None:
            row.watermark_opacity = max(0, min(255, int(data["watermark_opacity"])))
        if "watermark_tile_spacing" in data and data["watermark_tile_spacing"] is not None:
            row.watermark_tile_spacing = max(0, min(2000, int(data["watermark_tile_spacing"])))
        if "take_preview_max_dim" in data and data["take_preview_max_dim"] is not None:
            val = int(data["take_preview_max_dim"])
            if not (PREVIEW_MAX_DIM_MIN <= val <= PREVIEW_MAX_DIM_MAX):
                raise ValueError(
                    f"take_preview_max_dim must be between {PREVIEW_MAX_DIM_MIN} and {PREVIEW_MAX_DIM_MAX}, got {val}"
                )
            row.take_preview_max_dim = val
        if "preview_format" in data and data["preview_format"] is not None:
            fmt = str(data["preview_format"]).strip().lower()
            if fmt not in PREVIEW_FORMAT_ALLOWED:
                raise ValueError(f"preview_format must be one of {sorted(PREVIEW_FORMAT_ALLOWED)}, got {fmt!r}")
            row.preview_format = fmt
        if "preview_quality" in data and data["preview_quality"] is not None:
            row.preview_quality = max(1, min(100, int(data["preview_quality"])))
        if "job_preview_max_dim" in data and data["job_preview_max_dim"] is not None:
            val = int(data["job_preview_max_dim"])
            if not (PREVIEW_MAX_DIM_MIN <= val <= PREVIEW_MAX_DIM_MAX):
                raise ValueError(
                    f"job_preview_max_dim must be between {PREVIEW_MAX_DIM_MIN} and {PREVIEW_MAX_DIM_MAX}, got {val}"
                )
            row.job_preview_max_dim = val
        if "watermark_use_contrast" in data and data["watermark_use_contrast"] is not None:
            row.watermark_use_contrast = bool(data["watermark_use_contrast"])
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self.as_dict()

    def get_watermark_params(self) -> dict[str, Any]:
        """Параметры вотермарка: из БД или settings.watermark_text (.env). Единая логика с админкой (watermark_text_effective)."""
        row = self.get_or_create()
        db_text = getattr(row, "watermark_text", None)
        if db_text is not None and str(db_text).strip():
            text = str(db_text).strip()
        else:
            text = getattr(app_config, "watermark_text", "@ai_nanobananastudio_bot")
        return {
            "text": text,
            "opacity": getattr(row, "watermark_opacity", 60),
            "tile_spacing": getattr(row, "watermark_tile_spacing", 200),
            "use_contrast": getattr(row, "watermark_use_contrast", True),
        }

    def get_take_preview_max_dim(self) -> int:
        """Макс. сторона превью для 3 вариантов Take. Защитно ограничен [MIN, MAX]."""
        row = self.get_or_create()
        val = getattr(row, "take_preview_max_dim", 800)
        return max(PREVIEW_MAX_DIM_MIN, min(PREVIEW_MAX_DIM_MAX, int(val)))

    def get_job_preview_max_dim(self) -> int:
        """Макс. сторона превью для Job (paywall). Защитно ограничен [MIN, MAX]."""
        row = self.get_or_create()
        val = getattr(row, "job_preview_max_dim", 800)
        return max(PREVIEW_MAX_DIM_MIN, min(PREVIEW_MAX_DIM_MAX, int(val)))

    def get_preview_format(self) -> str:
        """Формат превью: webp или jpeg."""
        row = self.get_or_create()
        fmt = getattr(row, "preview_format", "webp") or "webp"
        return fmt if fmt in ("webp", "jpeg") else "webp"

    def get_preview_quality(self) -> int:
        """Качество сжатия превью 1-100."""
        row = self.get_or_create()
        return max(1, min(100, getattr(row, "preview_quality", 85)))

    def get_watermark_use_contrast(self) -> bool:
        """Двухслойный контрастный вотермарк (виден на светлом и тёмном фоне)."""
        row = self.get_or_create()
        return getattr(row, "watermark_use_contrast", True)
