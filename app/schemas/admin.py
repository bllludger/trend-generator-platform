"""
Admin API schemas for extended functionality.
"""
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """Pagination parameters."""
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


class PaginatedResponse(BaseModel):
    """Paginated response wrapper."""
    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int


class JobDetailOut(BaseModel):
    """Extended job information."""
    job_id: str
    user_id: str
    telegram_id: str | None
    trend_id: str
    trend_name: str | None
    status: str
    reserved_tokens: int
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class UserListOut(BaseModel):
    """User list item."""
    id: str
    telegram_id: str
    telegram_username: str | None = None
    telegram_first_name: str | None = None
    telegram_last_name: str | None = None
    token_balance: int
    subscription_active: bool
    free_generations_used: int = 0
    free_generations_left: int = 3  # limit - used
    copy_generations_used: int = 0
    copy_generations_left: int = 1  # «Сделать такую же»
    created_at: datetime
    jobs_count: int = 0
    jobs_succeeded: int = 0
    jobs_failed: int = 0
    last_active: datetime | None = None


class AuditLogOut(BaseModel):
    """Audit log entry."""
    id: str
    actor_type: str
    actor_id: str | None
    actor_display_name: str | None = None  # @username or "Имя Фамилия" for users
    action: str
    entity_type: str
    entity_id: str | None
    payload: dict[str, Any]
    created_at: datetime


class JobFilterParams(BaseModel):
    """Job filtering parameters."""
    status: str | None = None
    trend_id: str | None = None
    user_id: str | None = None
    telegram_id: str | None = None
    error_code: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


class UserFilterParams(BaseModel):
    """User filtering parameters."""
    subscription_active: bool | None = None
    telegram_id: str | None = None
    min_balance: int | None = None
    max_balance: int | None = None
