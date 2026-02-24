"""
LLM Runner: centralized generate-with-retry, failure classification, and observability.
Per plan: retry budget (max 1 retry), jitter, classify failures, mandatory logging.
Streaming fallback (plan §3.6): when streaming is used, on response-block one retry without
streaming can be added here (retry_without_streaming); current image path does not use streaming.
"""
import logging
import random
import time
from typing import Any

from app.services.image_generation.base import (
    ImageGenerationProvider,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ImageGenerationError,
)
from app.services.image_generation.failure_types import (
    FailureType,
    classify_failure,
)

logger = logging.getLogger(__name__)

# Keys for structured logging (plan §3.5, §3.7)
LOG_KEYS = (
    "model_version",
    "safety_settings",
    "finish_reason",
    "block_reason",
    "attempt_number",
    "success_after_retry",
    "streaming_enabled",
    "failure_type",
    "retry_allowed",
)


def generate_with_retry(
    provider: ImageGenerationProvider,
    request: ImageGenerationRequest,
    settings: Any,
    *,
    model_version: str | None = None,
    safety_settings_snapshot: Any = None,
    streaming_enabled: bool = False,
) -> ImageGenerationResponse:
    """
    Generate image with retry budget and classification per plan §3.2–3.5.
    At most one retry when classification allows (SAFETY/OTHER heuristic, or transport transient).
    """
    max_attempts = getattr(
        settings, "image_generation_retry_max_attempts", 2
    )
    backoff_seconds = getattr(
        settings, "image_generation_retry_backoff_seconds", 2.0
    )
    respect_retry_after = getattr(
        settings, "image_generation_retry_respect_retry_after", True
    )
    model_version = model_version or (request.model or getattr(provider, "model_name", ""))

    last_error: ImageGenerationError | None = None
    attempt = 0

    while attempt < max_attempts:
        attempt += 1
        try:
            result = provider.generate(request)
            # Success
            if attempt > 1:
                _log_structured(
                    model_version=model_version,
                    safety_settings=safety_settings_snapshot,
                    finish_reason=None,
                    block_reason=None,
                    attempt_number=attempt,
                    success_after_retry=True,
                    streaming_enabled=streaming_enabled,
                    failure_type=None,
                    retry_allowed=None,
                )
            return result
        except ImageGenerationError as e:
            last_error = e
            detail = e.detail or {}
            http_status = detail.get("http_status")
            failure_type, retry_allowed = classify_failure(
                http_status, detail, str(e)
            )
            detail["failure_type"] = failure_type.value

            _log_structured(
                model_version=model_version,
                safety_settings=safety_settings_snapshot,
                finish_reason=detail.get("finish_reason"),
                block_reason=detail.get("block_reason"),
                attempt_number=attempt,
                success_after_retry=False,
                streaming_enabled=streaming_enabled,
                failure_type=failure_type.value,
                retry_allowed=retry_allowed,
            )

            if not retry_allowed or attempt >= max_attempts:
                raise

            # Retry: sleep with jitter
            delay = backoff_seconds
            if http_status == 429 and respect_retry_after and detail.get("retry_after"):
                try:
                    delay = float(detail["retry_after"])
                except (TypeError, ValueError):
                    pass
            delay += random.uniform(0, 1)
            logger.info(
                "image_generation_retry_scheduled",
                extra={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "delay_seconds": round(delay, 2),
                    "failure_type": failure_type.value,
                },
            )
            time.sleep(delay)

    if last_error is not None:
        raise last_error
    raise RuntimeError("generate_with_retry: no result and no error")


def _log_structured(**kwargs: Any) -> None:
    """Emit one structured log line for observability (plan §3.5, §3.7)."""
    extra = {k: v for k, v in kwargs.items() if k in LOG_KEYS and v is not None}
    logger.info("image_generation_result", extra=extra)
