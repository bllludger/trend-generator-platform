"""Настройки сервиса склейки фото: читает/пишет в БД (single-row, id=1)."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.photo_merge_settings import PhotoMergeSettings


class PhotoMergeSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_create(self) -> PhotoMergeSettings:
        row = self.db.query(PhotoMergeSettings).filter(PhotoMergeSettings.id == 1).first()
        if row:
            return row
        row = PhotoMergeSettings(id=1)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def as_dict(self) -> dict[str, Any]:
        row = self.get_or_create()
        return {
            "output_format": row.output_format,
            "jpeg_quality": row.jpeg_quality,
            "max_output_side_px": row.max_output_side_px,
            "max_input_file_mb": row.max_input_file_mb,
            "background_color": row.background_color,
            "enabled": row.enabled,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        row = self.get_or_create()
        if "output_format" in data and data["output_format"] in ("png", "jpeg"):
            row.output_format = data["output_format"]
        if "jpeg_quality" in data and data["jpeg_quality"] is not None:
            row.jpeg_quality = max(1, min(95, int(data["jpeg_quality"])))
        if "max_output_side_px" in data and data["max_output_side_px"] is not None:
            row.max_output_side_px = max(0, int(data["max_output_side_px"]))
        if "max_input_file_mb" in data and data["max_input_file_mb"] is not None:
            row.max_input_file_mb = max(1, min(100, int(data["max_input_file_mb"])))
        if "background_color" in data and data["background_color"]:
            row.background_color = str(data["background_color"])[:16]
        if "enabled" in data and data["enabled"] is not None:
            row.enabled = bool(data["enabled"])
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self.as_dict()
