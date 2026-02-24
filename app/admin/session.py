from typing import Optional
from uuid import UUID, uuid4

import redis
from fastapi import Request
from fastapi_sessions.backends.session_backend import SessionBackend
from fastapi_sessions.frontends.implementations import SessionCookie, CookieParameters
from pydantic import BaseModel

from app.core.config import settings


class AdminSessionData(BaseModel):
    username: str


class RedisSessionBackend(SessionBackend[UUID, AdminSessionData]):
    def __init__(self) -> None:
        self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.ttl_seconds = settings.admin_ui_session_ttl
        self.key_prefix = "admin-session:"

    async def create(self, session_id: UUID, data: AdminSessionData) -> None:
        self.client.setex(
            f"{self.key_prefix}{session_id}",
            self.ttl_seconds,
            data.model_dump_json(),
        )

    async def read(self, session_id: UUID) -> Optional[AdminSessionData]:
        raw = self.client.get(f"{self.key_prefix}{session_id}")
        if not raw:
            return None
        return AdminSessionData.model_validate_json(raw)

    async def update(self, session_id: UUID, data: AdminSessionData) -> None:
        await self.create(session_id, data)

    async def delete(self, session_id: UUID) -> None:
        self.client.delete(f"{self.key_prefix}{session_id}")


session_backend = RedisSessionBackend()

cookie_params = CookieParameters(
    max_age=settings.admin_ui_session_ttl,
    samesite=settings.admin_ui_cookie_samesite,
    secure=settings.admin_ui_cookie_secure,
)

session_cookie = SessionCookie(
    cookie_name="admin_session",
    identifier="admin_session",
    auto_error=False,
    secret_key=settings.admin_ui_session_secret,
    cookie_params=cookie_params,
)


async def get_session_id(request: Request) -> Optional[UUID]:
    return await session_cookie(request)


async def require_admin_session(request: Request) -> Optional[AdminSessionData]:
    session_id = await get_session_id(request)
    if not session_id:
        return None
    return await session_backend.read(session_id)


async def create_admin_session(username: str) -> UUID:
    session_id = uuid4()
    await session_backend.create(session_id, AdminSessionData(username=username))
    return session_id
