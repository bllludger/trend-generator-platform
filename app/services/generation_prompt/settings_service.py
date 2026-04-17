"""Сервис настроек промпта генерации: мастер prompt_input, legacy task/identity/safety + Gemini defaults."""
from datetime import datetime, timezone
import json
import re
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.generation_prompt_settings import GenerationPromptSettings
from app.utils.image_formats import aspect_ratio_to_size

# Убираем старые шаблоны (migrations/034 и вводные фразы), чтобы в Gemini не утекали «заготовки».
_LEGACY_MASTER_PROMPT_RES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"IMAGE_1\s*=\s*trend\s+reference\s*\(scene/style\)\.\s*IMAGE_2\s*=\s*user\s+photo\s*"
        r"\(\s*preserve\s+this\s+identity\s+in\s+output\s*\)\s*\.?",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"Generate\s+a\s+single\s+image:\s*apply\s+the\s+scene\s+and\s+style\s+from\s+the\s+trend\s+to\s+the\s+subject\s+"
        r"from\s+the\s+user\s+photo\s*\.?",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"Привет\s*,?\s*помоги\s+сгенерировать\s*:?", re.IGNORECASE),
)


def strip_legacy_master_prompt_boilerplate(text: str | None) -> str:
    t = "" if text is None else str(text)
    for pat in _LEGACY_MASTER_PROMPT_RES:
        t = pat.sub("", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _effective_master_prompt_from_row(row: GenerationPromptSettings) -> str:
    """Склеивает включённые input+task (на случай старых БД), вырезает легаси-шаблоны."""
    parts: list[str] = []
    if row.prompt_input_enabled:
        s = (row.prompt_input or "").strip()
        if s:
            parts.append(s)
    if row.prompt_task_enabled:
        s = (row.prompt_task or "").strip()
        if s:
            parts.append(s)
    return strip_legacy_master_prompt_boilerplate("\n\n".join(parts))


RECOMMENDED_DEFAULTS = {
    "prompt_input": "",
    "prompt_task": "",
    "prompt_identity_transfer": "Preserve the face and identity from the user photo. Do not alter facial features, skin tone, or distinguishing characteristics.",
    "safety_constraints": "",
}


PROFILE_PREVIEW = 1
PROFILE_RELEASE = 2

GEMINI_3_PRO_IMAGE_PREVIEW = "gemini-3-pro-image-preview"
LEGACY_GEMINI_3_PRO_IMAGE_MODEL_ID = "gemini-3.1-pro-preview"

SUPPORTED_ASPECT_RATIOS = frozenset({
    "1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4",
    "9:16", "16:9", "21:9", "1:4", "4:1", "1:8", "8:1",
})
SUPPORTED_MEDIA_RESOLUTION = frozenset({"LOW", "MEDIUM", "HIGH"})
SUPPORTED_THINKING_LEVELS = frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH"})
THINKING_LEVELS_BY_MODEL: dict[str, frozenset[str]] = {
    GEMINI_3_PRO_IMAGE_PREVIEW: frozenset({"LOW", "HIGH"}),
    "gemini-3.1-flash-image-preview": frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH"}),
}


def canonical_gemini_image_model_id(model: str | None) -> str:
    raw = (model or "").strip()
    if not raw:
        return "gemini-2.5-flash-image"
    if raw == LEGACY_GEMINI_3_PRO_IMAGE_MODEL_ID:
        return GEMINI_3_PRO_IMAGE_PREVIEW
    return raw


def clamp_temperature(value: Any, default: float = 0.7) -> float:
    try:
        t = float(value)
        if t != t:
            return default
        return max(0.0, min(2.0, t))
    except (TypeError, ValueError):
        return default


def clamp_top_p(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, parsed))


def normalize_seed(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clamp_candidate_count(value: Any, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(4, parsed))


def normalize_media_resolution(value: Any) -> str | None:
    raw = (str(value).strip().upper() if value is not None else "")
    if not raw:
        return None
    if raw.startswith("MEDIA_RESOLUTION_"):
        raw = raw.removeprefix("MEDIA_RESOLUTION_")
    if raw in SUPPORTED_MEDIA_RESOLUTION:
        return raw
    return None


def normalize_aspect_ratio(value: Any, fallback: str = "3:4") -> str:
    raw = (str(value).strip() if value is not None else "")
    if raw in SUPPORTED_ASPECT_RATIOS:
        return raw
    return fallback


def size_to_aspect_ratio(size: str | None, fallback: str = "1:1") -> str:
    raw = (size or "").strip()
    if not raw or "x" not in raw:
        return fallback
    try:
        w_str, h_str = raw.split("x", 1)
        width = int(w_str)
        height = int(h_str)
        if width <= 0 or height <= 0:
            return fallback
    except (TypeError, ValueError):
        return fallback

    if width == height:
        ratio = "1:1"
    else:
        from math import gcd
        d = gcd(width, height)
        ratio = f"{width // d}:{height // d}"

    if ratio in SUPPORTED_ASPECT_RATIOS:
        return ratio
    return fallback


def _normalize_thinking_level(value: Any) -> str | None:
    raw = (str(value).strip().upper() if value is not None else "")
    if not raw:
        return None
    if raw.startswith("THINKING_LEVEL_"):
        raw = raw.removeprefix("THINKING_LEVEL_")
    if raw in SUPPORTED_THINKING_LEVELS:
        return raw
    return None


def supported_thinking_levels_for_model(model: str | None) -> frozenset[str]:
    return THINKING_LEVELS_BY_MODEL.get(canonical_gemini_image_model_id(model), frozenset())


def normalize_thinking_config(model: str | None, raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    data: dict[str, Any] | None = None
    if isinstance(raw, dict):
        data = dict(raw)
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            data = dict(parsed)
    if not data:
        return None

    level = _normalize_thinking_level(data.get("thinking_level") or data.get("thinkingLevel"))
    budget_raw = data.get("thinking_budget")
    if budget_raw is None:
        budget_raw = data.get("thinkingBudget")
    budget: int | None = None
    if budget_raw is not None:
        try:
            budget = max(0, int(budget_raw))
        except (TypeError, ValueError):
            budget = None

    include_thoughts_raw = data.get("include_thoughts")
    if include_thoughts_raw is None:
        include_thoughts_raw = data.get("includeThoughts")
    include_thoughts = include_thoughts_raw if isinstance(include_thoughts_raw, bool) else None

    out: dict[str, Any] = {}
    if level and level in supported_thinking_levels_for_model(model):
        out["thinking_level"] = level
    elif budget is not None:
        out["thinking_budget"] = budget
    if include_thoughts is not None:
        out["include_thoughts"] = include_thoughts
    return out or None


class GenerationPromptSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_row(self, row_id: int) -> GenerationPromptSettings | None:
        return self.db.query(GenerationPromptSettings).filter(GenerationPromptSettings.id == row_id).first()

    def get(self) -> GenerationPromptSettings | None:
        return self.get_row(PROFILE_PREVIEW)

    def get_or_create_row(self, row_id: int) -> GenerationPromptSettings:
        row = self.get_row(row_id)
        if row:
            return row
        row = GenerationPromptSettings(id=row_id)
        row.prompt_input = ""
        row.prompt_task = ""
        row.prompt_identity_transfer = ""
        row.safety_constraints = ""
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_preview(self) -> GenerationPromptSettings:
        return self.get_or_create_row(PROFILE_PREVIEW)

    def get_release(self) -> GenerationPromptSettings:
        return self.get_or_create_row(PROFILE_RELEASE)

    def get_or_create(self) -> GenerationPromptSettings:
        return self.get_preview()

    def _normalize_defaults_from_mapping(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        model = canonical_gemini_image_model_id(
            str(raw.get("default_model") or "").strip()
            or getattr(settings, "gemini_image_model", "gemini-2.5-flash-image")
        )
        aspect_ratio = normalize_aspect_ratio(raw.get("default_aspect_ratio"), fallback="3:4")
        size = (str(raw.get("default_size") or "").strip() or aspect_ratio_to_size(aspect_ratio))
        fmt = (str(raw.get("default_format") or "").strip() or "png")
        tier = (str(raw.get("default_image_size_tier") or "").strip().upper() or "1K")
        if tier not in ("256", "512", "1K", "2K", "4K"):
            tier = "1K"

        return {
            "default_model": model,
            "default_size": size,
            "default_format": fmt,
            "default_temperature": clamp_temperature(raw.get("default_temperature"), default=0.7),
            "default_temperature_a": (
                clamp_temperature(raw.get("default_temperature_a"), default=0.7)
                if raw.get("default_temperature_a") not in (None, "")
                else None
            ),
            "default_temperature_b": (
                clamp_temperature(raw.get("default_temperature_b"), default=0.7)
                if raw.get("default_temperature_b") not in (None, "")
                else None
            ),
            "default_temperature_c": (
                clamp_temperature(raw.get("default_temperature_c"), default=0.7)
                if raw.get("default_temperature_c") not in (None, "")
                else None
            ),
            "default_image_size_tier": tier,
            "default_aspect_ratio": aspect_ratio,
            "default_top_p": clamp_top_p(raw.get("default_top_p")),
            "default_top_p_a": clamp_top_p(raw.get("default_top_p_a")),
            "default_top_p_b": clamp_top_p(raw.get("default_top_p_b")),
            "default_top_p_c": clamp_top_p(raw.get("default_top_p_c")),
            "default_seed": normalize_seed(raw.get("default_seed")),
            "default_candidate_count": clamp_candidate_count(raw.get("default_candidate_count"), default=1),
            "default_media_resolution": normalize_media_resolution(raw.get("default_media_resolution")),
            "default_thinking_config": normalize_thinking_config(model, raw.get("default_thinking_config")),
        }

    def _normalize_defaults_from_row(self, row: GenerationPromptSettings) -> dict[str, Any]:
        mapping = {
            "default_model": getattr(row, "default_model", None),
            "default_size": getattr(row, "default_size", None),
            "default_format": getattr(row, "default_format", None),
            "default_temperature": getattr(row, "default_temperature", None),
            "default_temperature_a": getattr(row, "default_temperature_a", None),
            "default_temperature_b": getattr(row, "default_temperature_b", None),
            "default_temperature_c": getattr(row, "default_temperature_c", None),
            "default_image_size_tier": getattr(row, "default_image_size_tier", None),
            "default_aspect_ratio": getattr(row, "default_aspect_ratio", None),
            "default_top_p": getattr(row, "default_top_p", None),
            "default_top_p_a": getattr(row, "default_top_p_a", None),
            "default_top_p_b": getattr(row, "default_top_p_b", None),
            "default_top_p_c": getattr(row, "default_top_p_c", None),
            "default_seed": getattr(row, "default_seed", None),
            "default_candidate_count": getattr(row, "default_candidate_count", None),
            "default_media_resolution": getattr(row, "default_media_resolution", None),
            "default_thinking_config": getattr(row, "default_thinking_config", None),
        }
        return self._normalize_defaults_from_mapping(mapping)

    def normalize_profile_payload(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        out = self._normalize_defaults_from_mapping(raw)
        out.update({
            "prompt_input": strip_legacy_master_prompt_boilerplate(str(raw.get("prompt_input") or "").strip()),
            "prompt_input_enabled": bool(raw.get("prompt_input_enabled", True)),
            "prompt_task": "",
            "prompt_task_enabled": bool(raw.get("prompt_task_enabled", True)),
            "prompt_identity_transfer": (str(raw.get("prompt_identity_transfer") or "").strip()),
            "prompt_identity_transfer_enabled": bool(raw.get("prompt_identity_transfer_enabled", True)),
            "safety_constraints": (str(raw.get("safety_constraints") or "").strip()),
            "safety_constraints_enabled": bool(raw.get("safety_constraints_enabled", True)),
        })
        return out

    def get_effective(self, profile: str = "release") -> dict[str, Any]:
        """Для воркера: только включённые блоки и дефолты. profile='release' (id=2) или 'preview' (id=1)."""
        row_id = PROFILE_RELEASE if profile == "release" else PROFILE_PREVIEW
        try:
            row = self.get_or_create_row(row_id)
        except Exception:
            return self._default_effective()

        defaults = self._normalize_defaults_from_row(row)
        return {
            "prompt_input": _effective_master_prompt_from_row(row),
            "prompt_task": "",
            "prompt_identity_transfer": (row.prompt_identity_transfer or "").strip() if row.prompt_identity_transfer_enabled else "",
            "safety_constraints": (row.safety_constraints or "").strip() if row.safety_constraints_enabled else "",
            **defaults,
        }

    def _default_effective(self) -> dict[str, Any]:
        defaults = self._normalize_defaults_from_mapping({
            "default_model": getattr(settings, "gemini_image_model", "gemini-2.5-flash-image"),
            "default_size": "1024x1024",
            "default_format": "png",
            "default_temperature": 0.7,
            "default_image_size_tier": "1K",
            "default_aspect_ratio": "3:4",
            "default_candidate_count": 1,
        })
        return {
            **RECOMMENDED_DEFAULTS,
            **defaults,
        }

    def as_dict(self) -> dict[str, Any]:
        """Возвращает оба профиля: preview (id=1) и release (id=2)."""
        try:
            preview = self.get_or_create_row(PROFILE_PREVIEW)
            release = self.get_or_create_row(PROFILE_RELEASE)
        except Exception:
            d = self._default_as_dict()
            return {"preview": d, "release": dict(d)}
        return {
            "preview": self._row_to_dict(preview),
            "release": self._row_to_dict(release),
        }

    def _row_to_dict(self, row: GenerationPromptSettings) -> dict[str, Any]:
        defaults = self._normalize_defaults_from_row(row)
        return {
            "prompt_input": _effective_master_prompt_from_row(row),
            "prompt_input_enabled": bool(row.prompt_input_enabled),
            "prompt_task": "",
            "prompt_task_enabled": bool(row.prompt_task_enabled),
            "prompt_identity_transfer": (row.prompt_identity_transfer or "").strip(),
            "prompt_identity_transfer_enabled": bool(row.prompt_identity_transfer_enabled),
            "safety_constraints": (row.safety_constraints or "").strip(),
            "safety_constraints_enabled": bool(row.safety_constraints_enabled),
            **defaults,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _default_as_dict(self) -> dict[str, Any]:
        defaults = self._normalize_defaults_from_mapping({
            "default_model": "gemini-2.5-flash-image",
            "default_size": "1024x1024",
            "default_format": "png",
            "default_temperature": 0.7,
            "default_image_size_tier": "1K",
            "default_aspect_ratio": "3:4",
            "default_candidate_count": 1,
        })
        return {
            "prompt_input": RECOMMENDED_DEFAULTS["prompt_input"],
            "prompt_input_enabled": True,
            "prompt_task": RECOMMENDED_DEFAULTS["prompt_task"],
            "prompt_task_enabled": True,
            "prompt_identity_transfer": RECOMMENDED_DEFAULTS["prompt_identity_transfer"],
            "prompt_identity_transfer_enabled": True,
            "safety_constraints": RECOMMENDED_DEFAULTS["safety_constraints"],
            "safety_constraints_enabled": True,
            **defaults,
            "updated_at": None,
        }

    def _apply_row_data(self, row: GenerationPromptSettings, data: dict[str, Any]) -> None:
        for key in ("prompt_input", "prompt_task", "prompt_identity_transfer", "safety_constraints"):
            if key in data:
                val = "" if data[key] is None else str(data[key])
                if key == "prompt_input":
                    val = strip_legacy_master_prompt_boilerplate(val)
                if key == "prompt_task":
                    val = ""
                setattr(row, key, val)
        for key in ("prompt_input_enabled", "prompt_task_enabled", "prompt_identity_transfer_enabled", "safety_constraints_enabled"):
            if key in data:
                setattr(row, key, bool(data[key]))
        for key in ("default_model", "default_size", "default_format"):
            if key in data:
                setattr(
                    row,
                    key,
                    (str(data[key]) or "").strip() or {
                        "default_model": "gemini-2.5-flash-image",
                        "default_size": "1024x1024",
                        "default_format": "png",
                    }[key],
                )

        if "default_temperature" in data and data["default_temperature"] is not None:
            row.default_temperature = clamp_temperature(data.get("default_temperature"), default=0.7)
        for key in ("default_temperature_a", "default_temperature_b", "default_temperature_c"):
            if key in data:
                row_value = data.get(key)
                setattr(
                    row,
                    key,
                    None if row_value in (None, "") else clamp_temperature(row_value, default=0.7),
                )

        if "default_image_size_tier" in data and data["default_image_size_tier"] is not None:
            tier = str(data["default_image_size_tier"]).strip().upper()
            if tier in ("256", "512", "1K", "2K", "4K"):
                row.default_image_size_tier = tier

        if "default_aspect_ratio" in data and data["default_aspect_ratio"] is not None:
            row.default_aspect_ratio = normalize_aspect_ratio(data["default_aspect_ratio"], fallback="3:4")
            # Keep legacy default_size consistent with aspect-ratio-first behavior.
            if "default_size" not in data:
                row.default_size = aspect_ratio_to_size(row.default_aspect_ratio)

        if "default_top_p" in data:
            row.default_top_p = clamp_top_p(data.get("default_top_p"))
        for key in ("default_top_p_a", "default_top_p_b", "default_top_p_c"):
            if key in data:
                setattr(row, key, clamp_top_p(data.get(key)))

        if "default_seed" in data:
            row.default_seed = normalize_seed(data.get("default_seed"))

        if "default_candidate_count" in data:
            row.default_candidate_count = clamp_candidate_count(data.get("default_candidate_count"), default=1)

        if "default_media_resolution" in data:
            row.default_media_resolution = normalize_media_resolution(data.get("default_media_resolution"))

        if "default_thinking_config" in data:
            model_for_thinking = canonical_gemini_image_model_id(
                str(data.get("default_model") or row.default_model or settings.gemini_image_model or "gemini-2.5-flash-image")
            )
            row.default_thinking_config = normalize_thinking_config(model_for_thinking, data.get("default_thinking_config"))

        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        if "preview" in data:
            row = self.get_or_create_row(PROFILE_PREVIEW)
            self._apply_row_data(row, data["preview"])
        if "release" in data:
            row = self.get_or_create_row(PROFILE_RELEASE)
            self._apply_row_data(row, data["release"])
        if "preview" not in data and "release" not in data:
            row = self.get_or_create_row(PROFILE_PREVIEW)
            self._apply_row_data(row, data)
        self.db.commit()
        return self.as_dict()

    def reset_to_recommended(self) -> dict[str, Any]:
        row = self.get_or_create_row(PROFILE_PREVIEW)
        row.prompt_input = RECOMMENDED_DEFAULTS["prompt_input"]
        row.prompt_task = RECOMMENDED_DEFAULTS["prompt_task"]
        row.prompt_identity_transfer = RECOMMENDED_DEFAULTS["prompt_identity_transfer"]
        row.safety_constraints = RECOMMENDED_DEFAULTS["safety_constraints"]
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self._row_to_dict(row)
