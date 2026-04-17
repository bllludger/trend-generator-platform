import logging
import os
import time
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from prometheus_client import start_http_server

from face_id_app.callback import post_callback_with_retry
from face_id_app.celery_app import celery_app
from face_id_app.config import settings
from face_id_app.detector import process_asset
from face_id_app.metrics import (
    face_id_detected_faces_histogram,
    face_id_job_duration_seconds,
    face_id_jobs_total,
)

logger = logging.getLogger(__name__)

_METRICS_STARTED = False


def _ensure_metrics_server() -> None:
    global _METRICS_STARTED
    if _METRICS_STARTED:
        return
    try:
        start_http_server(int(os.environ.get("FACE_ID_WORKER_METRICS_PORT", settings.worker_metrics_port)))
        _METRICS_STARTED = True
    except Exception as exc:
        # Multi-process workers will compete for the same port; this is expected.
        if "Address already in use" in str(exc):
            _METRICS_STARTED = True
            return
        logger.exception("face_id_worker_metrics_start_failed")
        _METRICS_STARTED = True


def _cfg_value(detector_cfg: dict[str, Any], key: str, default: Any) -> Any:
    if key not in detector_cfg:
        return default
    return detector_cfg.get(key)


def _is_source_path_allowed(path: str) -> bool:
    base = os.path.realpath(settings.storage_base_path)
    candidate = os.path.realpath(path)
    return candidate == base or candidate.startswith(base + os.sep)


def _is_callback_url_allowed(callback_url: str) -> bool:
    parsed = urlparse(callback_url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    allowed = settings.callback_allowed_hosts_set()
    return host in allowed if allowed else False


@celery_app.task(name="face_id.process", bind=True)
def process_face_id(self, payload: dict[str, Any]) -> dict[str, Any]:
    _ensure_metrics_server()
    started = time.perf_counter()
    detector_cfg = payload.get("detector_config") if isinstance(payload.get("detector_config"), dict) else {}
    asset_id = str(payload.get("asset_id") or "").strip()
    callback_url = str(payload.get("callback_url") or "").strip()
    source_path = str(payload.get("source_path") or "").strip()

    if not asset_id:
        raise ValueError("asset_id is required")
    if not source_path:
        raise ValueError("source_path is required")
    if not callback_url:
        raise ValueError("callback_url is required")
    if not _is_source_path_allowed(source_path):
        raise ValueError("source_path outside storage_base_path")
    if not _is_callback_url_allowed(callback_url):
        raise ValueError("callback_url host is not allowed")

    try:
        result = process_asset(payload)
    except Exception as exc:
        logger.exception("face_id_process_failed", extra={"asset_id": asset_id})
        result = {
            "asset_id": asset_id,
            "status": "failed_error",
            "faces_detected": None,
            "selected_path": None,
            "source_path": source_path,
            "detector_meta": {
                "error": f"{exc.__class__.__name__}: {exc}",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "model_version": settings.model_version,
            },
        }

    status = str(result.get("status") or "failed_error")
    faces_detected_raw = result.get("faces_detected")
    try:
        observed_faces = float(int(faces_detected_raw)) if faces_detected_raw is not None else 0.0
    except (TypeError, ValueError):
        observed_faces = 0.0

    elapsed = time.perf_counter() - started
    face_id_detected_faces_histogram.observe(observed_faces)
    face_id_job_duration_seconds.observe(elapsed)
    face_id_jobs_total.labels(status=status).inc()

    callback_payload = {
        "asset_id": asset_id,
        "status": status,
        "faces_detected": result.get("faces_detected"),
        "selected_path": result.get("selected_path"),
        "source_path": result.get("source_path"),
        "detector_meta": result.get("detector_meta") or {},
        "event_id": str(uuid4()),
    }

    timeout = float(_cfg_value(detector_cfg, "callback_timeout_seconds", settings.callback_timeout_seconds))
    retries = int(_cfg_value(detector_cfg, "callback_max_retries", settings.callback_max_retries))
    backoff = float(_cfg_value(detector_cfg, "callback_backoff_seconds", settings.callback_backoff_seconds))
    post_callback_with_retry(
        callback_url=callback_url,
        payload=callback_payload,
        callback_secret=settings.resolve_callback_secret(payload.get("callback_secret_id")),
        timeout_seconds=timeout,
        max_retries=retries,
        backoff_seconds=backoff,
    )
    return callback_payload
