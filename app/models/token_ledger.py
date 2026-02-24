from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from app.db.base import Base


class TokenLedger(Base):
    __tablename__ = "token_ledger"
    __table_args__ = (UniqueConstraint("user_id", "job_id", "operation", name="uq_ledger_idempotency"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, index=True)
    job_id = Column(String, nullable=False, index=True)
    operation = Column(String, nullable=False)  # HOLD, CAPTURE, RELEASE
    amount = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
