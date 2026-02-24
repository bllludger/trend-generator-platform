"""
Gemini Nano Banana provider (Google AI generateContent image generation).
Uses generativelanguage.googleapis.com with api_key.
Per plan: 200 OK with empty content never silent-success; detail has normalized fields for runner.
"""
import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from app.services.image_generation.base import (
    ImageGenerationProvider,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ImageGenerationError,
    build_gemini_error_detail,
    sanitize_gemini_response_for_log,
)

logger = logging.getLogger(__name__)

DEFAULT_TEMPERATURE = 0.3
DEFAULT_SEED = 42
MAX_PRODUCTION_TEMPERATURE = 0.5  # ТЗ: temperature не выше 0.5 для image generation
# Model -> max supported image size tier; use "2K" minimum when supported.
MODEL_MAX_IMAGE_TIER: dict[str, str] = {
    "gemini-2.5-flash-image": "4K",
    "gemini-3-pro-image-preview": "4K",
}
# ТЗ: imageSize только если модель поддерживает; gemini-2.5-flash-image может не поддерживать 2K — не отправляем imageSize.
MODELS_SUPPORTING_IMAGE_SIZE: frozenset[str] = frozenset({"gemini-3-pro-image-preview"})


def _parse_safety_settings(value: Any) -> list[dict[str, Any]]:
    """Parse safety_settings from config (list of {category, threshold} or JSON string)."""
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _size_to_aspect_ratio(size: str | None) -> str:
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


class GeminiNanaBananaProvider(ImageGenerationProvider):
    """Gemini image generation via Google AI generateContent API."""

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.api_key = (config.get("api_key") or "").strip()
        self.project_id = config.get("project_id") or ""
        self.location = config.get("location", "us-central1")
        endpoint = (config.get("api_endpoint") or "https://generativelanguage.googleapis.com").rstrip("/")
        self.base_url = f"{endpoint}/v1beta/models"
        self.timeout = float(config.get("timeout", 120.0))
        self.model_name = (config.get("model") or "gemini-2.5-flash-image").strip()

    def is_available(self) -> bool:
        return bool(self.api_key)

    def get_supported_models(self) -> list[str]:
        return [
            "gemini-2.5-flash-image",
            "gemini-3-pro-image-preview",
        ]

    def supports_image_editing(self) -> bool:
        return True

    def _effective_image_size_tier(self, model: str, requested_tier: str | None) -> str:
        """Return imageSize tier: >= 2K when model supports 2K, else max tier for model."""
        tier_order = ("256", "512", "1K", "2K", "4K")
        max_tier = MODEL_MAX_IMAGE_TIER.get(model, "2K")
        max_idx = tier_order.index(max_tier) if max_tier in tier_order else 3
        min_idx = 3 if max_idx >= 3 else 0
        requested = (requested_tier or "").strip().upper() or "2K"
        req_idx = tier_order.index(requested) if requested in tier_order else 3
        use_idx = max(min_idx, min(req_idx, max_idx))
        return tier_order[use_idx]

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        if not self.is_available():
            raise ValueError("Gemini provider not configured (missing api_key)")

        if not (request.model or "").strip():
            logger.warning("model not set, using default: %s", self.model_name)
        model = (request.model or self.model_name).strip() or self.model_name
        if model != self.model_name:
            logger.info("model override: requested=%s, default=%s", model, self.model_name)

        temperature = request.temperature if request.temperature is not None else DEFAULT_TEMPERATURE
        temperature = max(0.0, min(2.0, float(temperature)))
        temperature = min(temperature, MAX_PRODUCTION_TEMPERATURE)
        seed = request.seed if request.seed is not None else self.config.get("default_seed", DEFAULT_SEED)
        if not isinstance(seed, int):
            try:
                seed = int(seed)
            except (TypeError, ValueError):
                seed = DEFAULT_SEED

        parts: list[dict] = []
        prompt_text = request.prompt
        if request.negative_prompt:
            prompt_text += "\n\nAvoid: " + request.negative_prompt.strip()
        parts.append({"text": prompt_text})

        if request.input_image_path and Path(request.input_image_path).exists():
            raw = Path(request.input_image_path).read_bytes()
            b64 = base64.standard_b64encode(raw).decode("ascii")
            parts.append({
                "inlineData": {"mimeType": "image/jpeg", "data": b64},
            })

        aspect_ratio = _size_to_aspect_ratio(request.size) if request.size else "1:1"
        image_config: dict[str, Any] = {"aspectRatio": aspect_ratio}
        if model in MODELS_SUPPORTING_IMAGE_SIZE:
            image_size_tier = self._effective_image_size_tier(model, request.image_size_tier)
            if image_size_tier:
                image_config["imageSize"] = image_size_tier

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "temperature": temperature,
                "seed": seed,
                "imageConfig": image_config,
            },
        }
        safety_settings = _parse_safety_settings(self.config.get("safety_settings"))
        if safety_settings:
            payload["safetySettings"] = safety_settings

        url = f"{self.base_url}/{model}:generateContent"
        params = {"key": self.api_key}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, params=params, json=payload)
                resp.raise_for_status()
                result = resp.json()
        except httpx.HTTPStatusError as e:
            try:
                err_body = e.response.json()
            except Exception:
                err_body = {}
            detail = build_gemini_error_detail(err_body)
            detail["http_status"] = e.response.status_code
            if e.response.status_code == 429:
                retry_after = e.response.headers.get("Retry-After")
                if retry_after is not None:
                    detail["retry_after"] = retry_after
            msg = err_body.get("error", {}).get("message", str(e))
            raise ImageGenerationError(msg, detail=detail) from e
        except Exception as e:
            raise ImageGenerationError(str(e), detail={}) from e

        # Block at request level (no candidates)
        prompt_feedback = result.get("promptFeedback", {})
        if prompt_feedback.get("blockReason"):
            detail = build_gemini_error_detail(result)
            msg = prompt_feedback.get("blockReason", "Request blocked")
            raise ImageGenerationError(msg, detail=detail)

        candidates = result.get("candidates") or []
        if not candidates:
            detail = build_gemini_error_detail(result)
            raise ImageGenerationError("No candidates in Gemini response", detail=detail)

        c0 = candidates[0]
        finish_reason = c0.get("finishReason", "")
        if finish_reason and finish_reason != "STOP":
            detail = build_gemini_error_detail(result)
            finish_message = c0.get("finishMessage", finish_reason)
            raise ImageGenerationError(finish_message or finish_reason, detail=detail)

        content = c0.get("content") or {}
        response_parts = content.get("parts") or []
        image_b64: str | None = None
        for part in response_parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and isinstance(inline.get("data"), str):
                image_b64 = inline["data"]
                break

        if not image_b64:
            detail = build_gemini_error_detail(result)
            raise ImageGenerationError("No image in Gemini response", detail=detail)

        raw_response_sanitized = sanitize_gemini_response_for_log(result)
        content_bytes = base64.standard_b64decode(image_b64)

        return ImageGenerationResponse(
            image_content=content_bytes,
            model=model,
            provider="gemini",
            image_b64=image_b64,
            raw_response_sanitized=raw_response_sanitized,
        )
