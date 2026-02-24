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
        session = Session(
            id=str(uuid4()),
            user_id=user_id,
            pack_id=pack_id,
            takes_limit=pack.takes_limit or 0,
            takes_used=0,
            status="active",
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
