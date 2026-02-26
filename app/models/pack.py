"""
Pack model — настраиваемые пакеты генераций для продажи за Telegram Stars.
Управляются из админки, порядок задаётся через order_index.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class Pack(Base):
    __tablename__ = "packs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String, nullable=False)
    emoji = Column(String, nullable=False, default="")
    tokens = Column(Integer, nullable=False, default=0)
    stars_price = Column(Integer, nullable=False)
    description = Column(String, nullable=False, default="")
    enabled = Column(Boolean, nullable=False, default=True)
    order_index = Column(Integer, nullable=False, default=0)

    # Session-based packs (MVP)
    takes_limit = Column(Integer, nullable=True)
    hd_amount = Column(Integer, nullable=True)
    is_trial = Column(Boolean, nullable=False, default=False)
    pack_type = Column(String, nullable=False, default="legacy")
    upgrade_target_pack_ids = Column(JSONB, nullable=True)

    # Outcome Collections
    pack_subtype = Column(String, nullable=False, default="standalone")
    playlist = Column(JSONB, nullable=True)
    favorites_cap = Column(Integer, nullable=True)
    collection_label = Column(String, nullable=True)
    upsell_pack_ids = Column(JSONB, nullable=True)
    hd_sla_minutes = Column(Integer, nullable=False, default=10)

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
