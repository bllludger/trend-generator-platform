from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class Take(Base):
    __tablename__ = "takes"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    session_id = Column(String, nullable=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    take_type = Column(String, nullable=False, default="TREND")
    trend_id = Column(String, nullable=True)
    custom_prompt = Column(String, nullable=True)
    image_size = Column(String, nullable=True)
    input_file_ids = Column(JSONB, nullable=False, default=list)
    input_local_paths = Column(JSONB, nullable=False, default=list)
    copy_reference_path = Column(String, nullable=True)
    status = Column(String, nullable=False, default="generating")

    variant_a_preview = Column(String, nullable=True)
    variant_b_preview = Column(String, nullable=True)
    variant_c_preview = Column(String, nullable=True)
    variant_a_original = Column(String, nullable=True)
    variant_b_original = Column(String, nullable=True)
    variant_c_original = Column(String, nullable=True)

    seed_a = Column(Integer, nullable=True)
    seed_b = Column(Integer, nullable=True)
    seed_c = Column(Integer, nullable=True)

    error_code = Column(String, nullable=True)
    error_variants = Column(JSONB, nullable=True)

    # Outcome Collections
    step_index = Column(Integer, nullable=True)
    is_reroll = Column(Boolean, nullable=False, default=False)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
