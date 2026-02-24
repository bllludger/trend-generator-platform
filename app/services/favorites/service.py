import logging
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.models.favorite import Favorite

logger = logging.getLogger(__name__)


class FavoriteService:
    def __init__(self, db: DBSession):
        self.db = db

    def add_favorite(
        self,
        user_id: str,
        take_id: str,
        variant: str,
        preview_path: str,
        original_path: str,
        session_id: str | None = None,
    ) -> Favorite | None:
        """Idempotent add — returns existing on duplicate (UNIQUE constraint)."""
        existing = (
            self.db.query(Favorite)
            .filter(
                Favorite.user_id == user_id,
                Favorite.take_id == take_id,
                Favorite.variant == variant.upper(),
            )
            .one_or_none()
        )
        if existing:
            return existing

        fav = Favorite(
            id=str(uuid4()),
            session_id=session_id,
            user_id=user_id,
            take_id=take_id,
            variant=variant.upper(),
            preview_path=preview_path,
            original_path=original_path,
        )
        try:
            self.db.add(fav)
            self.db.flush()
            return fav
        except IntegrityError:
            self.db.rollback()
            return (
                self.db.query(Favorite)
                .filter(
                    Favorite.user_id == user_id,
                    Favorite.take_id == take_id,
                    Favorite.variant == variant.upper(),
                )
                .one_or_none()
            )

    def remove_favorite(self, favorite_id: str) -> bool:
        fav = self.db.query(Favorite).filter(Favorite.id == favorite_id).one_or_none()
        if not fav:
            return False
        if fav.hd_status == "delivered":
            return False
        self.db.delete(fav)
        self.db.flush()
        return True

    def list_favorites(self, session_id: str) -> list[Favorite]:
        return (
            self.db.query(Favorite)
            .filter(Favorite.session_id == session_id)
            .order_by(Favorite.created_at)
            .all()
        )

    def list_favorites_for_user(self, user_id: str) -> list[Favorite]:
        return (
            self.db.query(Favorite)
            .filter(Favorite.user_id == user_id)
            .order_by(Favorite.created_at)
            .all()
        )

    def count_favorites(self, session_id: str) -> int:
        return (
            self.db.query(Favorite)
            .filter(Favorite.session_id == session_id)
            .count()
        )

    def get_favorite(self, favorite_id: str) -> Favorite | None:
        return self.db.query(Favorite).filter(Favorite.id == favorite_id).one_or_none()

    def mark_rendering(self, favorite_id: str) -> bool:
        """Set hd_status='rendering'. Returns False if already rendering or delivered."""
        fav = self.get_favorite(favorite_id)
        if not fav or fav.hd_status in ("rendering", "delivered"):
            return False
        fav.hd_status = "rendering"
        self.db.add(fav)
        self.db.flush()
        return True

    def mark_hd_delivered(self, favorite_id: str, hd_path: str) -> bool:
        """Set hd_status='delivered'. Idempotent — returns True if already delivered."""
        fav = self.get_favorite(favorite_id)
        if not fav:
            return False
        if fav.hd_status == "delivered":
            return True
        fav.hd_status = "delivered"
        fav.hd_path = hd_path
        self.db.add(fav)
        self.db.flush()
        return True

    def reset_hd_status(self, favorite_id: str) -> None:
        """Reset hd_status to 'none' on failure."""
        fav = self.get_favorite(favorite_id)
        if fav and fav.hd_status != "delivered":
            fav.hd_status = "none"
            fav.hd_job_id = None
            self.db.add(fav)
            self.db.flush()

    def set_hd_job_id(self, favorite_id: str, job_id: str) -> None:
        fav = self.get_favorite(favorite_id)
        if fav:
            fav.hd_job_id = job_id
            self.db.add(fav)
            self.db.flush()
