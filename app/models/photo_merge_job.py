from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class PhotoMergeJob(Base):
    """Запись об операции склейки фото пользователя."""

    __tablename__ = "photo_merge_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="pending", index=True)  # pending | processing | succeeded | failed
    input_paths = Column(JSONB, nullable=False, default=list)  # список локальных путей входных фото
    input_count = Column(Integer, nullable=False, default=0)
    output_path = Column(String, nullable=True)
    output_format = Column(String, nullable=False, default="png")
    input_bytes = Column(BigInteger, nullable=True)
    output_bytes = Column(BigInteger, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error_code = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
