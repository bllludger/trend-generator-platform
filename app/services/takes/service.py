import logging
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.take import Take

logger = logging.getLogger(__name__)


class TakeService:
    def __init__(self, db: DBSession):
        self.db = db

    def create_take(
        self,
        user_id: str,
        trend_id: str | None,
        take_type: str = "TREND",
        session_id: str | None = None,
        custom_prompt: str | None = None,
        image_size: str | None = None,
        input_file_ids: list[str] | None = None,
        input_local_paths: list[str] | None = None,
        copy_reference_path: str | None = None,
    ) -> Take:
        take = Take(
            id=str(uuid4()),
            session_id=session_id,
            user_id=user_id,
            take_type=take_type,
            trend_id=trend_id,
            custom_prompt=custom_prompt,
            image_size=image_size,
            input_file_ids=input_file_ids or [],
            input_local_paths=input_local_paths or [],
            copy_reference_path=copy_reference_path,
            status="generating",
        )
        self.db.add(take)
        self.db.flush()
        return take

    def set_variants(
        self,
        take: Take,
        *,
        preview_a: str | None = None,
        preview_b: str | None = None,
        preview_c: str | None = None,
        original_a: str | None = None,
        original_b: str | None = None,
        original_c: str | None = None,
        seed_a: int | None = None,
        seed_b: int | None = None,
        seed_c: int | None = None,
    ) -> None:
        if preview_a is not None:
            take.variant_a_preview = preview_a
        if preview_b is not None:
            take.variant_b_preview = preview_b
        if preview_c is not None:
            take.variant_c_preview = preview_c
        if original_a is not None:
            take.variant_a_original = original_a
        if original_b is not None:
            take.variant_b_original = original_b
        if original_c is not None:
            take.variant_c_original = original_c
        if seed_a is not None:
            take.seed_a = seed_a
        if seed_b is not None:
            take.seed_b = seed_b
        if seed_c is not None:
            take.seed_c = seed_c
        self.db.add(take)
        self.db.flush()

    def set_status(
        self,
        take: Take,
        status: str,
        error_code: str | None = None,
        error_variants: list[str] | None = None,
    ) -> None:
        take.status = status
        take.error_code = error_code
        take.error_variants = error_variants
        self.db.add(take)
        self.db.flush()

    def get_take(self, take_id: str) -> Take | None:
        return self.db.query(Take).filter(Take.id == take_id).one_or_none()

    def list_takes(self, session_id: str) -> list[Take]:
        return (
            self.db.query(Take)
            .filter(Take.session_id == session_id)
            .order_by(Take.created_at)
            .all()
        )

    def get_variant_paths(self, take: Take, variant: str) -> tuple[str | None, str | None]:
        """Return (preview_path, original_path) for the given variant letter."""
        v = variant.upper()
        if v == "A":
            return take.variant_a_preview, take.variant_a_original
        if v == "B":
            return take.variant_b_preview, take.variant_b_original
        if v == "C":
            return take.variant_c_preview, take.variant_c_original
        return None, None

    def get_seed(self, take: Take, variant: str) -> int | None:
        v = variant.upper()
        if v == "A":
            return take.seed_a
        if v == "B":
            return take.seed_b
        if v == "C":
            return take.seed_c
        return None
