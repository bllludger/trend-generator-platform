"""
Request ID middleware: sets request_id on request.state and adds X-Request-ID to response.
Enables end-to-end tracing in logs and support tools.
"""
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def _get_or_create_request_id(request: Request) -> str:
    """Use X-Request-ID from client if valid, otherwise generate new."""
    provided = request.headers.get("X-Request-ID", "").strip()
    if provided and len(provided) <= 128:
        return provided
    return str(uuid.uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = _get_or_create_request_id(request)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
