"""
Playground API: default config, log stream, save to trend, test prompt.
Paths match admin-frontend/src/services/playgroundApi.ts.
"""
import asyncio
import base64
from io import BytesIO
import json
import logging
import os
import tempfile
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from PIL import Image
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.trend import Trend
from app.services.auth.jwt import get_current_user, verify_token
from app.services.generation_prompt.settings_service import GenerationPromptSettingsService
from app.services.image_generation import (
    ImageGenerationError,
    ImageGenerationRequest,
    ImageProviderFactory,
    generate_with_retry,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/playground", tags=["playground"])

SUPPORTED_ASPECT_RATIOS = frozenset({
    "1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4",
    "9:16", "16:9", "21:9", "1:4", "4:1", "1:8", "8:1",
})
SUPPORTED_MEDIA_RESOLUTION = frozenset({"LOW", "MEDIUM", "HIGH"})
SUPPORTED_THINKING_LEVELS = frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH"})
MAX_INLINE_UPLOAD_BYTES = 7 * 1024 * 1024
MAX_TOTAL_INLINE_UPLOAD_BYTES = 50 * 1024 * 1024
# Official image model (Nano Banana Pro): https://ai.google.dev/gemini-api/docs/models/gemini-3-pro-image-preview
# Legacy UI/DB string (was conflated with text model id):
_LEGACY_GEMINI_3_PRO_IMAGE_MODEL_ID = "gemini-3.1-pro-preview"
_GEMINI_3_PRO_IMAGE_PREVIEW = "gemini-3-pro-image-preview"

_PLAYGROUND_INPUT_LIMIT_BY_MODEL = {
    "gemini-2.5-flash-image": 3,
    _GEMINI_3_PRO_IMAGE_PREVIEW: 14,
    "gemini-3.1-flash-image-preview": 14,
}
_PLAYGROUND_MAX_CANDIDATE_BY_MODEL = {
    "gemini-2.5-flash-image": 1,
    _GEMINI_3_PRO_IMAGE_PREVIEW: 4,
    "gemini-3.1-flash-image-preview": 1,
}
_PLAYGROUND_MODELS_SUPPORTING_MEDIA_RESOLUTION = frozenset({
    _GEMINI_3_PRO_IMAGE_PREVIEW,
})
_PLAYGROUND_THINKING_LEVELS_BY_MODEL = {
    _GEMINI_3_PRO_IMAGE_PREVIEW: frozenset({"LOW", "HIGH"}),
    "gemini-3.1-flash-image-preview": frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH"}),
}
_ALLOWED_UPLOAD_MIME_TYPES = frozenset({
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif",
    "application/pdf",
})
_PLAYGROUND_SCHEMA_REQUIRED_COLUMNS = (
    "prompt_aspect_ratio",
    "prompt_top_p",
    "prompt_candidate_count",
    "prompt_media_resolution",
    "prompt_thinking_config",
)
_PLAYGROUND_SCHEMA_CHECK_OK: bool | None = None

PLAYGROUND_BATCH_MAX_TRENDS = 200
PLAYGROUND_BATCH_MAX_CONCURRENCY = 20
PLAYGROUND_BATCH_DEFAULT_CONCURRENCY = 10
_PLAYGROUND_BATCH_OVERLAY_KEYS = (
    "model",
    "temperature",
    "top_p",
    "candidate_count",
    "media_resolution",
    "thinking_config",
    "format",
    "size",
    "aspect_ratio",
    "seed",
    "image_size_tier",
)


def _unlink_playground_temp_paths(paths: list[str]) -> None:
    for path in paths:
        try:
            if path and os.path.isfile(path):
                os.unlink(path)
        except Exception:
            pass


async def get_current_user_or_query_token(request: Request) -> dict:
    """For SSE: accept token in query (?token=) since EventSource cannot send Authorization header."""
    token = request.query_params.get("token")
    if not token and request.headers.get("Authorization"):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token (query ?token= or Bearer)")
    payload = verify_token(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return {"username": payload.get("sub")}


# ---------- Pydantic models (match frontend PlaygroundPromptConfig) ----------
class PlaygroundSection(BaseModel):
    id: str
    label: str
    content: str = ""
    enabled: bool = True
    order: int = 0


class PlaygroundPromptConfig(BaseModel):
    model: str = "gemini-2.5-flash-image"
    temperature: float = Field(ge=0, le=2, default=0.4)
    top_p: float | None = Field(default=None, ge=0, le=1)
    candidate_count: int = Field(default=1, ge=1, le=4)
    media_resolution: str | None = None
    thinking_config: dict[str, Any] | None = None
    format: str = "png"
    size: str | None = None
    aspect_ratio: str | None = None
    sections: list[PlaygroundSection] = []
    variables: dict[str, str] = Field(default_factory=dict)
    seed: int | None = None
    image_size_tier: str | None = None

    @field_validator("aspect_ratio")
    @classmethod
    def validate_aspect_ratio(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if cleaned not in SUPPORTED_ASPECT_RATIOS:
            raise ValueError(f"Unsupported aspect_ratio: {cleaned}")
        return cleaned

    @field_validator("media_resolution")
    @classmethod
    def validate_media_resolution(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize_media_resolution(value)
        if not normalized:
            cleaned = value.strip().upper()
            raise ValueError(f"Unsupported media_resolution: {cleaned}")
        return normalized


def _style_preset_content_to_text(content: str) -> str:
    """Convert Style section content (JSON or plain text) to worker-style 'k: v' string."""
    content = (content or "").strip()
    if not content:
        return ""
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return " ".join(f"{k}: {v}" for k, v in sorted(parsed.items()) if v is not None and v != "")
        if isinstance(parsed, str):
            return parsed.strip()
    except (json.JSONDecodeError, TypeError):
        pass
    return content


def _build_prompt_from_config(config: PlaygroundPromptConfig) -> str:
    """Build single prompt string from enabled sections; add []/[STYLE]/[AVOID] to match worker."""
    parts = []
    for s in sorted(config.sections, key=lambda x: x.order):
        if not s.enabled or not s.content.strip():
            continue
        text = s.content.strip()
        for k, v in (config.variables or {}).items():
            text = text.replace("{{" + k + "}}", str(v))
        label = (s.label or "").strip().lower()
        if label == "scene":
            parts.append("[]\n" + text)
        elif label == "style":
            style_text = _style_preset_content_to_text(text)
            if style_text:
                parts.append("[STYLE]\n" + style_text)
        elif label == "avoid":
            parts.append("[AVOID]\n" + text)
        elif label == "composition":
            parts.append("[COMPOSITION]\n" + text)
        else:
            parts.append(text)
    return "\n\n".join(parts) if parts else "Generate an image."


def _build_full_prompt_for_playground(db: Session, config: PlaygroundPromptConfig) -> str:
    """Build prompt with master blocks ([INPUT], [TASK], [IDENTITY TRANSFER]) + sections + [SAFETY] for Playground test."""
    svc = GenerationPromptSettingsService(db)
    effective = svc.get_effective(profile="preview")
    blocks = []
    prompt_input = (effective.get("prompt_input") or "").strip()
    if prompt_input:
        blocks.append("[INPUT]\n" + prompt_input)
    prompt_task = (effective.get("prompt_task") or "").strip()
    if prompt_task:
        blocks.append("[TASK]\n" + prompt_task)
    identity = (effective.get("prompt_identity_transfer") or "").strip()
    if identity:
        blocks.append("[IDENTITY TRANSFER]\n" + identity)
    sections_text = _build_prompt_from_config(config)
    if sections_text:
        blocks.append(sections_text)
    safety = (effective.get("safety_constraints") or "").strip()
    if safety:
        blocks.append("[SAFETY]\n" + safety)
    return "\n\n".join(blocks)


# ---------- Helpers for sent_request (mirror Gemini provider payload) ----------
def _playground_size_to_aspect_ratio(size: str | None) -> str:
    """Convert size like '1024x1024' to aspect ratio like '1:1'."""
    if not size or "x" not in size:
        return "1:1"
    try:
        w, h = size.split("x")
        width, height = int(w), int(h)
    except (ValueError, TypeError):
        return "1:1"
    if width == height:
        return "1:1"
    if width * 9 == height * 16:
        return "9:16"
    if width * 16 == height * 9:
        return "16:9"
    if width * 3 == height * 4:
        return "3:4"
    if width * 4 == height * 3:
        return "4:3"
    from math import gcd
    d = gcd(width, height)
    return f"{width // d}:{height // d}"


def _playground_effective_aspect_ratio(config: PlaygroundPromptConfig) -> str:
    ratio = (config.aspect_ratio or "").strip()
    if ratio in SUPPORTED_ASPECT_RATIOS:
        return ratio
    by_size = _playground_size_to_aspect_ratio(config.size or "1024x1024")
    if by_size in SUPPORTED_ASPECT_RATIOS:
        return by_size
    return "1:1"


def _normalize_playground_gemini_image_model_id(model: str | None) -> str:
    """Deprecated `gemini-3.1-pro-preview` → official image model `gemini-3-pro-image-preview`."""
    m = (model or "").strip()
    if not m:
        return "gemini-2.5-flash-image"
    if m == _LEGACY_GEMINI_3_PRO_IMAGE_MODEL_ID:
        return _GEMINI_3_PRO_IMAGE_PREVIEW
    return m


def _playground_max_input_images(model: str | None) -> int:
    model_name = _normalize_playground_gemini_image_model_id(model)
    return _PLAYGROUND_INPUT_LIMIT_BY_MODEL.get(model_name, 3)


def _safe_candidate_count(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(4, parsed))


def _playground_max_candidate_count(model: str | None) -> int:
    model_name = _normalize_playground_gemini_image_model_id(model)
    return _PLAYGROUND_MAX_CANDIDATE_BY_MODEL.get(model_name, 1)


def _playground_supports_media_resolution(model: str | None) -> bool:
    model_name = _normalize_playground_gemini_image_model_id(model)
    return model_name in _PLAYGROUND_MODELS_SUPPORTING_MEDIA_RESOLUTION


def _safe_top_p(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, parsed))


def _normalize_upload_mime_type(raw: str | None) -> str | None:
    value = (raw or "").strip().lower()
    if not value:
        return None
    if value == "image/jpg":
        value = "image/jpeg"
    return value


def _normalize_media_resolution(value: str | None) -> str | None:
    raw = (value or "").strip().upper()
    if not raw:
        return None
    if raw.startswith("MEDIA_RESOLUTION_"):
        raw = raw.removeprefix("MEDIA_RESOLUTION_")
    if raw in SUPPORTED_MEDIA_RESOLUTION:
        return raw
    return None


def _media_resolution_to_api_enum(value: str | None) -> str | None:
    normalized = _normalize_media_resolution(value)
    if not normalized:
        return None
    return f"MEDIA_RESOLUTION_{normalized}"


def _normalize_thinking_level(value: str | None) -> str | None:
    raw = (value or "").strip().upper()
    if not raw:
        return None
    if raw.startswith("THINKING_LEVEL_"):
        raw = raw.removeprefix("THINKING_LEVEL_")
    if raw in SUPPORTED_THINKING_LEVELS:
        return raw
    return None


def _playground_supported_thinking_levels(model: str | None) -> frozenset[str]:
    model_name = _normalize_playground_gemini_image_model_id(model)
    return _PLAYGROUND_THINKING_LEVELS_BY_MODEL.get(model_name, frozenset())


def _effective_playground_thinking_config(model: str | None, raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    cfg = dict(raw)
    level = _normalize_thinking_level(cfg.get("thinking_level") or cfg.get("thinkingLevel"))
    budget_raw = cfg.get("thinking_budget")
    if budget_raw is None:
        budget_raw = cfg.get("thinkingBudget")
    budget: int | None = None
    if budget_raw is not None:
        try:
            budget = int(budget_raw)
        except (TypeError, ValueError):
            budget = None
    include_thoughts_raw = cfg.get("include_thoughts")
    if include_thoughts_raw is None:
        include_thoughts_raw = cfg.get("includeThoughts")
    include_thoughts = include_thoughts_raw if isinstance(include_thoughts_raw, bool) else None

    out: dict[str, Any] = {}
    if level and level in _playground_supported_thinking_levels(model):
        out["thinking_level"] = level
    elif budget is not None:
        out["thinking_budget"] = budget
    if include_thoughts is not None:
        out["include_thoughts"] = include_thoughts
    return out or None


def _convert_output_image_bytes(raw: bytes, target_format: str) -> tuple[str, bytes]:
    fmt = (target_format or "png").strip().lower()
    if fmt not in {"png", "jpeg", "webp"}:
        fmt = "png"

    with Image.open(BytesIO(raw)) as img:
        out = BytesIO()
        if fmt == "jpeg":
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(out, format="JPEG", quality=95)
            return "image/jpeg", out.getvalue()
        if fmt == "webp":
            if img.mode == "P":
                img = img.convert("RGBA")
            img.save(out, format="WEBP", quality=95)
            return "image/webp", out.getvalue()
        if img.mode == "P":
            img = img.convert("RGBA")
        img.save(out, format="PNG")
        return "image/png", out.getvalue()


def _ensure_playground_schema(db: Session) -> None:
    global _PLAYGROUND_SCHEMA_CHECK_OK
    if _PLAYGROUND_SCHEMA_CHECK_OK is True:
        return
    rows = db.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='trends'"
    )).all()
    existing = {str(r[0]) for r in rows}
    missing_cols = [c for c in _PLAYGROUND_SCHEMA_REQUIRED_COLUMNS if c not in existing]
    if missing_cols:
        missing = ", ".join(missing_cols)
        raise HTTPException(
            status_code=503,
            detail=f"Playground schema not ready. Missing columns: {missing}. Run migrations/069_playground_multimodal_params.sql",
        )
    _PLAYGROUND_SCHEMA_CHECK_OK = True


_MODELS_SUPPORTING_IMAGE_SIZE = frozenset({_GEMINI_3_PRO_IMAGE_PREVIEW, "gemini-3.1-flash-image-preview"})
_MODEL_MAX_IMAGE_TIER = {
    "gemini-2.5-flash-image": "4K",
    _GEMINI_3_PRO_IMAGE_PREVIEW: "4K",
    "gemini-3.1-flash-image-preview": "4K",
}


def _effective_image_size_tier(model: str, requested_tier: str | None) -> str:
    """Return imageSize tier for display (match provider logic)."""
    tier_order = ("256", "512", "1K", "2K", "4K")
    model = _normalize_playground_gemini_image_model_id(model)
    max_tier = _MODEL_MAX_IMAGE_TIER.get(model, "2K")
    max_idx = tier_order.index(max_tier) if max_tier in tier_order else 3
    min_idx = 3 if max_idx >= 3 else 0
    requested = (requested_tier or "").strip().upper() or "2K"
    req_idx = tier_order.index(requested) if requested in tier_order else 3
    use_idx = max(min_idx, min(req_idx, max_idx))
    return tier_order[use_idx]


def _build_sent_request_playground(
    config: PlaygroundPromptConfig,
    prompt: str,
    input_files: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build sanitized request payload as sent to Gemini (image data replaced with placeholder)."""
    model = (config.model or "gemini-2.5-flash-image").strip()
    temperature = config.temperature if config.temperature is not None else 0.4
    temperature = max(0.0, min(2.0, float(temperature)))
    seed = config.seed if config.seed is not None else 42
    if not isinstance(seed, int):
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            seed = 42

    parts: list[dict[str, Any]] = [{"text": prompt}]
    for item in input_files:
        size_bytes = int(item.get("size_bytes") or 0)
        mime_type = str(item.get("mime_type") or "image/jpeg")
        parts.append({
            "inlineData": {
                "mimeType": mime_type,
                "data": f"[REDACTED, {size_bytes} bytes]",
            },
        })

    aspect_ratio = _playground_effective_aspect_ratio(config)
    image_config: dict[str, Any] = {"aspectRatio": aspect_ratio}
    if model in _MODELS_SUPPORTING_IMAGE_SIZE and config.image_size_tier:
        image_config["imageSize"] = _effective_image_size_tier(model, config.image_size_tier)

    generation_config: dict[str, Any] = {
        "responseModalities": ["IMAGE"],
        "temperature": temperature,
        "seed": seed,
        "imageConfig": image_config,
    }
    if config.top_p is not None:
        generation_config["topP"] = max(0.0, min(1.0, float(config.top_p)))
    max_candidates = _playground_max_candidate_count(model)
    if config.candidate_count is not None:
        generation_config["candidateCount"] = max(1, min(max_candidates, int(config.candidate_count)))
    media_resolution = _media_resolution_to_api_enum(config.media_resolution)
    if media_resolution and _playground_supports_media_resolution(model):
        generation_config["mediaResolution"] = media_resolution
    effective_thinking = _effective_playground_thinking_config(model, config.thinking_config)
    if effective_thinking:
        thinking_payload: dict[str, Any] = {}
        if "thinking_level" in effective_thinking:
            thinking_payload["thinkingLevel"] = effective_thinking["thinking_level"]
        elif "thinking_budget" in effective_thinking:
            thinking_payload["thinkingBudget"] = int(effective_thinking["thinking_budget"])
        if isinstance(effective_thinking.get("include_thoughts"), bool):
            thinking_payload["includeThoughts"] = effective_thinking["include_thoughts"]
        if thinking_payload:
            generation_config["thinkingConfig"] = thinking_payload

    return {
        "model": model,
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": generation_config,
    }


def trend_to_playground_config(
    trend: Trend,
    default_model: str = "gemini-2.5-flash-image",
    default_temperature: float = 0.4,
    default_format: str = "png",
    default_size: str = "1024x1024",
) -> PlaygroundPromptConfig:
    """Build PlaygroundPromptConfig from trend (single source of truth for load)."""
    sections_raw = trend.prompt_sections if isinstance(trend.prompt_sections, list) else []
    has_meaningful_sections = sections_raw and any(
        (s or {}).get("content") for s in sections_raw
    )
    if has_meaningful_sections:
        sections = []
        for i, s in enumerate(sections_raw):
            sections.append(
                PlaygroundSection(
                    id=str(s.get("id", i + 1)),
                    label=str(s.get("label", f"Section {i + 1}")),
                    content=str(s.get("content", "")),
                    enabled=s.get("enabled", True),
                    order=s.get("order") if isinstance(s.get("order"), (int, float)) else i,
                )
            )
        return PlaygroundPromptConfig(
            model=trend.prompt_model or default_model,
            temperature=float(trend.prompt_temperature) if trend.prompt_temperature is not None else default_temperature,
            top_p=_safe_top_p(getattr(trend, "prompt_top_p", None)),
            candidate_count=_safe_candidate_count(getattr(trend, "prompt_candidate_count", 1)),
            media_resolution=getattr(trend, "prompt_media_resolution", None),
            thinking_config=_effective_playground_thinking_config(
                trend.prompt_model or default_model,
                getattr(trend, "prompt_thinking_config", None),
            ),
            format=trend.prompt_format or default_format,
            size=trend.prompt_size or default_size,
            aspect_ratio=getattr(trend, "prompt_aspect_ratio", None) or _playground_size_to_aspect_ratio(trend.prompt_size or default_size),
            sections=sections,
            variables={},
            seed=trend.prompt_seed if getattr(trend, "prompt_seed", None) is not None else None,
            image_size_tier=getattr(trend, "prompt_image_size_tier", None) or None,
        )
    scene_content = (trend.scene_prompt or trend.system_prompt or "").strip()
    style_preset = trend.style_preset
    if style_preset is None:
        style_content = ""
    elif isinstance(style_preset, dict):
        style_content = json.dumps(style_preset, ensure_ascii=False, indent=2) if style_preset else ""
    else:
        style_content = str(style_preset).strip() if style_preset else ""
    avoid_content = (trend.negative_scene or "").strip()
    composition_content = (getattr(trend, "composition_prompt", None) or "").strip()
    sections = [
        PlaygroundSection(id="1", label="Scene", content=scene_content, enabled=True, order=0),
        PlaygroundSection(id="2", label="Style", content=style_content, enabled=True, order=1),
        PlaygroundSection(id="3", label="Avoid", content=avoid_content, enabled=True, order=2),
        PlaygroundSection(id="4", label="Composition", content=composition_content, enabled=True, order=3),
    ]
    return PlaygroundPromptConfig(
        model=trend.prompt_model or default_model,
        temperature=float(trend.prompt_temperature) if trend.prompt_temperature is not None else default_temperature,
        top_p=_safe_top_p(getattr(trend, "prompt_top_p", None)),
        candidate_count=_safe_candidate_count(getattr(trend, "prompt_candidate_count", 1)),
        media_resolution=getattr(trend, "prompt_media_resolution", None),
        thinking_config=_effective_playground_thinking_config(
            trend.prompt_model or default_model,
            getattr(trend, "prompt_thinking_config", None),
        ),
        format=trend.prompt_format or default_format,
        size=trend.prompt_size or default_size,
        aspect_ratio=getattr(trend, "prompt_aspect_ratio", None) or _playground_size_to_aspect_ratio(trend.prompt_size or default_size),
        sections=sections,
        variables={},
        seed=trend.prompt_seed if getattr(trend, "prompt_seed", None) is not None else None,
        image_size_tier=getattr(trend, "prompt_image_size_tier", None) or None,
    )


# ---------- GET /admin/playground/config ----------
@router.get("/config", response_model=PlaygroundPromptConfig)
async def get_playground_config(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Default playground config (model, temperature, format, sections, variables). Playground uses preview profile, not release."""
    _ensure_playground_schema(db)
    svc = GenerationPromptSettingsService(db)
    effective = svc.get_effective(profile="preview")
    sections = [
        PlaygroundSection(id="1", label="Scene", content="", enabled=True, order=0),
        PlaygroundSection(id="2", label="Style", content="", enabled=True, order=1),
        PlaygroundSection(id="3", label="Avoid", content="", enabled=True, order=2),
        PlaygroundSection(id="4", label="Composition", content="", enabled=True, order=3),
    ]
    return PlaygroundPromptConfig(
        model=effective.get("default_model", "gemini-2.5-flash-image"),
        temperature=effective.get("default_temperature", 0.4),
        top_p=None,
        candidate_count=1,
        media_resolution=None,
        thinking_config=None,
        format=effective.get("default_format", "png"),
        size=effective.get("default_size") or "1024x1024",
        aspect_ratio=_playground_size_to_aspect_ratio(effective.get("default_size") or "1024x1024"),
        sections=sections,
        variables={},
    )


# ---------- GET /admin/playground/logs/stream (SSE) ----------
async def _sse_heartbeat_generator():
    """Send heartbeat every 15s so EventSource stays open."""
    while True:
        await asyncio.sleep(15)
        yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': asyncio.get_event_loop().time()})}\n\n"


@router.get("/logs/stream")
async def logs_stream(
    current_user: dict = Depends(get_current_user_or_query_token),
):
    """
    SSE stream for playground logs. EventSource cannot send Authorization header;
    frontend can pass token in query: /admin/playground/logs/stream?token=JWT
    """
    async def event_stream():
        import time
        while True:
            await asyncio.sleep(15)
            yield f"data: {json.dumps({'level': 'info', 'message': 'heartbeat', 'timestamp': time.time()})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ---------- PUT /admin/playground/trends/{id} ----------
@router.put("/trends/{trend_id}")
async def save_to_trend(
    trend_id: str,
    body: PlaygroundPromptConfig,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Save playground config into trend (sections, model, size, format, temperature, seed, image_size_tier)."""
    _ensure_playground_schema(db)
    trend = db.query(Trend).filter(Trend.id == trend_id).first()
    if not trend:
        return {"ok": False, "detail": "Trend not found"}
    trend.prompt_sections = [s.model_dump() for s in body.sections]
    trend.prompt_model = body.model or None
    trend.prompt_size = body.size or None
    trend.prompt_aspect_ratio = body.aspect_ratio or _playground_size_to_aspect_ratio(body.size or "1024x1024")
    trend.prompt_format = body.format or None
    trend.prompt_temperature = body.temperature
    trend.prompt_seed = int(body.seed) if body.seed is not None else None
    trend.prompt_image_size_tier = body.image_size_tier or None
    trend.prompt_top_p = body.top_p if body.top_p is not None else None
    trend.prompt_candidate_count = int(body.candidate_count) if body.candidate_count is not None else 1
    trend.prompt_media_resolution = body.media_resolution or None
    trend.prompt_thinking_config = _effective_playground_thinking_config(body.model, body.thinking_config)
    db.add(trend)
    db.commit()
    return {"ok": True}


def _run_log_entry(level: str, message: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"level": level, "message": message, "timestamp": time.time(), **({"extra": extra} if extra else {})}


def _merge_playground_config_overlay(
    trend_config: PlaygroundPromptConfig,
    overlay: dict[str, Any],
) -> PlaygroundPromptConfig:
    """Apply batch-tab global fields over trend config (matches admin-frontend runBatchTest merge)."""
    d = trend_config.model_dump()
    for key in _PLAYGROUND_BATCH_OVERLAY_KEYS:
        if key in overlay and overlay[key] is not None:
            d[key] = overlay[key]
    return PlaygroundPromptConfig.model_validate(d)


async def _multipart_upload_items_to_temp_files(
    files: list[Any],
) -> tuple[list[str], list[dict[str, Any]], int, str | None]:
    """
    Read uploaded multipart file-like objects into temp files.
    Returns (temp_paths, input_files, total_bytes, error_message).
    On any error, already-created temp files are removed.
    """
    temp_paths: list[str] = []
    input_files: list[dict[str, Any]] = []
    total_bytes = 0
    for item in files:
        mime_type = _normalize_upload_mime_type(getattr(item, "content_type", ""))
        if not mime_type:
            _unlink_playground_temp_paths(temp_paths)
            return [], [], 0, "Missing content type for uploaded file"
        if mime_type not in _ALLOWED_UPLOAD_MIME_TYPES:
            _unlink_playground_temp_paths(temp_paths)
            return [], [], 0, f"Unsupported file type: {mime_type}"
        data = await item.read()
        if len(data) > MAX_INLINE_UPLOAD_BYTES:
            _unlink_playground_temp_paths(temp_paths)
            return [], [], 0, f"File too large: {len(data)} bytes. Max {MAX_INLINE_UPLOAD_BYTES} bytes (7 MB)."
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL_INLINE_UPLOAD_BYTES:
            _unlink_playground_temp_paths(temp_paths)
            return (
                [],
                [],
                0,
                (
                    f"Total upload too large: {total_bytes} bytes. "
                    f"Max total size is {MAX_TOTAL_INLINE_UPLOAD_BYTES} bytes."
                ),
            )
        suffix = ".jpg"
        if mime_type == "image/png":
            suffix = ".png"
        elif mime_type == "image/webp":
            suffix = ".webp"
        elif mime_type == "application/pdf":
            suffix = ".pdf"
        elif mime_type in ("image/heic", "image/heif"):
            suffix = ".heic"
        f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        f.write(data)
        f.close()
        temp_paths.append(f.name)
        input_files.append({
            "path": f.name,
            "mime_type": mime_type or "image/jpeg",
            "size_bytes": len(data),
        })
    return temp_paths, input_files, total_bytes, None


def _sse_data_line(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---------- POST /admin/playground/test ----------
@router.post("/test")
async def test_prompt(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Multipart: config (JSON string), image1 (optional file — user photo for scene transfer).
    Returns { image_url?, error?, sent_request?, run_log? } (snake_case for frontend).
    """
    run_log: list[dict[str, Any]] = []
    sent_request: dict[str, Any] | None = None
    temp_paths: list[str] = []

    try:
        _ensure_playground_schema(db)
        form = await request.form()
        config_raw = form.get("config")
        if not config_raw:
            return {"error": "Missing 'config' in form", "sent_request": None, "run_log": run_log}
        if hasattr(config_raw, "read"):
            maybe_data = config_raw.read()
            if asyncio.iscoroutine(maybe_data):
                maybe_data = await maybe_data
            if isinstance(maybe_data, bytes):
                config_raw = maybe_data.decode("utf-8")
            else:
                config_raw = str(maybe_data or "")
        config = PlaygroundPromptConfig.model_validate(json.loads(config_raw))

        run_log.append(_run_log_entry("info", "Request started"))

        prompt = _build_full_prompt_for_playground(db, config)
        raw_images = list(form.getlist("images") or [])
        if not raw_images:
            image1 = form.get("image1")
            if image1 is not None:
                raw_images = [image1]

        model_name = config.model or "gemini-2.5-flash-image"
        max_images = _playground_max_input_images(model_name)
        effective_thinking_config = _effective_playground_thinking_config(model_name, config.thinking_config)
        files = [item for item in raw_images if hasattr(item, "read")]
        if len(files) > max_images:
            return {
                "error": f"Too many input files: got {len(files)}, max {max_images} for model {model_name}",
                "sent_request": None,
                "run_log": run_log,
            }

        more_temp, input_files, total_bytes, upload_err = await _multipart_upload_items_to_temp_files(files)
        if upload_err:
            return {"error": upload_err, "sent_request": None, "run_log": run_log}
        temp_paths.extend(more_temp)

        run_log.append(_run_log_entry("info", "Config", extra={
            "model": model_name,
            "size": config.size or "1024x1024",
            "aspect_ratio": _playground_effective_aspect_ratio(config),
            "temperature": getattr(config, "temperature", 0.4),
            "top_p": config.top_p,
            "candidate_count": config.candidate_count,
            "effective_candidate_count_max": _playground_max_candidate_count(model_name),
            "media_resolution": config.media_resolution,
            "media_resolution_supported": _playground_supports_media_resolution(model_name),
            "thinking_config": effective_thinking_config,
            "seed": config.seed,
            "image_size_tier": config.image_size_tier,
            "input_files_count": len(input_files),
            "input_total_bytes": total_bytes,
            "max_input_files_for_model": max_images,
            "prompt_length": len(prompt),
        }))

        sent_request = _build_sent_request_playground(config, prompt, input_files)
        run_log.append(_run_log_entry("info", "Sending request to Gemini"))

        provider = ImageProviderFactory.create_from_settings(settings, "gemini")
        req = ImageGenerationRequest(
            prompt=prompt,
            model=config.model or None,
            size=config.size or "1024x1024",
            negative_prompt=None,
            input_files=input_files,
            extra_params=None,
            temperature=config.temperature,
            top_p=config.top_p,
            candidate_count=max(1, min(_playground_max_candidate_count(model_name), int(config.candidate_count or 1))),
            media_resolution=config.media_resolution if _playground_supports_media_resolution(model_name) else None,
            thinking_config=effective_thinking_config,
            seed=config.seed,
            image_size_tier=config.image_size_tier,
            aspect_ratio=_playground_effective_aspect_ratio(config),
            allow_high_temperature=True,
        )
        t0 = time.perf_counter()
        result = await run_in_threadpool(
            generate_with_retry,
            provider,
            req,
            settings,
            model_version=config.model or None,
            safety_settings_snapshot=getattr(settings, "gemini_safety_settings", None),
            streaming_enabled=False,
        )
        elapsed = time.perf_counter() - t0

        run_log.append(_run_log_entry("info", f"Gemini responded in {elapsed:.2f}s"))
        contents = result.image_contents if result.image_contents else [result.image_content]
        run_log.append(_run_log_entry("info", f"Success: received {len(contents)} image(s)"))

        fmt = (config.format or "png").lower()
        image_urls: list[str] = []
        for idx, item in enumerate(contents):
            try:
                mime, converted = _convert_output_image_bytes(item, fmt)
            except Exception as e:
                run_log.append(_run_log_entry("error", f"Output conversion failed for image #{idx + 1}: {e}"))
                return {"error": f"Output conversion failed for image #{idx + 1}", "sent_request": sent_request, "run_log": run_log}
            image_urls.append(f"data:{mime};base64,{base64.standard_b64encode(converted).decode('ascii')}")
        return {
            "image_urls": image_urls,
            "image_url": image_urls[0] if image_urls else None,
            "sent_request": sent_request,
            "run_log": run_log,
        }
    except ImageGenerationError as e:
        err_msg = str(e) or (e.detail.get("finish_message") if e.detail else "Generation failed")
        run_log.append(_run_log_entry("error", f"Gemini call failed: {err_msg}", extra=e.detail))
        return {"error": err_msg, "sent_request": sent_request, "run_log": run_log}
    except json.JSONDecodeError as e:
        run_log.append(_run_log_entry("error", f"Invalid config JSON: {e}"))
        return {"error": f"Invalid config JSON: {e}", "sent_request": None, "run_log": run_log}
    except Exception as e:
        logger.exception("Playground test failed")
        run_log.append(_run_log_entry("error", str(e)))
        return {"error": str(e), "sent_request": sent_request, "run_log": run_log}
    finally:
        _unlink_playground_temp_paths(temp_paths)


# ---------- POST /admin/playground/batch-test (SSE stream) ----------
@router.post("/batch-test")
async def playground_batch_test(
    request: Request,
    db: Session = Depends(get_db),
    _current_user: dict = Depends(get_current_user),
):
    """
    Multipart: images, trend_ids (JSON array of strings), config_overlay (JSON object),
    concurrency (optional int 1–20).
    Streams Server-Sent Events: one JSON payload per trend, then {"done": true, ...}.
    """
    _ensure_playground_schema(db)
    form = await request.form()

    trend_ids_raw = form.get("trend_ids")
    if not trend_ids_raw:
        raise HTTPException(status_code=400, detail="Missing trend_ids")
    if hasattr(trend_ids_raw, "read"):
        maybe_data = trend_ids_raw.read()
        if asyncio.iscoroutine(maybe_data):
            maybe_data = await maybe_data
        if isinstance(maybe_data, bytes):
            trend_ids_raw = maybe_data.decode("utf-8")
        else:
            trend_ids_raw = str(maybe_data or "")
    try:
        trend_ids: list[Any] = json.loads(trend_ids_raw)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid trend_ids JSON")
    if not isinstance(trend_ids, list):
        raise HTTPException(status_code=400, detail="trend_ids must be a JSON array")
    if len(trend_ids) == 0:
        raise HTTPException(status_code=400, detail="trend_ids is empty")
    trend_ids_str: list[str] = [str(x) for x in trend_ids]
    seen_ids: set[str] = set()
    trend_ids_unique: list[str] = []
    for tid in trend_ids_str:
        if tid not in seen_ids:
            seen_ids.add(tid)
            trend_ids_unique.append(tid)
    trend_ids_str = trend_ids_unique
    if len(trend_ids_str) > PLAYGROUND_BATCH_MAX_TRENDS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many trends: max {PLAYGROUND_BATCH_MAX_TRENDS}",
        )

    overlay_raw = form.get("config_overlay")
    if overlay_raw is None:
        overlay_raw = "{}"
    if hasattr(overlay_raw, "read"):
        maybe_data = overlay_raw.read()
        if asyncio.iscoroutine(maybe_data):
            maybe_data = await maybe_data
        if isinstance(maybe_data, bytes):
            overlay_raw = maybe_data.decode("utf-8")
        else:
            overlay_raw = str(maybe_data or "")
    try:
        config_overlay: dict[str, Any] = json.loads(overlay_raw) if str(overlay_raw).strip() else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid config_overlay JSON")

    conc_field = form.get("concurrency")
    conc_str = ""
    if conc_field is not None and not hasattr(conc_field, "read"):
        conc_str = str(conc_field).strip()
    try:
        concurrency = int(conc_str) if conc_str else PLAYGROUND_BATCH_DEFAULT_CONCURRENCY
    except ValueError:
        concurrency = PLAYGROUND_BATCH_DEFAULT_CONCURRENCY
    concurrency = max(1, min(PLAYGROUND_BATCH_MAX_CONCURRENCY, concurrency))

    gs = GenerationPromptSettingsService(db)
    effective = gs.get_effective(profile="preview")
    default_model = effective.get("default_model", "gemini-2.5-flash-image")
    default_temperature = float(effective.get("default_temperature", 0.4))
    default_format = effective.get("default_format", "png")
    default_size = effective.get("default_size") or "1024x1024"

    rows = db.query(Trend).filter(Trend.id.in_(trend_ids_str)).all()
    trend_map = {str(t.id): t for t in rows}

    merged_for_limits: list[PlaygroundPromptConfig] = []
    for tid in trend_ids_str:
        trend = trend_map.get(tid)
        if not trend:
            continue
        base_cfg = trend_to_playground_config(
            trend,
            default_model=default_model,
            default_temperature=default_temperature,
            default_format=default_format,
            default_size=default_size,
        )
        merged_for_limits.append(_merge_playground_config_overlay(base_cfg, config_overlay))

    overlay_fallback = (config_overlay.get("model") or "").strip() or "gemini-2.5-flash-image"
    if merged_for_limits:
        min_max_files = min(
            _playground_max_input_images(m.model or "gemini-2.5-flash-image")
            for m in merged_for_limits
        )
    else:
        min_max_files = _playground_max_input_images(overlay_fallback)

    raw_images = list(form.getlist("images") or [])
    if not raw_images:
        image1 = form.get("image1")
        if image1 is not None:
            raw_images = [image1]
    files = [item for item in raw_images if hasattr(item, "read")]
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="Missing images")
    if len(files) > min_max_files:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Too many input files: got {len(files)}, max {min_max_files} "
                "for this batch (minimum limit across merged trend configs)"
            ),
        )

    temp_paths, input_files, _, upload_err = await _multipart_upload_items_to_temp_files(files)
    if upload_err:
        raise HTTPException(status_code=400, detail=upload_err)

    work_items: list[tuple[str, str, str, PlaygroundPromptConfig, str]] = []
    try:
        for tid in trend_ids_str:
            trend = trend_map.get(tid)
            tname = trend.name if trend else tid
            emoji = (trend.emoji if trend else "") or ""
            if not trend:
                work_items.append((
                    tid,
                    tname,
                    emoji,
                    PlaygroundPromptConfig(),
                    "",
                ))
                continue
            base_cfg = trend_to_playground_config(
                trend,
                default_model=default_model,
                default_temperature=default_temperature,
                default_format=default_format,
                default_size=default_size,
            )
            merged = _merge_playground_config_overlay(base_cfg, config_overlay)
            prompt = _build_full_prompt_for_playground(db, merged)
            work_items.append((tid, tname, emoji, merged, prompt))
    except Exception:
        _unlink_playground_temp_paths(temp_paths)
        raise

    async def event_stream():
        success_count = 0
        error_count = 0
        sem = asyncio.Semaphore(concurrency)

        async def run_item(
            item: tuple[str, str, str, PlaygroundPromptConfig, str],
        ) -> dict[str, Any]:
            trend_id, tname, emoji, merged, prompt = item
            if not prompt:
                return {
                    "trend_id": trend_id,
                    "trend_name": tname,
                    "trend_emoji": emoji,
                    "status": "error",
                    "duration": 0.0,
                    "error": "Trend not found",
                }
            model_name = merged.model or "gemini-2.5-flash-image"
            eff_thinking = _effective_playground_thinking_config(model_name, merged.thinking_config)
            async with sem:
                t0 = time.perf_counter()
                try:
                    provider = ImageProviderFactory.create_from_settings(settings, "gemini")
                    req = ImageGenerationRequest(
                        prompt=prompt,
                        model=merged.model or None,
                        size=merged.size or "1024x1024",
                        negative_prompt=None,
                        input_files=input_files,
                        extra_params=None,
                        temperature=merged.temperature,
                        top_p=merged.top_p,
                        candidate_count=max(
                            1,
                            min(
                                _playground_max_candidate_count(model_name),
                                int(merged.candidate_count or 1),
                            ),
                        ),
                        media_resolution=merged.media_resolution
                        if _playground_supports_media_resolution(model_name)
                        else None,
                        thinking_config=eff_thinking,
                        seed=merged.seed,
                        image_size_tier=merged.image_size_tier,
                        aspect_ratio=_playground_effective_aspect_ratio(merged),
                        allow_high_temperature=True,
                    )
                    result = await run_in_threadpool(
                        generate_with_retry,
                        provider,
                        req,
                        settings,
                        model_version=merged.model or None,
                        safety_settings_snapshot=getattr(settings, "gemini_safety_settings", None),
                        streaming_enabled=False,
                    )
                    elapsed = time.perf_counter() - t0
                    contents = result.image_contents if result.image_contents else [result.image_content]
                    fmt = (merged.format or "png").lower()
                    if not contents:
                        return {
                            "trend_id": trend_id,
                            "trend_name": tname,
                            "trend_emoji": emoji,
                            "status": "error",
                            "duration": round(elapsed, 3),
                            "error": "No image in response",
                        }
                    first = contents[0]
                    try:
                        mime, converted = _convert_output_image_bytes(first, fmt)
                    except Exception as e:
                        return {
                            "trend_id": trend_id,
                            "trend_name": tname,
                            "trend_emoji": emoji,
                            "status": "error",
                            "duration": round(elapsed, 3),
                            "error": f"Output conversion failed: {e}",
                        }
                    data_url = f"data:{mime};base64,{base64.standard_b64encode(converted).decode('ascii')}"
                    return {
                        "trend_id": trend_id,
                        "trend_name": tname,
                        "trend_emoji": emoji,
                        "status": "success",
                        "duration": round(elapsed, 3),
                        "image_url": data_url,
                    }
                except ImageGenerationError as e:
                    elapsed = time.perf_counter() - t0
                    err_msg = str(e) or (e.detail.get("finish_message") if e.detail else "Generation failed")
                    return {
                        "trend_id": trend_id,
                        "trend_name": tname,
                        "trend_emoji": emoji,
                        "status": "error",
                        "duration": round(elapsed, 3),
                        "error": err_msg,
                    }
                except Exception as e:
                    elapsed = time.perf_counter() - t0
                    logger.exception("Playground batch item failed")
                    return {
                        "trend_id": trend_id,
                        "trend_name": tname,
                        "trend_emoji": emoji,
                        "status": "error",
                        "duration": round(elapsed, 3),
                        "error": str(e),
                    }

        try:
            tasks = [asyncio.create_task(run_item(w)) for w in work_items]
            for fut in asyncio.as_completed(tasks):
                payload = await fut
                if payload.get("status") == "success":
                    success_count += 1
                else:
                    error_count += 1
                yield _sse_data_line(payload)
            yield _sse_data_line({
                "done": True,
                "total": len(work_items),
                "success": success_count,
                "errors": error_count,
            })
        finally:
            _unlink_playground_temp_paths(temp_paths)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
