import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


async def enqueue_face_id_processing(
    *,
    asset_id: str,
    source_path: str,
    flow: str,
    user_id: str,
    chat_id: str | None,
    request_id: str,
    detector_config: dict[str, Any],
) -> bool:
    base = (getattr(settings, "face_id_api_base", "") or "").strip().rstrip("/")
    if not base:
        return False
    callback_url = (getattr(settings, "face_id_callback_url", "") or "").strip()
    if not callback_url:
        return False
    payload = {
        "asset_id": asset_id,
        "source_path": source_path,
        "flow": flow,
        "user_id": user_id,
        "chat_id": chat_id,
        "request_id": request_id,
        "callback_url": callback_url,
        "callback_secret_id": getattr(settings, "face_id_callback_secret_id", "v1"),
        "detector_config": detector_config,
    }
    timeout = float(getattr(settings, "face_id_request_timeout_seconds", 1.5) or 1.5)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base}/v1/process", json=payload)
        if resp.status_code >= 300:
            logger.warning(
                "face_id_enqueue_http_error",
                extra={"status_code": resp.status_code, "asset_id": asset_id, "request_id": request_id},
            )
            return False
        return True
    except Exception as e:
        logger.warning("face_id_enqueue_failed", extra={"asset_id": asset_id, "request_id": request_id, "error": str(e)})
        return False

