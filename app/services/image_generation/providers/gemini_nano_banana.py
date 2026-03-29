"""
Gemini Nano Banana provider (Google AI generateContent image generation).
Uses generativelanguage.googleapis.com with api_key.
Per plan: 200 OK with empty content never silent-success; detail has normalized fields for runner.
"""
import base64
import copy
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

DEFAULT_TEMPERATURE = 1.0
DEFAULT_SEED = 42
MAX_PRODUCTION_TEMPERATURE = 1.0  # Прод-лимит: разрешаем отправлять до 1.0
# Official image ids: https://ai.google.dev/gemini-api/docs/image-generation
_GEMINI_3_PRO_IMAGE_PREVIEW = "gemini-3-pro-image-preview"  # Nano Banana Pro
_LEGACY_GEMINI_3_PRO_IMAGE_MODEL_ID = "gemini-3.1-pro-preview"  # deprecated; same as _GEMINI_3_PRO_IMAGE_PREVIEW

# Model -> max supported image size tier; use "2K" minimum when supported.
MODEL_MAX_IMAGE_TIER: dict[str, str] = {
    "gemini-2.5-flash-image": "4K",
    _GEMINI_3_PRO_IMAGE_PREVIEW: "4K",
    "gemini-3.1-flash-image-preview": "4K",  # Nano Banana 2
}
MODEL_MAX_CANDIDATE_COUNT: dict[str, int] = {
    "gemini-2.5-flash-image": 1,
    _GEMINI_3_PRO_IMAGE_PREVIEW: 4,
    "gemini-3.1-flash-image-preview": 1,
}
# ТЗ: imageSize только если модель поддерживает; gemini-2.5-flash-image может не поддерживать 2K — не отправляем imageSize.
MODELS_SUPPORTING_IMAGE_SIZE: frozenset[str] = frozenset({_GEMINI_3_PRO_IMAGE_PREVIEW, "gemini-3.1-flash-image-preview"})
SUPPORTED_MEDIA_RESOLUTION = frozenset({"LOW", "MEDIUM", "HIGH"})
MODELS_SUPPORTING_MEDIA_RESOLUTION: frozenset[str] = frozenset({_GEMINI_3_PRO_IMAGE_PREVIEW})
SUPPORTED_THINKING_LEVELS = frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH"})
MODEL_THINKING_LEVELS: dict[str, frozenset[str]] = {
    _GEMINI_3_PRO_IMAGE_PREVIEW: frozenset({"LOW", "HIGH"}),
    "gemini-3.1-flash-image-preview": frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH"}),
}
SUPPORTED_ASPECT_RATIOS = frozenset({
    "1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4",
    "9:16", "16:9", "21:9", "1:4", "4:1", "1:8", "8:1",
})


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


def _max_candidate_count_for_model(model: str) -> int:
    return MODEL_MAX_CANDIDATE_COUNT.get(_canonical_gemini_image_model_id(model), 1)


def _normalize_thinking_level(value: str | None) -> str | None:
    raw = (value or "").strip().upper()
    if not raw:
        return None
    if raw.startswith("THINKING_LEVEL_"):
        raw = raw.removeprefix("THINKING_LEVEL_")
    if raw in SUPPORTED_THINKING_LEVELS:
        return raw
    return None


def _canonical_gemini_image_model_id(model: str) -> str:
    if model == _LEGACY_GEMINI_3_PRO_IMAGE_MODEL_ID:
        return _GEMINI_3_PRO_IMAGE_PREVIEW
    return model


def _supported_thinking_levels_for_model(model: str) -> frozenset[str]:
    return MODEL_THINKING_LEVELS.get(_canonical_gemini_image_model_id(model), frozenset())


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
            _GEMINI_3_PRO_IMAGE_PREVIEW,
            "gemini-3.1-flash-image-preview",  # Nano Banana 2 (Preview)
        ]

    def supports_image_editing(self) -> bool:
        return True

    def _effective_image_size_tier(self, model: str, requested_tier: str | None) -> str:
        """Return imageSize tier: >= 2K when model supports 2K, else max tier for model."""
        tier_order = ("256", "512", "1K", "2K", "4K")
        max_tier = MODEL_MAX_IMAGE_TIER.get(_canonical_gemini_image_model_id(model), "2K")
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
        model = _canonical_gemini_image_model_id(model)

        temperature = request.temperature if request.temperature is not None else DEFAULT_TEMPERATURE
        temperature = max(0.0, min(2.0, float(temperature)))
        if not request.allow_high_temperature:
            temperature = min(temperature, MAX_PRODUCTION_TEMPERATURE)
        seed = request.seed if request.seed is not None else self.config.get("default_seed", DEFAULT_SEED)
        if not isinstance(seed, int):
            try:
                seed = int(seed)
            except (TypeError, ValueError):
                seed = DEFAULT_SEED

        parts: list[dict[str, Any]] = []
        prompt_text = request.prompt
        if request.negative_prompt:
            prompt_text += "\n\nAvoid: " + request.negative_prompt.strip()
        parts.append({"text": prompt_text})

        input_files = request.input_files if isinstance(request.input_files, list) else []
        if input_files:
            for item in input_files:
                path = (item or {}).get("path")
                mime_type = (item or {}).get("mime_type") or "image/jpeg"
                if not path or not Path(path).exists():
                    continue
                raw = Path(path).read_bytes()
                b64 = base64.standard_b64encode(raw).decode("ascii")
                parts.append({
                    "inlineData": {"mimeType": mime_type, "data": b64},
                })
        elif request.input_image_path and Path(request.input_image_path).exists():
            raw = Path(request.input_image_path).read_bytes()
            b64 = base64.standard_b64encode(raw).decode("ascii")
            parts.append({
                "inlineData": {"mimeType": "image/jpeg", "data": b64},
            })

        requested_aspect_ratio = (request.aspect_ratio or "").strip()
        if requested_aspect_ratio and requested_aspect_ratio in SUPPORTED_ASPECT_RATIOS:
            aspect_ratio = requested_aspect_ratio
        else:
            aspect_ratio = _size_to_aspect_ratio(request.size) if request.size else "1:1"
            if aspect_ratio not in SUPPORTED_ASPECT_RATIOS:
                aspect_ratio = "1:1"
        image_config: dict[str, Any] = {"aspectRatio": aspect_ratio}
        if model in MODELS_SUPPORTING_IMAGE_SIZE:
            image_size_tier = self._effective_image_size_tier(model, request.image_size_tier)
            if image_size_tier:
                image_config["imageSize"] = image_size_tier

        generation_config: dict[str, Any] = {
            "responseModalities": ["IMAGE"],
            "temperature": temperature,
            "seed": seed,
            "imageConfig": image_config,
        }
        if request.top_p is not None:
            top_p = max(0.0, min(1.0, float(request.top_p)))
            generation_config["topP"] = top_p
        if request.candidate_count is not None:
            candidate_count = max(1, min(_max_candidate_count_for_model(model), int(request.candidate_count)))
            generation_config["candidateCount"] = candidate_count
        media_resolution = _media_resolution_to_api_enum(request.media_resolution)
        if media_resolution and model in MODELS_SUPPORTING_MEDIA_RESOLUTION:
            generation_config["mediaResolution"] = media_resolution
        if isinstance(request.thinking_config, dict):
            cfg = dict(request.thinking_config)
            level = _normalize_thinking_level(cfg.get("thinking_level") or cfg.get("thinkingLevel"))
            budget = cfg.get("thinking_budget")
            if budget is None:
                budget = cfg.get("thinkingBudget")
            include_thoughts = cfg.get("include_thoughts")
            if include_thoughts is None:
                include_thoughts = cfg.get("includeThoughts")
            thinking_payload: dict[str, Any] = {}
            if level and level in _supported_thinking_levels_for_model(model):
                thinking_payload["thinkingLevel"] = level
            elif budget is not None:
                try:
                    thinking_payload["thinkingBudget"] = int(budget)
                except (TypeError, ValueError):
                    pass
            if isinstance(include_thoughts, bool):
                thinking_payload["includeThoughts"] = include_thoughts
            if thinking_payload:
                generation_config["thinkingConfig"] = thinking_payload

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
        }
        safety_settings = _parse_safety_settings(self.config.get("safety_settings"))
        if safety_settings:
            payload["safetySettings"] = safety_settings

        url = f"{self.base_url}/{model}:generateContent"
        params = {"key": self.api_key}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, params=params, json=payload)
                if resp.status_code == 400:
                    try:
                        err_body = resp.json()
                    except Exception:
                        err_body = {}
                    err_status = ((err_body.get("error") or {}).get("status") or "").upper()
                    if err_status == "INVALID_ARGUMENT":
                        retry_payload = copy.deepcopy(payload)
                        retry_cfg = retry_payload.get("generationConfig") or {}
                        retried = False
                        if "mediaResolution" in retry_cfg:
                            logger.info("retrying Gemini request without mediaResolution after INVALID_ARGUMENT")
                            retry_cfg.pop("mediaResolution", None)
                            retried = True
                        else:
                            thinking_cfg = retry_cfg.get("thinkingConfig") or {}
                            if "thinkingLevel" in thinking_cfg:
                                logger.info("retrying Gemini request without thinkingLevel after INVALID_ARGUMENT")
                                thinking_cfg.pop("thinkingLevel", None)
                                if thinking_cfg:
                                    retry_cfg["thinkingConfig"] = thinking_cfg
                                else:
                                    retry_cfg.pop("thinkingConfig", None)
                                retried = True
                        if retried:
                            retry_payload["generationConfig"] = retry_cfg
                            resp = client.post(url, params=params, json=retry_payload)
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

        image_b64s: list[str] = []
        non_stop_message: str | None = None
        for candidate in candidates:
            finish_reason = candidate.get("finishReason", "")
            if finish_reason and finish_reason != "STOP":
                if non_stop_message is None:
                    non_stop_message = candidate.get("finishMessage", finish_reason) or finish_reason
                continue
            content = candidate.get("content") or {}
            response_parts = content.get("parts") or []
            for part in response_parts:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and isinstance(inline.get("data"), str):
                    image_b64s.append(inline["data"])
                    break

        if not image_b64s:
            detail = build_gemini_error_detail(result)
            if non_stop_message:
                raise ImageGenerationError(non_stop_message, detail=detail)
            raise ImageGenerationError("No image in Gemini response", detail=detail)

        raw_response_sanitized = sanitize_gemini_response_for_log(result)
        content_bytes_list = [base64.standard_b64decode(item) for item in image_b64s]

        return ImageGenerationResponse(
            image_content=content_bytes_list[0],
            model=model,
            provider="gemini",
            image_b64=image_b64s[0],
            image_contents=content_bytes_list,
            image_b64s=image_b64s,
            raw_response_sanitized=raw_response_sanitized,
        )
