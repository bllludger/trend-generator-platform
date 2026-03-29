from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.referral_trial_reward import ReferralTrialReward
from app.models.take import Take
from app.models.trial_v2_progress import TrialV2Progress
from app.models.trial_v2_selection import TrialV2Selection
from app.models.trial_v2_trend_slot import TrialV2TrendSlot
from app.models.user import User

TRIAL_SLOT_LIMIT = 3
TRIAL_SLOT_TAKES_LIMIT = 2  # first take + 1 reroll
TRIAL_REWARD_CAP = 10


class TrialV2Service:
    """Domain service for Trial V2 limits, selection queue, and referral unlock rewards."""

    def __init__(self, db: Session):
        self.db = db

    def is_trial_v2_user(self, user: User | None) -> bool:
        return bool(user and getattr(user, "trial_v2_eligible", False))

    def get_or_create_progress(self, user_id: str, *, for_update: bool = False) -> TrialV2Progress:
        q = self.db.query(TrialV2Progress).filter(TrialV2Progress.user_id == user_id)
        if for_update:
            q = q.with_for_update()
        row = q.one_or_none()
        if row:
            return row

        try:
            with self.db.begin_nested():
                row = TrialV2Progress(user_id=user_id)
                self.db.add(row)
                self.db.flush()
        except IntegrityError:
            # Race-safe: another transaction created progress row first.
            pass

        q = self.db.query(TrialV2Progress).filter(TrialV2Progress.user_id == user_id)
        if for_update:
            q = q.with_for_update()
        row = q.one_or_none()
        if row:
            return row

        row = TrialV2Progress(user_id=user_id)
        self.db.add(row)
        self.db.flush()
        return row

    def _get_slot(self, user_id: str, trend_id: str, *, for_update: bool = False) -> TrialV2TrendSlot | None:
        q = self.db.query(TrialV2TrendSlot).filter(
            TrialV2TrendSlot.user_id == user_id,
            TrialV2TrendSlot.trend_id == trend_id,
        )
        if for_update:
            q = q.with_for_update()
        return q.one_or_none()

    def can_start_take(self, user_id: str, trend_id: str) -> tuple[bool, str | None]:
        progress = self.get_or_create_progress(user_id)
        slot = self._get_slot(user_id, trend_id)
        if slot is None:
            if (progress.trend_slots_used or 0) >= TRIAL_SLOT_LIMIT:
                return False, "В Trial доступно только 3 уникальных образа."
            return True, None

        if (slot.takes_count or 0) >= TRIAL_SLOT_TAKES_LIMIT:
            return False, "Для этого образа Trial-лимит уже исчерпан."
        if bool(slot.reroll_used):
            return False, "Кнопка «Не подошло» для этого образа уже использована."
        return True, None

    def register_take_started(
        self,
        *,
        user_id: str,
        trend_id: str,
        take_id: str,
    ) -> tuple[bool, str | None, bool]:
        """
        Reserve Trial V2 capacity for a new take.
        Returns: (ok, error, used_reroll).
        """
        progress = self.get_or_create_progress(user_id, for_update=True)
        slot = self._get_slot(user_id, trend_id, for_update=True)
        used_reroll = False

        if slot is None:
            if (progress.trend_slots_used or 0) >= TRIAL_SLOT_LIMIT:
                return False, "В Trial доступно только 3 уникальных образа.", False
            slot = TrialV2TrendSlot(
                user_id=user_id,
                trend_id=trend_id,
                takes_count=1,
                reroll_used=False,
                last_take_id=take_id,
            )
            progress.trend_slots_used = (progress.trend_slots_used or 0) + 1
            self.db.add(slot)
        else:
            if (slot.takes_count or 0) >= TRIAL_SLOT_TAKES_LIMIT:
                return False, "Для этого образа Trial-лимит уже исчерпан.", False
            if bool(slot.reroll_used):
                return False, "Кнопка «Не подошло» для этого образа уже использована.", False
            used_reroll = True
            slot.takes_count = (slot.takes_count or 0) + 1
            slot.reroll_used = True
            slot.last_take_id = take_id
            progress.rerolls_used = (progress.rerolls_used or 0) + 1
            self.db.add(slot)

        progress.takes_used = (progress.takes_used or 0) + 1
        progress.updated_at = datetime.now(timezone.utc)
        self.db.add(progress)
        self.db.flush()
        return True, None, used_reroll

    def rollback_take_started(self, *, user_id: str, trend_id: str, take_id: str) -> bool:
        """
        Best-effort rollback for enqueue failures. Reverts only if take_id matches last slot take.
        """
        progress = self.get_or_create_progress(user_id, for_update=True)
        slot = self._get_slot(user_id, trend_id, for_update=True)
        if not slot or str(slot.last_take_id or "") != str(take_id):
            return False

        takes_count = max((slot.takes_count or 0) - 1, 0)
        slot.takes_count = takes_count
        slot.last_take_id = None
        if takes_count == 0:
            self.db.delete(slot)
            progress.trend_slots_used = max((progress.trend_slots_used or 0) - 1, 0)
        elif bool(slot.reroll_used):
            # We only rollback "last take"; for 2->1 rollback clear reroll flag.
            slot.reroll_used = False
            progress.rerolls_used = max((progress.rerolls_used or 0) - 1, 0)
            self.db.add(slot)
        progress.takes_used = max((progress.takes_used or 0) - 1, 0)
        progress.updated_at = datetime.now(timezone.utc)
        self.db.add(progress)
        self.db.flush()
        return True

    def enqueue_selection(
        self,
        *,
        user_id: str,
        take_id: str,
        variant: str,
        source: str = "trial_select",
    ) -> TrialV2Selection:
        v = (variant or "").strip().upper()
        existing = (
            self.db.query(TrialV2Selection)
            .filter(
                TrialV2Selection.user_id == user_id,
                TrialV2Selection.take_id == take_id,
                TrialV2Selection.variant == v,
                TrialV2Selection.status == "pending",
            )
            .first()
        )
        if existing:
            return existing

        try:
            with self.db.begin_nested():
                row = TrialV2Selection(
                    user_id=user_id,
                    take_id=take_id,
                    variant=v,
                    status="pending",
                    source=source,
                )
                self.db.add(row)
                self.db.flush()
                return row
        except IntegrityError:
            # Duplicate click/race on unique pending selection.
            pass

        existing = (
            self.db.query(TrialV2Selection)
            .filter(
                TrialV2Selection.user_id == user_id,
                TrialV2Selection.take_id == take_id,
                TrialV2Selection.variant == v,
                TrialV2Selection.status == "pending",
            )
            .first()
        )
        if existing:
            return existing
        raise RuntimeError("failed_to_enqueue_trial_selection")

    def get_oldest_pending_selection(self, user_id: str, *, for_update: bool = False) -> TrialV2Selection | None:
        q = (
            self.db.query(TrialV2Selection)
            .filter(
                TrialV2Selection.user_id == user_id,
                TrialV2Selection.status == "pending",
            )
            .order_by(TrialV2Selection.created_at.asc())
        )
        if for_update:
            q = q.with_for_update()
        return q.first()

    def mark_selection_claimed(self, selection: TrialV2Selection) -> None:
        selection.status = "claimed"
        selection.claimed_at = datetime.now(timezone.utc)
        self.db.add(selection)
        self.db.flush()

    def mark_selection_claiming(self, selection: TrialV2Selection) -> None:
        selection.status = "claiming"
        selection.claimed_at = None
        self.db.add(selection)
        self.db.flush()

    def award_referral_reward(self, *, referrer_user_id: str, referral_user_id: str) -> tuple[bool, int]:
        """
        Create unique reward event (1 referral account -> max 1 reward for specific referrer).
        Returns: (created, reward_available_after).
        """
        progress = self.get_or_create_progress(referrer_user_id, for_update=True)

        exists = (
            self.db.query(ReferralTrialReward.id)
            .filter(
                ReferralTrialReward.referrer_user_id == referrer_user_id,
                ReferralTrialReward.referral_user_id == referral_user_id,
            )
            .first()
        )
        if exists:
            return False, int(progress.reward_available or 0)

        if int(progress.reward_earned_total or 0) >= TRIAL_REWARD_CAP:
            return False, int(progress.reward_available or 0)

        try:
            with self.db.begin_nested():
                event = ReferralTrialReward(
                    referrer_user_id=referrer_user_id,
                    referral_user_id=referral_user_id,
                    reason="first_preview",
                )
                self.db.add(event)

                progress.reward_earned_total = int(progress.reward_earned_total or 0) + 1
                progress.reward_available = int(progress.reward_available or 0) + 1
                progress.updated_at = datetime.now(timezone.utc)
                self.db.add(progress)
                self.db.flush()
        except IntegrityError:
            self.db.refresh(progress)
            return False, int(progress.reward_available or 0)
        return True, int(progress.reward_available or 0)

    def process_first_successful_preview(self, referral_user_id: str) -> dict[str, Any] | None:
        """
        Mark referral user's first successful preview atomically and award referrer reward if applicable.
        Returns data for push notification when reward was created.
        """
        referral_user = (
            self.db.query(User)
            .filter(User.id == referral_user_id)
            .with_for_update()
            .one_or_none()
        )
        if not referral_user:
            return None
        if not bool(getattr(referral_user, "trial_v2_eligible", False)):
            return None
        if bool(getattr(referral_user, "trial_first_preview_completed", False)):
            return None

        referral_user.trial_first_preview_completed = True
        referral_user.trial_first_preview_completed_at = datetime.now(timezone.utc)
        self.db.add(referral_user)

        referrer_id = getattr(referral_user, "referred_by_user_id", None)
        if not referrer_id:
            self.db.flush()
            return None

        referrer = (
            self.db.query(User)
            .filter(User.id == referrer_id)
            .with_for_update()
            .one_or_none()
        )
        if not referrer or not bool(getattr(referrer, "trial_v2_eligible", False)):
            self.db.flush()
            return None

        created, reward_available = self.award_referral_reward(
            referrer_user_id=referrer_id,
            referral_user_id=referral_user.id,
        )
        if not created:
            self.db.flush()
            return None

        self.db.flush()
        if not referrer or not referrer.telegram_id:
            return None
        return {
            "referrer_user_id": referrer.id,
            "referrer_telegram_id": referrer.telegram_id,
            "reward_available": reward_available,
        }

    def claim_next_reward_selection(self, user_id: str) -> tuple[str, TrialV2Selection | None]:
        """
        Claim 1 available reward and bind it to oldest pending selection.
        Returns:
          - ("no_reward", None)
          - ("no_selection", None) -> reward preserved as reserve
          - ("ok", selection)
        """
        status, sel = self.reserve_next_reward_selection(user_id)
        if status != "ok" or not sel:
            return status, None
        if not self.finalize_reserved_claim(user_id=user_id, selection_id=sel.id):
            self.cancel_reserved_claim(user_id=user_id, selection_id=sel.id)
            return "no_selection", None
        return "ok", sel

    def reserve_next_reward_selection(self, user_id: str) -> tuple[str, TrialV2Selection | None]:
        """
        Reserve 1 reward + oldest pending selection for delivery attempt.
        Returns:
          - ("no_reward", None)
          - ("no_selection", None)
          - ("ok", selection_with_status_claiming)
        """
        progress = self.get_or_create_progress(user_id, for_update=True)
        if int(progress.reward_available or 0) < 1:
            return "no_reward", None

        sel = self.get_oldest_pending_selection(user_id, for_update=True)
        if not sel:
            progress.reward_reserved = max(
                int(progress.reward_reserved or 0),
                int(progress.reward_available or 0),
            )
            progress.updated_at = datetime.now(timezone.utc)
            self.db.add(progress)
            self.db.flush()
            return "no_selection", None

        progress.reward_available = max(int(progress.reward_available or 0) - 1, 0)
        progress.updated_at = datetime.now(timezone.utc)
        self.db.add(progress)
        self.mark_selection_claiming(sel)
        self.db.flush()
        return "ok", sel

    def finalize_reserved_claim(self, *, user_id: str, selection_id: str) -> bool:
        """
        Finalize a previously reserved selection after successful delivery.
        """
        progress = self.get_or_create_progress(user_id, for_update=True)
        sel = (
            self.db.query(TrialV2Selection)
            .filter(
                TrialV2Selection.id == selection_id,
                TrialV2Selection.user_id == user_id,
                TrialV2Selection.status == "claiming",
            )
            .with_for_update()
            .one_or_none()
        )
        if not sel:
            return False

        sel.status = "claimed"
        sel.claimed_at = datetime.now(timezone.utc)
        self.db.add(sel)

        progress.reward_claimed_total = int(progress.reward_claimed_total or 0) + 1
        if int(progress.reward_reserved or 0) > 0:
            progress.reward_reserved = int(progress.reward_reserved or 0) - 1
        progress.updated_at = datetime.now(timezone.utc)
        self.db.add(progress)
        self.db.flush()
        return True

    def cancel_reserved_claim(self, *, user_id: str, selection_id: str) -> bool:
        """
        Roll back reward reservation on delivery failure, preserving user balance.
        """
        progress = self.get_or_create_progress(user_id, for_update=True)
        sel = (
            self.db.query(TrialV2Selection)
            .filter(
                TrialV2Selection.id == selection_id,
                TrialV2Selection.user_id == user_id,
                TrialV2Selection.status == "claiming",
            )
            .with_for_update()
            .one_or_none()
        )
        if not sel:
            return False

        sel.status = "pending"
        sel.claimed_at = None
        self.db.add(sel)

        progress.reward_available = int(progress.reward_available or 0) + 1
        progress.updated_at = datetime.now(timezone.utc)
        self.db.add(progress)
        self.db.flush()
        return True

    def get_referral_unlock_stats(self, user_id: str) -> dict[str, int]:
        progress = self.get_or_create_progress(user_id)
        pending = (
            self.db.query(TrialV2Selection.id)
            .filter(
                TrialV2Selection.user_id == user_id,
                TrialV2Selection.status == "pending",
            )
            .count()
        )
        return {
            "reward_earned_total": int(progress.reward_earned_total or 0),
            "reward_claimed_total": int(progress.reward_claimed_total or 0),
            "reward_available": int(progress.reward_available or 0),
            "reward_reserved": int(progress.reward_reserved or 0),
            "pending_selections": int(pending or 0),
        }

    def get_trial_status(self, user_id: str) -> dict[str, int]:
        progress = self.get_or_create_progress(user_id)
        return {
            "trend_slots_used": int(progress.trend_slots_used or 0),
            "trend_slots_total": TRIAL_SLOT_LIMIT,
            "rerolls_used": int(progress.rerolls_used or 0),
            "rerolls_total": TRIAL_SLOT_LIMIT,
            "takes_used": int(progress.takes_used or 0),
            "takes_total": TRIAL_SLOT_LIMIT * TRIAL_SLOT_TAKES_LIMIT,
        }

    def list_available_variants_for_take(self, take: Take) -> list[str]:
        variants: list[str] = []
        if getattr(take, "variant_a_original", None):
            variants.append("A")
        if getattr(take, "variant_b_original", None):
            variants.append("B")
        if getattr(take, "variant_c_original", None):
            variants.append("C")
        return variants
