import json
import time
from typing import Any

import httpx

from face_id_app.signature import build_signature


def post_callback_with_retry(
    *,
    callback_url: str,
    payload: dict[str, Any],
    callback_secret: str,
    timeout_seconds: float,
    max_retries: int,
    backoff_seconds: float,
) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    attempts = max(0, int(max_retries)) + 1
    timeout = max(0.1, float(timeout_seconds))
    backoff = max(0.0, float(backoff_seconds))

    last_error: Exception | None = None
    for attempt in range(attempts):
        ts = str(int(time.time()))
        sig = build_signature(callback_secret, ts, body)
        headers = {
            "Content-Type": "application/json",
            "X-FaceId-Timestamp": ts,
            "X-FaceId-Signature": sig,
        }
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(callback_url, headers=headers, content=body)
            if 200 <= resp.status_code < 300:
                return
            raise RuntimeError(f"callback http status {resp.status_code}")
        except Exception as exc:  # noqa: PERF203
            last_error = exc
            if attempt < attempts - 1:
                sleep_s = backoff * (2 ** attempt)
                if sleep_s > 0:
                    time.sleep(sleep_s)
    if last_error:
        raise last_error
