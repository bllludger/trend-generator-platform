"""Сервис настроек «Сделать такую же»: читает/пишет только в БД. Дефолты — в миграции 011, не дублируются здесь."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.copy_style_settings import CopyStyleSettings

# Только для пустых полей (если миграция не заполнила или кто-то очистил). Полные дефолты — в 011_copy_style_settings.sql
_FALLBACK_SYSTEM = "Опиши изображение для 1:1 копирования стиля: акторы, композиция, освещение. Ответ — только промпт на английском."
_FALLBACK_USER = "Проанализируй это изображение и составь промпт для 1:1 копирования стиля и акторов."
_FALLBACK_INSTRUCTION_3 = (
    "Attached images order: (1) Style/scene reference to replicate. "
    "(2) Use this person's face for the woman/female character. "
    "(3) Use this person's face for the man/male character. "
    "Generate the scene in the described style with these two faces."
)
_FALLBACK_INSTRUCTION_2 = (
    "Attached images order: (1) Use this face for the woman/female character. "
    "(2) Use this face for the man/male character. Generate the scene with these faces."
)
# Дефолт системного префикса для генерации (флоу «Сделать такую же») — если в БД пусто
_FALLBACK_GENERATION_SYSTEM_PREFIX = (
    "You are an image generation system (Nano Banana / Gemini image editing mode). "
    "Follow instructions exactly. No explanations, no captions, no intermediate steps. "
    "TREND (text) defines style and scene. Attached images define who must appear. "
    "Preserve identity, count, and placement of people from the input images. "
    "Return one final image only."
)


class CopyStyleSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self) -> CopyStyleSettings | None:
        return self.db.query(CopyStyleSettings).filter(CopyStyleSettings.id == 1).first()

    def get_or_create(self) -> CopyStyleSettings:
        row = self.get()
        if row:
            return row
        row = CopyStyleSettings(
            id=1,
            model=getattr(settings, "openai_vision_model", "gpt-4o"),
            system_prompt="",
            user_prompt="",
            max_tokens=1536,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_effective(self) -> dict[str, Any]:
        """Настройки для vision_analyzer и воркера. Единая точка — только БД; пустые поля — fallback."""
        row = self.get_or_create()
        sp = (row.system_prompt or "").strip()
        up = (row.user_prompt or "").strip()
        suffix = (getattr(row, "prompt_suffix", None) or "").strip()
        instr_3 = (getattr(row, "prompt_instruction_3_images", None) or "").strip()
        instr_2 = (getattr(row, "prompt_instruction_2_images", None) or "").strip()
        gen_prefix = (getattr(row, "generation_system_prompt_prefix", None) or "").strip()
        gen_neg = (getattr(row, "generation_negative_prompt", None) or "").strip()
        gen_safety = (getattr(row, "generation_safety_constraints", None) or "").strip() or "no text generation, no chat."
        gen_constraints = (getattr(row, "generation_image_constraints_template", None) or "").strip() or "size={size}, format={format}"
        gen_size = (getattr(row, "generation_default_size", None) or "").strip() or "1024x1024"
        gen_fmt = (getattr(row, "generation_default_format", None) or "").strip() or "png"
        gen_model = (getattr(row, "generation_default_model", None) or "").strip() or getattr(settings, "gemini_image_model", "gemini-2.5-flash-image")
        return {
            "model": (row.model or "").strip() or getattr(settings, "openai_vision_model", "gpt-4o"),
            "system_prompt": sp or _FALLBACK_SYSTEM,
            "user_prompt": up or _FALLBACK_USER,
            "max_tokens": max(256, min(4096, row.max_tokens or 1536)),
            "prompt_suffix": suffix,
            "prompt_instruction_3_images": instr_3 or _FALLBACK_INSTRUCTION_3,
            "prompt_instruction_2_images": instr_2 or _FALLBACK_INSTRUCTION_2,
            "generation_system_prompt_prefix": gen_prefix or _FALLBACK_GENERATION_SYSTEM_PREFIX,
            "generation_negative_prompt": gen_neg,
            "generation_safety_constraints": gen_safety,
            "generation_image_constraints_template": gen_constraints,
            "generation_default_size": gen_size,
            "generation_default_format": gen_fmt,
            "generation_default_model": gen_model,
        }

    def as_dict(self) -> dict[str, Any]:
        """Для админ API: то, что в БД (пустые — fallback в форме). Единая точка — админка «Сделать такую же»."""
        row = self.get_or_create()
        sp = (row.system_prompt or "").strip()
        up = (row.user_prompt or "").strip()
        suffix = (getattr(row, "prompt_suffix", None) or "").strip()
        instr_3 = (getattr(row, "prompt_instruction_3_images", None) or "").strip()
        instr_2 = (getattr(row, "prompt_instruction_2_images", None) or "").strip()
        gen_prefix = (getattr(row, "generation_system_prompt_prefix", None) or "").strip()
        gen_neg = (getattr(row, "generation_negative_prompt", None) or "").strip()
        gen_safety = (getattr(row, "generation_safety_constraints", None) or "").strip()
        gen_constraints = (getattr(row, "generation_image_constraints_template", None) or "").strip()
        gen_size = (getattr(row, "generation_default_size", None) or "").strip()
        gen_fmt = (getattr(row, "generation_default_format", None) or "").strip()
        gen_model = (getattr(row, "generation_default_model", None) or "").strip()
        return {
            "model": (row.model or "").strip() or getattr(settings, "openai_vision_model", "gpt-4o"),
            "system_prompt": sp or _FALLBACK_SYSTEM,
            "user_prompt": up or _FALLBACK_USER,
            "max_tokens": max(256, min(4096, row.max_tokens or 1536)),
            "prompt_suffix": suffix,
            "prompt_instruction_3_images": instr_3 or _FALLBACK_INSTRUCTION_3,
            "prompt_instruction_2_images": instr_2 or _FALLBACK_INSTRUCTION_2,
            "generation_system_prompt_prefix": gen_prefix or _FALLBACK_GENERATION_SYSTEM_PREFIX,
            "generation_negative_prompt": gen_neg,
            "generation_safety_constraints": gen_safety or "no text generation, no chat.",
            "generation_image_constraints_template": gen_constraints or "size={size}, format={format}",
            "generation_default_size": gen_size or "1024x1024",
            "generation_default_format": gen_fmt or "png",
            "generation_default_model": gen_model or getattr(settings, "gemini_image_model", "gemini-2.5-flash-image"),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        row = self.get_or_create()
        if "model" in data:
            row.model = (str(data["model"]) or "").strip() or "gpt-4o"
        if "system_prompt" in data:
            raw = data["system_prompt"]
            row.system_prompt = "" if raw is None else str(raw)
        if "user_prompt" in data:
            raw = data["user_prompt"]
            row.user_prompt = "" if raw is None else str(raw)
        if "max_tokens" in data and data["max_tokens"] is not None:
            try:
                n = int(data["max_tokens"])
                row.max_tokens = max(256, min(4096, n))
            except (TypeError, ValueError):
                pass
        if "prompt_suffix" in data:
            raw = data["prompt_suffix"]
            row.prompt_suffix = "" if raw is None else str(raw)
        if "prompt_instruction_3_images" in data:
            raw = data["prompt_instruction_3_images"]
            row.prompt_instruction_3_images = "" if raw is None else str(raw)
        if "prompt_instruction_2_images" in data:
            raw = data["prompt_instruction_2_images"]
            row.prompt_instruction_2_images = "" if raw is None else str(raw)
        if "generation_system_prompt_prefix" in data:
            row.generation_system_prompt_prefix = "" if data["generation_system_prompt_prefix"] is None else str(data["generation_system_prompt_prefix"])
        if "generation_negative_prompt" in data:
            row.generation_negative_prompt = "" if data["generation_negative_prompt"] is None else str(data["generation_negative_prompt"])
        if "generation_safety_constraints" in data:
            raw = data["generation_safety_constraints"]
            row.generation_safety_constraints = "" if raw is None else str(raw)
        if "generation_image_constraints_template" in data:
            raw = data["generation_image_constraints_template"]
            row.generation_image_constraints_template = "" if raw is None else str(raw)
        if "generation_default_size" in data and data["generation_default_size"] is not None:
            row.generation_default_size = (str(data["generation_default_size"]) or "1024x1024").strip() or "1024x1024"
        if "generation_default_format" in data and data["generation_default_format"] is not None:
            row.generation_default_format = (str(data["generation_default_format"]) or "png").strip() or "png"
        if "generation_default_model" in data:
            row.generation_default_model = "" if data["generation_default_model"] is None else str(data["generation_default_model"]).strip()
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self.as_dict()
