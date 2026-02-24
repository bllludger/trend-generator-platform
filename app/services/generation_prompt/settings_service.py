"""Сервис настроек промпта генерации: только [INPUT], [TASK], [IDENTITY TRANSFER], [SAFETY]."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.generation_prompt_settings import GenerationPromptSettings

RECOMMENDED_DEFAULTS = {
    "prompt_input": "IMAGE_1 = trend reference (scene/style). IMAGE_2 = user photo (preserve this identity in output).",
    "prompt_task": "Generate a single image: apply the scene and style from the trend to the subject from the user photo.",
    "prompt_identity_transfer": "Preserve the face and identity from the user photo. Do not alter facial features, skin tone, or distinguishing characteristics.",
    "safety_constraints": "no text generation, no chat. No watermarks, no logos.",
}


class GenerationPromptSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self) -> GenerationPromptSettings | None:
        return self.db.query(GenerationPromptSettings).filter(GenerationPromptSettings.id == 1).first()

    def get_or_create(self) -> GenerationPromptSettings:
        row = self.get()
        if row:
            return row
        row = GenerationPromptSettings(id=1)
        row.prompt_input = RECOMMENDED_DEFAULTS["prompt_input"]
        row.prompt_task = RECOMMENDED_DEFAULTS["prompt_task"]
        row.prompt_identity_transfer = RECOMMENDED_DEFAULTS["prompt_identity_transfer"]
        row.safety_constraints = RECOMMENDED_DEFAULTS["safety_constraints"]
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_effective(self) -> dict[str, Any]:
        """Для воркера: только включённые блоки и дефолты."""
        try:
            row = self.get_or_create()
        except Exception:
            return self._default_effective()
        return {
            "prompt_input": (row.prompt_input or "").strip() if row.prompt_input_enabled else "",
            "prompt_task": (row.prompt_task or "").strip() if row.prompt_task_enabled else "",
            "prompt_identity_transfer": (row.prompt_identity_transfer or "").strip() if row.prompt_identity_transfer_enabled else "",
            "safety_constraints": (row.safety_constraints or "no text generation, no chat.").strip() if row.safety_constraints_enabled else "",
            "default_model": (row.default_model or "").strip() or getattr(settings, "gemini_image_model", "gemini-2.5-flash-image"),
            "default_size": (row.default_size or "").strip() or "1024x1024",
            "default_format": (row.default_format or "").strip() or "png",
            "default_temperature": self._clamp_temperature(getattr(row, "default_temperature", 0.7)),
            "default_image_size_tier": (getattr(row, "default_image_size_tier", None) or "1K").strip(),
            "default_aspect_ratio": (getattr(row, "default_aspect_ratio", None) or "1:1").strip(),
        }

    def _clamp_temperature(self, value: float) -> float:
        try:
            t = float(value)
            if t != t:
                return 0.7
            return max(0.0, min(2.0, t))
        except (TypeError, ValueError):
            return 0.7

    def _default_effective(self) -> dict[str, Any]:
        return {
            **RECOMMENDED_DEFAULTS,
            "default_model": getattr(settings, "gemini_image_model", "gemini-2.5-flash-image"),
            "default_size": "1024x1024",
            "default_format": "png",
            "default_temperature": 0.7,
            "default_image_size_tier": "1K",
            "default_aspect_ratio": "1:1",
        }

    def as_dict(self) -> dict[str, Any]:
        try:
            row = self.get_or_create()
        except Exception:
            return self._default_as_dict()
        return self._row_to_dict(row)

    def _row_to_dict(self, row: GenerationPromptSettings) -> dict[str, Any]:
        return {
            "prompt_input": (row.prompt_input or "").strip(),
            "prompt_input_enabled": bool(row.prompt_input_enabled),
            "prompt_task": (row.prompt_task or "").strip(),
            "prompt_task_enabled": bool(row.prompt_task_enabled),
            "prompt_identity_transfer": (row.prompt_identity_transfer or "").strip(),
            "prompt_identity_transfer_enabled": bool(row.prompt_identity_transfer_enabled),
            "safety_constraints": (row.safety_constraints or "no text generation, no chat.").strip(),
            "safety_constraints_enabled": bool(row.safety_constraints_enabled),
            "default_model": (row.default_model or "gemini-2.5-flash-image").strip(),
            "default_size": (row.default_size or "1024x1024").strip(),
            "default_format": (row.default_format or "png").strip(),
            "default_temperature": float(row.default_temperature or 0.7),
            "default_image_size_tier": (getattr(row, "default_image_size_tier", None) or "1K").strip(),
            "default_aspect_ratio": (getattr(row, "default_aspect_ratio", None) or "1:1").strip(),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _default_as_dict(self) -> dict[str, Any]:
        return {
            "prompt_input": RECOMMENDED_DEFAULTS["prompt_input"],
            "prompt_input_enabled": True,
            "prompt_task": RECOMMENDED_DEFAULTS["prompt_task"],
            "prompt_task_enabled": True,
            "prompt_identity_transfer": RECOMMENDED_DEFAULTS["prompt_identity_transfer"],
            "prompt_identity_transfer_enabled": True,
            "safety_constraints": RECOMMENDED_DEFAULTS["safety_constraints"],
            "safety_constraints_enabled": True,
            "default_model": "gemini-2.5-flash-image",
            "default_size": "1024x1024",
            "default_format": "png",
            "default_temperature": 0.7,
            "default_image_size_tier": "1K",
            "default_aspect_ratio": "1:1",
            "updated_at": None,
        }

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        row = self.get_or_create()
        for key in ("prompt_input", "prompt_task", "prompt_identity_transfer", "safety_constraints"):
            if key in data:
                setattr(row, key, "" if data[key] is None else str(data[key]))
        for key in ("prompt_input_enabled", "prompt_task_enabled", "prompt_identity_transfer_enabled", "safety_constraints_enabled"):
            if key in data:
                setattr(row, key, bool(data[key]))
        for key in ("default_model", "default_size", "default_format"):
            if key in data:
                setattr(row, key, (str(data[key]) or "").strip() or {"default_model": "gemini-2.5-flash-image", "default_size": "1024x1024", "default_format": "png"}[key])
        if "default_temperature" in data and data["default_temperature"] is not None:
            try:
                t = float(data["default_temperature"])
                if t == t:
                    row.default_temperature = max(0.0, min(2.0, t))
            except (TypeError, ValueError):
                pass
        if "default_image_size_tier" in data and data["default_image_size_tier"] is not None:
            tier = str(data["default_image_size_tier"]).strip().upper()
            if tier in ("256", "512", "1K", "2K", "4K"):
                row.default_image_size_tier = tier
        if "default_aspect_ratio" in data and data["default_aspect_ratio"] is not None:
            ar = str(data["default_aspect_ratio"]).strip()
            if ":" in ar:
                row.default_aspect_ratio = ar
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self._row_to_dict(row)

    def reset_to_recommended(self) -> dict[str, Any]:
        row = self.get_or_create()
        row.prompt_input = RECOMMENDED_DEFAULTS["prompt_input"]
        row.prompt_task = RECOMMENDED_DEFAULTS["prompt_task"]
        row.prompt_identity_transfer = RECOMMENDED_DEFAULTS["prompt_identity_transfer"]
        row.safety_constraints = RECOMMENDED_DEFAULTS["safety_constraints"]
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self._row_to_dict(row)
