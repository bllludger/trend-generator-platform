from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class Job(Base):
    __tablename__ = "jobs"

    job_id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, index=True)
    trend_id = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False)
    reserved_tokens = Column(Integer, nullable=False, default=0)
    used_free_quota = Column("used_free_daily_quota", Boolean, nullable=False, default=False)  # лимит на аккаунт (не ежедневный)
    used_copy_quota = Column(Boolean, nullable=False, default=False)  # «Сделать такую же» free slot
    error_code = Column(String, nullable=True)
    input_file_ids = Column(JSONB, nullable=False, default=list)
    input_local_paths = Column(JSONB, nullable=False, default=list)
    output_path = Column(String, nullable=True)
    output_path_original = Column(String, nullable=True)  # оригинал без watermark (для unlock)
    is_preview = Column(Boolean, nullable=False, default=False)  # True = фото с watermark
    # Источник истины оплаты/разблокировки (целевой; reserved_tokens — временная совместимость)
    unlocked_at = Column(DateTime, nullable=True)  # когда разблокировано
    unlock_method = Column(String, nullable=True)  # "tokens" | "stars"
    custom_prompt = Column(String, nullable=True)  # For "Своя идея" — user's text prompt
    image_size = Column(String, nullable=True)    # e.g. 1024x1024, 1024x576
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
