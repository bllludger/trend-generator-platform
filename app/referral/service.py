"""
ReferralService — attribution, bonus lifecycle, HD credits spend, anti-fraud.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.referral_bonus import ReferralBonus
from app.models.user import User
from app.referral.config import (
    calc_bonus_credits,
    get_attribution_window_days,
    get_daily_limit,
    get_hold_hours,
    get_min_pack_stars,
    get_monthly_limit,
)

logger = logging.getLogger(__name__)


class ReferralService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Referral code
    # ------------------------------------------------------------------

    def generate_referral_code(self) -> str:
        for _ in range(10):
            code = secrets.token_urlsafe(6)[:8]
            exists = self.db.query(User.id).filter(User.referral_code == code).first()
            if not exists:
                return code
        return secrets.token_urlsafe(8)[:10]

    def get_or_create_code(self, user: User) -> str:
        if user.referral_code:
            return user.referral_code
        code = self.generate_referral_code()
        user.referral_code = code
        self.db.add(user)
        self.db.flush()
        return code

    def get_referrer_by_code(self, code: str) -> User | None:
        return self.db.query(User).filter(User.referral_code == code).one_or_none()

    # ------------------------------------------------------------------
    # Attribution
    # ------------------------------------------------------------------

    def attribute(self, referral_user: User, referrer_code: str) -> bool:
        """
        Assign referrer to a new user. Idempotent — ignores if already attributed.
        Only works for users created within attribution_window_days.
        """
        if referral_user.referred_by_user_id:
            return False

        referrer = self.get_referrer_by_code(referrer_code)
        if not referrer:
            logger.warning("referral_code_not_found", extra={"code": referrer_code})
            return False

        if referrer.id == referral_user.id:
            return False

        window = timedelta(days=get_attribution_window_days())
        if referral_user.created_at and (
            datetime.now(timezone.utc) - referral_user.created_at.replace(tzinfo=timezone.utc)
            > window
        ):
            logger.info(
                "referral_attribution_expired",
                extra={"user_id": referral_user.id, "referrer_id": referrer.id},
            )
            return False

        referral_user.referred_by_user_id = referrer.id
        referral_user.referred_at = datetime.now(timezone.utc)
        self.db.add(referral_user)
        self.db.flush()

        logger.info(
            "referral_attributed",
            extra={
                "referral_user_id": referral_user.id,
                "referrer_user_id": referrer.id,
                "code": referrer_code,
            },
        )
        return True

    # ------------------------------------------------------------------
    # Bonus creation
    # ------------------------------------------------------------------

    def create_bonus(
        self, referrer: User, referral: User, payment: Payment
    ) -> ReferralBonus | None:
        """
        Create a pending bonus for the referrer after the referral's qualifying purchase.
        Returns None if purchase doesn't qualify or limits exceeded.
        """
        min_stars = get_min_pack_stars()
        if payment.stars_amount < min_stars:
            return None

        if payment.pack_id == "unlock":
            return None

        existing = (
            self.db.query(ReferralBonus)
            .filter(ReferralBonus.payment_id == payment.id)
            .first()
        )
        if existing:
            return existing

        if not self._check_limits(referrer):
            logger.warning(
                "referral_bonus_limit_reached",
                extra={"referrer_id": referrer.id},
            )
            return None

        credits = calc_bonus_credits(payment.stars_amount)
        if credits <= 0:
            return None

        if self.check_anomaly(referrer):
            logger.warning(
                "referral_flagged_for_review",
                extra={"referrer_id": referrer.id, "referral_id": referral.id},
            )
            return None

        hold_hours = get_hold_hours()
        now = datetime.now(timezone.utc)
        bonus = ReferralBonus(
            id=str(uuid4()),
            referrer_user_id=referrer.id,
            referral_user_id=referral.id,
            payment_id=payment.id,
            pack_stars=payment.stars_amount,
            hd_credits_amount=credits,
            status="pending",
            created_at=now,
            available_at=now + timedelta(hours=hold_hours),
        )
        self.db.add(bonus)

        referrer.hd_credits_pending += credits
        self.db.add(referrer)
        self.db.flush()

        logger.info(
            "referral_bonus_pending",
            extra={
                "bonus_id": bonus.id,
                "referrer_id": referrer.id,
                "referral_id": referral.id,
                "credits": credits,
                "available_at": bonus.available_at.isoformat(),
            },
        )
        return bonus

    # ------------------------------------------------------------------
    # Hold processing (called by Celery beat)
    # ------------------------------------------------------------------

    def process_pending(self) -> int:
        """Move hold-expired pending bonuses to available, credit hd_credits_balance."""
        now = datetime.now(timezone.utc)
        bonuses = (
            self.db.query(ReferralBonus)
            .filter(
                ReferralBonus.status == "pending",
                ReferralBonus.available_at <= now,
            )
            .all()
        )
        count = 0
        for bonus in bonuses:
            bonus.status = "available"
            self.db.add(bonus)

            referrer = (
                self.db.query(User)
                .filter(User.id == bonus.referrer_user_id)
                .with_for_update()
                .one_or_none()
            )
            if referrer:
                referrer.hd_credits_balance += bonus.hd_credits_amount
                referrer.hd_credits_pending = max(
                    0, referrer.hd_credits_pending - bonus.hd_credits_amount
                )
                self.db.add(referrer)

            self.db.flush()
            count += 1
            logger.info(
                "referral_bonus_available",
                extra={
                    "bonus_id": bonus.id,
                    "referrer_id": bonus.referrer_user_id,
                    "credits": bonus.hd_credits_amount,
                },
            )
        return count

    # ------------------------------------------------------------------
    # Spend HD credits
    # ------------------------------------------------------------------

    def spend_credits(self, user: User, amount: int) -> bool:
        """
        Debit HD credits from user balance. Blocked if debt > 0.
        Returns True on success.
        """
        if user.hd_credits_debt > 0:
            logger.info(
                "referral_spend_blocked_debt",
                extra={"user_id": user.id, "debt": user.hd_credits_debt},
            )
            return False

        locked = (
            self.db.query(User)
            .filter(User.id == user.id)
            .with_for_update()
            .one()
        )
        if locked.hd_credits_balance < amount:
            return False

        locked.hd_credits_balance -= amount
        self.db.add(locked)
        self.db.flush()

        logger.info(
            "referral_bonus_spent",
            extra={"user_id": user.id, "amount": amount, "new_balance": locked.hd_credits_balance},
        )
        return True

    # ------------------------------------------------------------------
    # Revoke bonus (on refund)
    # ------------------------------------------------------------------

    def revoke_bonus_by_payment(self, payment_id: str, reason: str = "refund") -> bool:
        """Revoke referral bonus linked to a payment. Creates debt if already spent."""
        bonus = (
            self.db.query(ReferralBonus)
            .filter(ReferralBonus.payment_id == payment_id)
            .one_or_none()
        )
        if not bonus or bonus.status == "revoked":
            return False

        referrer = (
            self.db.query(User)
            .filter(User.id == bonus.referrer_user_id)
            .with_for_update()
            .one_or_none()
        )
        if not referrer:
            return False

        old_status = bonus.status
        now = datetime.now(timezone.utc)
        bonus.status = "revoked"
        bonus.revoked_at = now
        bonus.revoke_reason = reason
        self.db.add(bonus)

        if old_status == "pending":
            referrer.hd_credits_pending = max(
                0, referrer.hd_credits_pending - bonus.hd_credits_amount
            )
        elif old_status == "available":
            referrer.hd_credits_balance = max(
                0, referrer.hd_credits_balance - bonus.hd_credits_amount
            )
        elif old_status == "spent":
            referrer.hd_credits_debt += bonus.hd_credits_amount

        self.db.add(referrer)
        self.db.flush()

        logger.info(
            "referral_bonus_revoked",
            extra={
                "bonus_id": bonus.id,
                "referrer_id": referrer.id,
                "old_status": old_status,
                "reason": reason,
                "credits": bonus.hd_credits_amount,
            },
        )
        return True

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_referral_stats(self, user_id: str) -> dict:
        """Get referral dashboard stats for a user."""
        attributed = (
            self.db.query(func.count(User.id))
            .filter(User.referred_by_user_id == user_id)
            .scalar()
            or 0
        )

        bought = (
            self.db.query(func.count(ReferralBonus.id))
            .filter(ReferralBonus.referrer_user_id == user_id)
            .scalar()
            or 0
        )

        user = self.db.query(User).filter(User.id == user_id).one_or_none()
        if not user:
            return {
                "attributed": 0,
                "bought": 0,
                "pending": 0,
                "available": 0,
                "spent": 0,
                "debt": 0,
            }

        spent_total = (
            self.db.query(func.coalesce(func.sum(ReferralBonus.hd_credits_amount), 0))
            .filter(
                ReferralBonus.referrer_user_id == user_id,
                ReferralBonus.status == "spent",
            )
            .scalar()
        )

        return {
            "attributed": attributed,
            "bought": bought,
            "pending": user.hd_credits_pending,
            "available": user.hd_credits_balance,
            "spent": spent_total,
            "debt": user.hd_credits_debt,
        }

    # ------------------------------------------------------------------
    # Anti-fraud
    # ------------------------------------------------------------------

    def check_anomaly(self, referrer: User) -> bool:
        """Flag referrer if bonus creation rate is anomalous."""
        now = datetime.now(timezone.utc)
        last_hour = now - timedelta(hours=1)
        recent = (
            self.db.query(func.count(ReferralBonus.id))
            .filter(
                ReferralBonus.referrer_user_id == referrer.id,
                ReferralBonus.created_at >= last_hour,
            )
            .scalar()
            or 0
        )
        if recent >= get_daily_limit():
            return True
        return False

    # ------------------------------------------------------------------
    # Limits
    # ------------------------------------------------------------------

    def _check_limits(self, referrer: User) -> bool:
        now = datetime.now(timezone.utc)

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily = (
            self.db.query(func.count(ReferralBonus.id))
            .filter(
                ReferralBonus.referrer_user_id == referrer.id,
                ReferralBonus.created_at >= today_start,
                ReferralBonus.status != "revoked",
            )
            .scalar()
            or 0
        )
        if daily >= get_daily_limit():
            return False

        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly = (
            self.db.query(func.count(ReferralBonus.id))
            .filter(
                ReferralBonus.referrer_user_id == referrer.id,
                ReferralBonus.created_at >= month_start,
                ReferralBonus.status != "revoked",
            )
            .scalar()
            or 0
        )
        if monthly >= get_monthly_limit():
            return False

        return True

    # ------------------------------------------------------------------
    # Admin: freeze bonus
    # ------------------------------------------------------------------

    def freeze_bonus(self, bonus_id: str) -> bool:
        """Move bonus back to pending for manual review."""
        bonus = self.db.query(ReferralBonus).filter(ReferralBonus.id == bonus_id).one_or_none()
        if not bonus or bonus.status not in ("pending", "available"):
            return False

        if bonus.status == "available":
            referrer = (
                self.db.query(User)
                .filter(User.id == bonus.referrer_user_id)
                .with_for_update()
                .one_or_none()
            )
            if referrer:
                referrer.hd_credits_balance = max(
                    0, referrer.hd_credits_balance - bonus.hd_credits_amount
                )
                referrer.hd_credits_pending += bonus.hd_credits_amount
                self.db.add(referrer)

        bonus.status = "pending"
        bonus.available_at = datetime.now(timezone.utc) + timedelta(days=365)
        self.db.add(bonus)
        self.db.flush()

        logger.info("referral_bonus_frozen", extra={"bonus_id": bonus_id})
        return True

    # ------------------------------------------------------------------
    # Mark bonus as spent (bookkeeping after HD credit usage)
    # ------------------------------------------------------------------

    def mark_oldest_available_spent(self, user_id: str, amount: int) -> None:
        """Mark the oldest available bonus as spent after user spends HD credits."""
        bonuses = (
            self.db.query(ReferralBonus)
            .filter(
                ReferralBonus.referrer_user_id == user_id,
                ReferralBonus.status == "available",
            )
            .order_by(ReferralBonus.available_at.asc())
            .all()
        )
        remaining = amount
        now = datetime.now(timezone.utc)
        for bonus in bonuses:
            if remaining <= 0:
                break
            if bonus.hd_credits_amount <= remaining:
                bonus.status = "spent"
                bonus.spent_at = now
                remaining -= bonus.hd_credits_amount
            else:
                break
            self.db.add(bonus)
        self.db.flush()
