from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, String

from app.db.base import Base


class TrialV2Selection(Base):
    __tablename__ = "trial_v2_selections"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, index=True)
    take_id = Column(String, nullable=False, index=True)
    variant = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    source = Column(String, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    claimed_at = Column(DateTime(timezone=True), nullable=True)

