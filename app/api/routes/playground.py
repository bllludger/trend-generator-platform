"""
Playground API: default config, log stream, save to trend, test prompt.
Paths match admin-frontend/src/services/playgroundApi.ts.
"""
import asyncio
import base64
import json
import logging
import tempfile
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
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
    format: str = "png"
    size: str | None = None
    sections: list[PlaygroundSection] = []
    variables: dict[str, str] = Field(default_factory=dict)
    seed: int | None = None
    image_size_tier: str | None = None


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
    """Build single prompt string from enabled sections; add [SCENE]/[STYLE]/[AVOID] to match worker."""
    parts = []
    for s in sorted(config.sections, key=lambda x: x.order):
        if not s.enabled or not s.content.strip():
            continue
        text = s.content.strip()
        for k, v in (config.variables or {}).items():
            text = text.replace("{{" + k + "}}", str(v))
        label = (s.label or "").strip().lower()
        if label == "scene":
            parts.append("[SCENE]\n" + text)
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
    effective = svc.get_effective()
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
            format=trend.prompt_format or default_format,
            size=trend.prompt_size or default_size,
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
        format=trend.prompt_format or default_format,
        size=trend.prompt_size or default_size,
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
    """Default playground config (model, temperature, format, sections, variables)."""
    svc = GenerationPromptSettingsService(db)
    effective = svc.get_effective()
    sections = [
        PlaygroundSection(id="1", label="Scene", content="", enabled=True, order=0),
        PlaygroundSection(id="2", label="Style", content="", enabled=True, order=1),
        PlaygroundSection(id="3", label="Avoid", content="", enabled=True, order=2),
        PlaygroundSection(id="4", label="Composition", content="", enabled=True, order=3),
    ]
    return PlaygroundPromptConfig(
        model=effective.get("default_model", "gemini-2.5-flash-image"),
        temperature=effective.get("default_temperature", 0.4),
        format=effective.get("default_format", "png"),
        size=effective.get("default_size") or "1024x1024",
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
    trend = db.query(Trend).filter(Trend.id == trend_id).first()
    if not trend:
        return {"ok": False, "detail": "Trend not found"}
    trend.prompt_sections = [s.model_dump() for s in body.sections]
    trend.prompt_model = body.model or None
    trend.prompt_size = body.size or None
    trend.prompt_format = body.format or None
    trend.prompt_temperature = body.temperature
    trend.prompt_seed = int(body.seed) if body.seed is not None else None
    trend.prompt_image_size_tier = body.image_size_tier or None
    db.add(trend)
    db.commit()
    return {"ok": True}


# ---------- POST /admin/playground/test ----------
@router.post("/test")
async def test_prompt(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Multipart: config (JSON string), image1 (optional file — user photo for scene transfer).
    Returns { image_url?: string, error?: string } (snake_case for frontend).
    """
    try:
        form = await request.form()
        config_raw = form.get("config")
        if not config_raw:
            return {"error": "Missing 'config' in form"}
        if hasattr(config_raw, "read"):
            config_raw = (config_raw.read() or b"").decode("utf-8")
        config = PlaygroundPromptConfig.model_validate(json.loads(config_raw))

        prompt = _build_full_prompt_for_playground(db, config)
        input_image_path: str | None = None

        image1 = form.get("image1")
        if image1 and hasattr(image1, "read"):
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            f.write(await image1.read())
            f.close()
            input_image_path = f.name

        provider = ImageProviderFactory.create_from_settings(settings, "gemini")
        req = ImageGenerationRequest(
            prompt=prompt,
            model=config.model or None,
            size=config.size or "1024x1024",
            negative_prompt=None,
            input_image_path=input_image_path,
            extra_params=None,
            temperature=config.temperature,
            seed=config.seed,
            image_size_tier=config.image_size_tier,
        )
        result = generate_with_retry(
            provider,
            req,
            settings,
            model_version=config.model or None,
            safety_settings_snapshot=getattr(settings, "gemini_safety_settings", None),
            streaming_enabled=False,
        )

        # Build data URL for frontend (image_url)
        b64 = base64.standard_b64encode(result.image_content).decode("ascii")
        mime = "image/png" if (config.format or "").lower() == "png" else "image/jpeg"
        image_url = f"data:{mime};base64,{b64}"
        if input_image_path:
            try:
                import os
                os.unlink(input_image_path)
            except Exception:
                pass
        return {"image_url": image_url}
    except ImageGenerationError as e:
        return {"error": str(e) or (e.detail.get("finish_message") if e.detail else "Generation failed")}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid config JSON: {e}"}
    except Exception as e:
        logger.exception("Playground test failed")
        return {"error": str(e)}
