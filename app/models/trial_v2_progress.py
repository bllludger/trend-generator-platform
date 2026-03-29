from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String

from app.db.base import Base


class TrialV2Progress(Base):
    __tablename__ = "trial_v2_progress"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, unique=True, index=True)

    trend_slots_used = Column(Integer, nullable=False, default=0)
    rerolls_used = Column(Integer, nullable=False, default=0)
    takes_used = Column(Integer, nullable=False, default=0)

    reward_earned_total = Column(Integer, nullable=False, default=0)
    reward_claimed_total = Column(Integer, nullable=False, default=0)
    reward_available = Column(Integer, nullable=False, default=0)
    reward_reserved = Column(Integer, nullable=False, default=0)

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

