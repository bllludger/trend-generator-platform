from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, String, UniqueConstraint

from app.db.base import Base


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "take_id", "variant", name="uq_favorites_user_take_variant"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    session_id = Column(String, nullable=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    take_id = Column(String, nullable=False, index=True)
    variant = Column(String, nullable=False)
    preview_path = Column(String, nullable=False)
    original_path = Column(String, nullable=False)
    hd_status = Column(String, nullable=False, default="none")
    hd_path = Column(String, nullable=True)
    hd_job_id = Column(String, nullable=True)

    # Outcome Collections: explicit HD selection + compensation idempotency
    selected_for_hd = Column(Boolean, nullable=False, default=False)
    compensated_at = Column(DateTime(timezone=True), nullable=True)
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
