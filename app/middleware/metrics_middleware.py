"""
HTTP metrics middleware: request count and duration for Prometheus.
Normalizes path to limit cardinality (replaces UUIDs and numeric IDs).
"""
import logging
import re
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.utils.metrics import (
    http_requests_total,
    http_request_duration_seconds,
    admin_api_requests_total,
)

logger = logging.getLogger(__name__)

# Path segments that look like UUIDs or numeric IDs get replaced
UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
NUMERIC_ID_PATTERN = re.compile(r"^[0-9]+$")
# Long hex/alpha strings (e.g. job_id, take_id)
LONG_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{20,}$")


def _normalize_path(path: str) -> str:
    """Replace high-cardinality segments with placeholders."""
    if not path or path == "/":
        return "/"
    parts = path.strip("/").split("/")
    normalized = []
    for p in parts:
        if not p:
            continue
        if UUID_PATTERN.fullmatch(p):
            normalized.append("{uuid}")
        elif NUMERIC_ID_PATTERN.fullmatch(p):
            normalized.append("{id}")
        elif LONG_ID_PATTERN.fullmatch(p):
            normalized.append("{id}")
        else:
            normalized.append(p)
    return "/" + "/".join(normalized) if normalized else "/"


def _status_class(status_code: int) -> str:
    """Return status class for lower cardinality (e.g. 2xx, 5xx)."""
    if status_code < 200:
        return "1xx"
    if status_code < 300:
        return "2xx"
    if status_code < 400:
        return "3xx"
    if status_code < 500:
        return "4xx"
    return "5xx"


class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        method = request.method
        path = _normalize_path(request.url.path)
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        status = response.status_code
        status_class = _status_class(status)

        try:
            http_requests_total.labels(
                method=method,
                path=path,
                status=status_class,
            ).inc()
            http_request_duration_seconds.labels(
                method=method,
                path=path,
            ).observe(duration)
            if request.url.path.startswith("/admin/") and not request.url.path.startswith(
                "/admin-ui"
            ):
                admin_api_requests_total.labels(
                    path=path,
                    status=status_class,
                ).inc()
        except Exception as e:
            logger.warning("http_metrics_record_failed", extra={"path": path, "error": str(e)})

        return response
