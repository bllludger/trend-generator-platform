from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, index=True)
    pack_id = Column(String, nullable=False)
    takes_limit = Column(Integer, nullable=False, default=0)
    takes_used = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="active")
    upgraded_from_session_id = Column(String, nullable=True)
    upgrade_credit_stars = Column(Integer, nullable=False, default=0)

    # Outcome Collections
    playlist = Column(JSONB, nullable=True)
    current_step = Column(Integer, nullable=False, default=0)
    hd_limit = Column(Integer, nullable=False, default=0)
    hd_used = Column(Integer, nullable=False, default=0)
    collection_run_id = Column(String, nullable=True)
    input_photo_path = Column(String, nullable=True)
    input_file_id = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
