from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String

from app.db.base import Base


class CompensationLog(Base):
    __tablename__ = "compensation_log"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, index=True)
    favorite_id = Column(String, nullable=True)
    session_id = Column(String, nullable=True)
    reason = Column(String, nullable=False)
    comp_type = Column(String, nullable=False, default="hd_credit")
    amount = Column(Integer, nullable=False, default=1)
    correlation_id = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
