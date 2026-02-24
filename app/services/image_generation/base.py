"""
Base classes and types for image generation providers.
Used by factory and all providers (openai, huggingface, replicate, google_vertex, gemini).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImageGenerationRequest:
    """Request for image generation."""
    prompt: str
    model: str | None = None
    size: str | None = None
    negative_prompt: str | None = None
    input_image_path: str | None = None
    extra_params: dict[str, Any] | None = None
    temperature: float | None = None
    seed: int | None = None
    image_size_tier: str | None = None  # e.g. "1K", "2K" for Gemini imageConfig


@dataclass
class ImageGenerationResponse:
    """Response from image generation."""
    image_content: bytes
    model: str
    provider: str
    image_url: str | None = None
    image_b64: str | None = None
    raw_response_sanitized: dict[str, Any] | None = None


class ImageGenerationError(Exception):
    """Raised when generation fails; detail holds Gemini-specific fields for logging."""
    def __init__(self, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.detail = detail or {}


def build_gemini_error_detail(result: dict[str, Any]) -> dict[str, Any]:
    """
    Extract error-related fields from raw Gemini API response for logging.
    Used when raising ImageGenerationError so runner can classify and log.
    Normalized keys: prompt_feedback, block_reason, finish_reason, finish_message, safety_ratings.
    """
    detail: dict[str, Any] = {}
    if not result:
        return detail
    prompt_feedback = result.get("promptFeedback") or {}
    if prompt_feedback:
        detail["prompt_feedback"] = prompt_feedback
        if prompt_feedback.get("blockReason"):
            detail["block_reason"] = prompt_feedback.get("blockReason")
    candidates = result.get("candidates") or []
    if candidates:
        c0 = candidates[0]
        if "finishReason" in c0:
            detail["finish_reason"] = c0["finishReason"]
        if "finishMessage" in c0:
            detail["finish_message"] = c0["finishMessage"]
        if "safetyRatings" in c0:
            detail["safety_ratings"] = c0["safetyRatings"]
    return detail


def _sanitize_value(value: Any) -> Any:
    """Recursively replace base64 data with placeholder."""
    if value is None:
        return None
    if isinstance(value, dict):
        if "data" in value and "mimeType" in value:
            return {"mimeType": value.get("mimeType"), "data": "[REDACTED]"}
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    return value


def sanitize_gemini_response_for_log(result: dict[str, Any]) -> dict[str, Any]:
    """
    Return a copy of the Gemini response safe for logging (no base64 image data).
    Pass result to ImageGenerationResponse(..., raw_response_sanitized=...) for audit.
    """
    if not result:
        return {}
    out = _sanitize_value(result)
    return out if isinstance(out, dict) else {}


class ImageGenerationProvider(ABC):
    """Base class for image generation providers."""

    def __init__(self, config: dict) -> None:
        self.config = config

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is configured and available."""
        pass

    @abstractmethod
    def get_supported_models(self) -> list[str]:
        """Return list of supported model names."""
        pass

    def supports_image_editing(self) -> bool:
        """Override if provider supports image editing (input image + prompt)."""
        return False

    @abstractmethod
    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """Generate image from request. Raises ImageGenerationError or ValueError on failure."""
        pass
