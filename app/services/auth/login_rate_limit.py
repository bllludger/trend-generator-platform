"""
Rate limiter for admin login to prevent brute-force attacks.
"""
import logging

import redis
from starlette.requests import Request

from app.core.config import settings

logger = logging.getLogger("auth")


def get_client_ip(request: Request) -> str:
    """Client IP (supports X-Forwarded-For from proxy)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded and settings.app_env == "production":
        trusted = settings.trusted_proxy_ips_set
        if trusted and request.client and request.client.host in trusted:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def check_login_rate_limit(client_ip: str) -> bool:
    """
    Check if login attempt is allowed. Returns True if allowed, False if rate limited.
    Increments counter on each call.
    """
    try:
        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        key = f"login_attempts:{client_ip}"
        current = client.incr(key)
        if current == 1:
            client.expire(key, settings.login_rate_limit_window_seconds)
        if current > settings.login_rate_limit_attempts:
            logger.warning("login_rate_limited", extra={"ip": client_ip, "attempts": current})
            return False
        return True
    except redis.RedisError as e:
        logger.warning("login_rate_limit_redis_error", extra={"error": str(e)})
        return True  # Fail open - allow login if Redis is down


def reset_login_attempts(client_ip: str) -> None:
    """Reset counter on successful login."""
    try:
        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        client.delete(f"login_attempts:{client_ip}")
    except redis.RedisError:
        pass
