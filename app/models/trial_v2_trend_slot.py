from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.db.base import Base


class TrialV2TrendSlot(Base):
    __tablename__ = "trial_v2_trend_slots"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, index=True)
    trend_id = Column(String, nullable=False, index=True)

    takes_count = Column(Integer, nullable=False, default=0)
    reroll_used = Column(Boolean, nullable=False, default=False)
    last_take_id = Column(String, nullable=True)

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

