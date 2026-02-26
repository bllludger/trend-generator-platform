import logging
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.models.favorite import Favorite

logger = logging.getLogger(__name__)


class FavoriteService:
    def __init__(self, db: DBSession):
        self.db = db

    def _check_favorites_cap(self, session_id: str) -> bool:
        """Enforce favorites cap based on session limits, not global user balance."""
        from app.models.session import Session as SessionModel
        from app.models.pack import Pack

        session = (
            self.db.query(SessionModel)
            .filter(SessionModel.id == session_id)
            .one_or_none()
        )
        if not session:
            return True

        pack = (
            self.db.query(Pack)
            .filter(Pack.id == session.pack_id)
            .one_or_none()
        )

        if pack and pack.favorites_cap:
            cap = pack.favorites_cap
        else:
            cap = min((session.hd_limit or 0) * 2, 30) if (session.hd_limit or 0) > 0 else 30

        current = self.count_favorites(session_id)
        return current < cap

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

        if session_id and not self._check_favorites_cap(session_id):
            logger.info(
                "favorites_cap_reached",
                extra={"session_id": session_id, "user_id": user_id},
            )
            return None

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

    # ── HD selection (Outcome Collections) ──────────────────────────

    def select_for_hd(self, favorite_id: str, session_id: str) -> bool:
        """Mark favorite as selected for HD delivery. Checks session.hd_limit."""
        from app.models.session import Session as SessionModel

        fav = self.get_favorite(favorite_id)
        if not fav:
            return False
        if fav.selected_for_hd:
            return True

        session = (
            self.db.query(SessionModel)
            .filter(SessionModel.id == session_id)
            .one_or_none()
        )
        if not session:
            return False

        selected_count = (
            self.db.query(Favorite)
            .filter(
                Favorite.session_id == session_id,
                Favorite.selected_for_hd.is_(True),
            )
            .count()
        )
        if selected_count >= (session.hd_limit or 0):
            return False

        fav.selected_for_hd = True
        self.db.add(fav)
        self.db.flush()
        return True

    def deselect_for_hd(self, favorite_id: str) -> bool:
        """Unmark HD selection (only if not yet delivered)."""
        fav = self.get_favorite(favorite_id)
        if not fav or fav.hd_status == "delivered":
            return False
        fav.selected_for_hd = False
        self.db.add(fav)
        self.db.flush()
        return True

    def list_selected_for_hd(self, session_id: str) -> list[Favorite]:
        """Return favorites marked for HD that haven't been delivered yet."""
        return (
            self.db.query(Favorite)
            .filter(
                Favorite.session_id == session_id,
                Favorite.selected_for_hd.is_(True),
                Favorite.hd_status == "none",
            )
            .order_by(Favorite.created_at)
            .all()
        )

    def count_selected_for_hd(self, session_id: str) -> int:
        return (
            self.db.query(Favorite)
            .filter(
                Favorite.session_id == session_id,
                Favorite.selected_for_hd.is_(True),
            )
            .count()
        )
