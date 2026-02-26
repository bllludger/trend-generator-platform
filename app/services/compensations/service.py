import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.compensation import CompensationLog
from app.models.favorite import Favorite
from app.models.pack import Pack
from app.models.session import Session
from app.services.sessions.service import SessionService

logger = logging.getLogger(__name__)


class CompensationService:
    def __init__(self, db: DBSession):
        self.db = db
        self.session_svc = SessionService(db)

    def check_and_compensate_hd_sla(self, favorite_id: str) -> bool:
        """Called by watchdog for stuck HD renders.
        Idempotent: skips if favorite.compensated_at is already set.
        Returns True if compensation was issued.
        """
        fav = self.db.query(Favorite).filter(Favorite.id == favorite_id).one_or_none()
        if not fav:
            return False
        if fav.compensated_at is not None:
            return False
        if fav.hd_status != "rendering":
            return False

        session = (
            self.db.query(Session).filter(Session.id == fav.session_id).one_or_none()
        )
        if not session:
            return False

        pack = self.db.query(Pack).filter(Pack.id == session.pack_id).one_or_none()
        sla_minutes = (pack.hd_sla_minutes if pack else None) or 10

        if not fav.updated_at:
            return False
        now = datetime.now(timezone.utc)
        elapsed = (now - fav.updated_at).total_seconds() / 60.0
        if elapsed < sla_minutes:
            return False

        fav.hd_status = "none"
        fav.compensated_at = now
        self.db.add(fav)

        self.session_svc.return_hd(session)

        log = CompensationLog(
            id=str(uuid4()),
            user_id=session.user_id,
            favorite_id=favorite_id,
            session_id=session.id,
            reason="hd_sla_breach",
            comp_type="hd_credit",
            amount=1,
            correlation_id=session.collection_run_id,
        )
        self.db.add(log)
        self.db.flush()

        logger.info(
            "compensation_sla_issued",
            extra={
                "favorite_id": favorite_id,
                "session_id": session.id,
                "elapsed_min": round(elapsed, 1),
                "sla_min": sla_minutes,
            },
        )
        return True

    def auto_compensate_on_fail(self, favorite_id: str) -> bool:
        """Called by deliver_hd on permanent failure.
        Idempotent: skips if favorite.compensated_at is already set.
        Returns True if compensation was issued.
        """
        fav = self.db.query(Favorite).filter(Favorite.id == favorite_id).one_or_none()
        if not fav:
            return False
        if fav.compensated_at is not None:
            return False

        session = (
            self.db.query(Session).filter(Session.id == fav.session_id).one_or_none()
        )
        if not session:
            return False

        now = datetime.now(timezone.utc)
        fav.compensated_at = now
        self.db.add(fav)

        self.session_svc.return_hd(session)

        log = CompensationLog(
            id=str(uuid4()),
            user_id=session.user_id,
            favorite_id=favorite_id,
            session_id=session.id,
            reason="hd_delivery_failed",
            comp_type="hd_credit",
            amount=1,
            correlation_id=session.collection_run_id,
        )
        self.db.add(log)
        self.db.flush()

        logger.info(
            "compensation_fail_issued",
            extra={"favorite_id": favorite_id, "session_id": session.id},
        )
        return True

    def report_hd_problem(
        self, user_id: str, favorite_id: str, collection_run_id: str | None = None
    ) -> CompensationLog:
        """User-initiated problem report. Creates log entry for manual review
        but does NOT auto-compensate."""
        log = CompensationLog(
            id=str(uuid4()),
            user_id=user_id,
            favorite_id=favorite_id,
            reason="user_report",
            comp_type="manual_review",
            amount=0,
            correlation_id=collection_run_id,
        )
        self.db.add(log)
        self.db.flush()
        logger.info(
            "hd_problem_reported",
            extra={"user_id": user_id, "favorite_id": favorite_id},
        )
        return log
