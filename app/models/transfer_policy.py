"""Глобальная политика переноса личности. Одна запись (id=1)."""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP

from app.db.base import Base


class TransferPolicy(Base):
    __tablename__ = "transfer_policy"

    id = Column(Integer, primary_key=True, default=1)
    scope = Column(String(32), nullable=False, default="global", index=True)  # 'global' | 'trends'
    identity_lock_level = Column(String(64), nullable=False, default="strict")
    identity_rules_text = Column(Text, nullable=False, default="")
    composition_rules_text = Column(Text, nullable=False, default="")
    subject_reference_name = Column(String(32), nullable=False, default="IMAGE_1")
    avoid_default_items = Column(Text, nullable=False, default="")
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
