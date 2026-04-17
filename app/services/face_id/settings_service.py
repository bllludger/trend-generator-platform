from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.face_id_settings import FaceIdSettings


class FaceIdSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self) -> FaceIdSettings | None:
        return self.db.query(FaceIdSettings).filter(FaceIdSettings.id == 1).first()

    def get_or_create(self) -> FaceIdSettings:
        row = self.get()
        if row:
            return row
        row = FaceIdSettings(id=1)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def as_dict(self) -> dict[str, Any]:
        row = self.get_or_create()
        return {
            "enabled": bool(row.enabled),
            "min_detection_confidence": float(row.min_detection_confidence),
            "model_selection": int(row.model_selection),
            "crop_pad_left": float(row.crop_pad_left),
            "crop_pad_right": float(row.crop_pad_right),
            "crop_pad_top": float(row.crop_pad_top),
            "crop_pad_bottom": float(row.crop_pad_bottom),
            "max_faces_allowed": int(row.max_faces_allowed),
            "no_face_policy": str(row.no_face_policy or "fallback_original"),
            "multi_face_policy": str(row.multi_face_policy or "fail_generation"),
            "callback_timeout_seconds": float(row.callback_timeout_seconds),
            "callback_max_retries": int(row.callback_max_retries),
            "callback_backoff_seconds": float(row.callback_backoff_seconds),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        row = self.get_or_create()
        if "enabled" in data:
            row.enabled = bool(data.get("enabled"))
        if "min_detection_confidence" in data:
            try:
                row.min_detection_confidence = max(0.0, min(1.0, float(data.get("min_detection_confidence"))))
            except (TypeError, ValueError):
                pass
        if "model_selection" in data:
            try:
                parsed = int(data.get("model_selection"))
                row.model_selection = 1 if parsed not in (0, 1) else parsed
            except (TypeError, ValueError):
                pass
        for key in ("crop_pad_left", "crop_pad_right", "crop_pad_top", "crop_pad_bottom"):
            if key in data:
                try:
                    setattr(row, key, max(0.0, float(data.get(key))))
                except (TypeError, ValueError):
                    pass
        if "max_faces_allowed" in data:
            try:
                row.max_faces_allowed = max(1, int(data.get("max_faces_allowed")))
            except (TypeError, ValueError):
                pass
        if "no_face_policy" in data:
            val = str(data.get("no_face_policy") or "").strip().lower()
            if val in {"fallback_original"}:
                row.no_face_policy = val
        if "multi_face_policy" in data:
            val = str(data.get("multi_face_policy") or "").strip().lower()
            if val in {"fail_generation", "fallback_original"}:
                row.multi_face_policy = val
        if "callback_timeout_seconds" in data:
            try:
                row.callback_timeout_seconds = max(0.1, float(data.get("callback_timeout_seconds")))
            except (TypeError, ValueError):
                pass
        if "callback_max_retries" in data:
            try:
                row.callback_max_retries = max(0, int(data.get("callback_max_retries")))
            except (TypeError, ValueError):
                pass
        if "callback_backoff_seconds" in data:
            try:
                row.callback_backoff_seconds = max(0.0, float(data.get("callback_backoff_seconds")))
            except (TypeError, ValueError):
                pass
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self.as_dict()

