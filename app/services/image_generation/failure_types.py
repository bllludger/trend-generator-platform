"""
Formal failure normalization for LLM Runner (Gemini/Vertex).
Classifies API and transport failures for retry policy and observability.
"""
from enum import Enum
from typing import Any


class FailureType(str, Enum):
    """Formal failure types per plan §3.1."""

    TRANSPORT_TRANSIENT = "transport_transient"  # 429, 5xx, timeout
    PROMPT_BLOCKED = "prompt_blocked"  # promptFeedback.blockReason
    RESPONSE_BLOCKED = "response_blocked"  # SAFETY / OTHER (heuristic retry allowed)
    RESPONSE_BLOCKED_STRICT = "response_blocked_strict"  # BLOCKLIST / SPII / PROHIBITED_CONTENT
    CLIENT_NON_RETRIABLE = "client_non_retriable"  # 4xx except 429


# finishReason values that forbid retry (strict policy)
STRICT_FINISH_REASONS = frozenset({
    "BLOCKLIST",
    "SPII",
    "PROHIBITED_CONTENT",
    "RECITATION",
})

# finishReason values for which runner policy allows 1 retry (operational heuristic)
RETRYABLE_FINISH_REASONS = frozenset({
    "SAFETY",
    "OTHER",
})


def classify_failure(
    http_status: int | None,
    detail: dict[str, Any],
    message: str = "",
) -> tuple[FailureType, bool]:
    """
    Classify failure from HTTP status and Gemini-style detail.
    Returns (failure_type, retry_allowed) per plan §3.2.
    """
    # Transport: 429 or 5xx
    if http_status is not None:
        if http_status == 429:
            return (FailureType.TRANSPORT_TRANSIENT, True)
        if 500 <= http_status < 600:
            return (FailureType.TRANSPORT_TRANSIENT, True)
        if 400 <= http_status < 500:
            return (FailureType.CLIENT_NON_RETRIABLE, False)

    # Prompt-level block (no candidates)
    prompt_feedback = detail.get("prompt_feedback") or detail.get("promptFeedback") or {}
    if prompt_feedback.get("blockReason"):
        return (FailureType.PROMPT_BLOCKED, False)

    # Response-level: use finishReason from candidate
    finish_reason = (detail.get("finish_reason") or detail.get("finishReason") or "").strip().upper()
    if finish_reason in STRICT_FINISH_REASONS:
        return (FailureType.RESPONSE_BLOCKED_STRICT, False)
    if finish_reason in RETRYABLE_FINISH_REASONS:
        return (FailureType.RESPONSE_BLOCKED, True)

    # Other finishReason (e.g. RECITATION, MAX_TOKENS, or unknown): no retry
    if finish_reason and finish_reason != "STOP":
        return (FailureType.RESPONSE_BLOCKED_STRICT, False)

    # No clear finishReason (e.g. "No candidates", "No image in response")
    # Treat as response/execution failure, no retry
    if detail:
        return (FailureType.RESPONSE_BLOCKED, False)

    # No detail (e.g. network error, timeout): treat as transient, allow retry
    return (FailureType.TRANSPORT_TRANSIENT, True)
