"""
Celery periodic task: process pending referral bonuses whose hold has expired.
"""
import logging

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.referral.service import ReferralService
from app.services.telegram.client import TelegramClient

logger = logging.getLogger(__name__)


@celery_app.task(name="app.referral.tasks.process_pending_bonuses")
def process_pending_bonuses() -> dict:
    """Move hold-expired pending bonuses to available and notify referrers."""
    db = SessionLocal()
    try:
        svc = ReferralService(db)

        from app.models.referral_bonus import ReferralBonus
        from app.models.user import User
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        pending = (
            db.query(ReferralBonus)
            .filter(
                ReferralBonus.status == "pending",
                ReferralBonus.available_at <= now,
            )
            .all()
        )

        referrer_ids = {b.referrer_user_id for b in pending}

        processed = svc.process_pending()
        db.commit()

        if referrer_ids:
            telegram = TelegramClient()
            try:
                for referrer_id in referrer_ids:
                    referrer = db.query(User).filter(User.id == referrer_id).one_or_none()
                    if referrer and referrer.telegram_id:
                        try:
                            telegram.send_message(
                                referrer.telegram_id,
                                f"🎁 Бонус доступен: +HD credits на твоём балансе!\n"
                                f"Доступно: {referrer.hd_credits_balance} HD credits.\n"
                                f"Используй при разблокировке фото.",
                            )
                        except Exception:
                            logger.exception(
                                "referral_notify_available_fail",
                                extra={"referrer_id": referrer_id},
                            )
            finally:
                telegram.close()

        logger.info("process_pending_bonuses_done", extra={"processed": processed})
        return {"processed": processed}
    except Exception:
        db.rollback()
        logger.exception("process_pending_bonuses_error")
        return {"processed": 0, "error": "exception"}
    finally:
        db.close()
