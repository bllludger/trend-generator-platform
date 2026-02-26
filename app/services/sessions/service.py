import logging
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session as DBSession

from app.models.pack import Pack
from app.models.session import Session
from app.models.take import Take

logger = logging.getLogger(__name__)


class SessionService:
    def __init__(self, db: DBSession):
        self.db = db

    def create_session(self, user_id: str, pack_id: str) -> Session:
        pack = self.db.query(Pack).filter(Pack.id == pack_id).one_or_none()
        if not pack:
            raise ValueError(f"Pack not found: {pack_id}")
        if getattr(pack, "pack_subtype", "standalone") == "collection":
            raise ValueError(
                "Use create_collection_session for collection packs"
            )
        session = Session(
            id=str(uuid4()),
            user_id=user_id,
            pack_id=pack_id,
            takes_limit=pack.takes_limit or 0,
            takes_used=0,
            status="active",
            hd_limit=pack.hd_amount or 0,
        )
        self.db.add(session)
        self.db.flush()
        return session

    def create_collection_session(
        self,
        user_id: str,
        pack: Pack,
        input_photo_path: str | None = None,
        input_file_id: str | None = None,
    ) -> Session:
        playlist = pack.playlist
        if not playlist or not isinstance(playlist, list) or len(playlist) == 0:
            raise ValueError(
                f"Collection pack {pack.id} has no playlist — cannot create session"
            )
        session = Session(
            id=str(uuid4()),
            user_id=user_id,
            pack_id=pack.id,
            takes_limit=pack.takes_limit or len(playlist),
            takes_used=0,
            status="active",
            playlist=list(playlist),
            current_step=0,
            hd_limit=pack.hd_amount or 0,
            hd_used=0,
            collection_run_id=str(uuid4()),
            input_photo_path=input_photo_path,
            input_file_id=input_file_id,
        )
        self.db.add(session)
        self.db.flush()
        return session

    def create_free_preview_session(self, user_id: str) -> Session:
        session = Session(
            id=str(uuid4()),
            user_id=user_id,
            pack_id="free_preview",
            takes_limit=1,
            takes_used=0,
            status="active",
        )
        self.db.add(session)
        self.db.flush()
        return session

    def get_active_session(self, user_id: str) -> Session | None:
        return (
            self.db.query(Session)
            .filter(Session.user_id == user_id, Session.status == "active")
            .order_by(Session.created_at.desc())
            .first()
        )

    def get_session(self, session_id: str) -> Session | None:
        return self.db.query(Session).filter(Session.id == session_id).one_or_none()

    def can_take(self, session: Session) -> bool:
        return session.takes_used < session.takes_limit

    def use_take(self, session: Session) -> bool:
        """Atomically increment takes_used. Returns False if limit reached."""
        result = self.db.execute(
            update(Session)
            .where(Session.id == session.id, Session.takes_used < Session.takes_limit)
            .values(takes_used=Session.takes_used + 1)
        )
        self.db.flush()
        if result.rowcount > 0:
            self.db.refresh(session)
            return True
        return False

    def return_take(self, session: Session) -> None:
        """Return a take on failure (decrement takes_used, floor at 0)."""
        result = self.db.execute(
            update(Session)
            .where(Session.id == session.id, Session.takes_used > 0)
            .values(takes_used=Session.takes_used - 1)
        )
        self.db.flush()
        if result.rowcount > 0:
            self.db.refresh(session)

    def complete_session(self, session: Session) -> None:
        session.status = "completed"
        self.db.add(session)
        self.db.flush()

    def upgrade_session(
        self, old_session: Session, new_pack_id: str, credit_stars: int
    ) -> Session:
        old_session.status = "upgraded"
        self.db.add(old_session)

        pack = self.db.query(Pack).filter(Pack.id == new_pack_id).one_or_none()
        if not pack:
            raise ValueError(f"Pack not found: {new_pack_id}")

        new_session = Session(
            id=str(uuid4()),
            user_id=old_session.user_id,
            pack_id=new_pack_id,
            takes_limit=pack.takes_limit or 0,
            takes_used=0,
            status="active",
            upgraded_from_session_id=old_session.id,
            upgrade_credit_stars=credit_stars,
        )
        self.db.add(new_session)
        self.db.flush()

        # Re-link takes from old session to new session
        self.db.execute(
            update(Take)
            .where(Take.session_id == old_session.id)
            .values(session_id=new_session.id)
        )
        self.db.flush()

        return new_session

    def attach_take_to_session(self, take: Take, session: Session) -> None:
        take.session_id = session.id
        self.db.add(take)
        self.db.flush()

    # ── Collection helpers ──────────────────────────────────────────

    def is_collection(self, session: Session) -> bool:
        pl = session.playlist
        return pl is not None and isinstance(pl, list) and len(pl) > 0

    def get_next_trend_id(self, session: Session) -> str | None:
        if not self.is_collection(session):
            return None
        step = session.current_step or 0
        if step < len(session.playlist):
            return session.playlist[step]
        return None

    def advance_step(self, session: Session) -> bool:
        """Atomically increment current_step. Returns False if playlist exhausted."""
        if not self.is_collection(session):
            return False
        playlist_len = len(session.playlist)
        result = self.db.execute(
            update(Session)
            .where(Session.id == session.id, Session.current_step < playlist_len)
            .values(current_step=Session.current_step + 1)
        )
        self.db.flush()
        if result.rowcount > 0:
            self.db.refresh(session)
            return True
        return False

    def hd_remaining(self, session: Session) -> int:
        return max((session.hd_limit or 0) - (session.hd_used or 0), 0)

    def use_hd(self, session: Session) -> bool:
        """Atomically increment hd_used. Returns False if limit reached."""
        result = self.db.execute(
            update(Session)
            .where(Session.id == session.id, Session.hd_used < Session.hd_limit)
            .values(hd_used=Session.hd_used + 1)
        )
        self.db.flush()
        if result.rowcount > 0:
            self.db.refresh(session)
            return True
        return False

    def return_hd(self, session: Session) -> None:
        """Return an HD credit on failure/compensation (floor at 0)."""
        result = self.db.execute(
            update(Session)
            .where(Session.id == session.id, Session.hd_used > 0)
            .values(hd_used=Session.hd_used - 1)
        )
        self.db.flush()
        if result.rowcount > 0:
            self.db.refresh(session)

    def set_input_photo(
        self, session: Session, photo_path: str, file_id: str
    ) -> None:
        session.input_photo_path = photo_path
        session.input_file_id = file_id
        self.db.add(session)
        self.db.flush()
