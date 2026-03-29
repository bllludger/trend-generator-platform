"""
Trial bundle order service: checkout for unlocking all 3 variants of a take for 129 ₽.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.take import Take
from app.models.trial_bundle_order import TrialBundleOrder
from app.services.takes.service import TakeService
from app.services.yookassa.client import YooKassaClient, YooKassaClientError

logger = logging.getLogger(__name__)

TRIAL_BUNDLE_AMOUNT_KOPECKS = 12900
TRIAL_BUNDLE_AMOUNT_VALUE = "129.00"


class TrialBundleOrderService:
    def __init__(self, db: DBSession):
        self.db = db

    def get_by_id(self, order_id: str) -> TrialBundleOrder | None:
        return self.db.query(TrialBundleOrder).filter(TrialBundleOrder.id == order_id).one_or_none()

    def get_by_yookassa_payment_id(self, payment_id: str) -> TrialBundleOrder | None:
        return (
            self.db.query(TrialBundleOrder)
            .filter(TrialBundleOrder.yookassa_payment_id == payment_id)
            .one_or_none()
        )

    def get_pending_order(self, telegram_user_id: str, take_id: str) -> TrialBundleOrder | None:
        return (
            self.db.query(TrialBundleOrder)
            .filter(
                TrialBundleOrder.telegram_user_id == telegram_user_id,
                TrialBundleOrder.take_id == take_id,
                TrialBundleOrder.status == "payment_pending",
            )
            .order_by(TrialBundleOrder.created_at.desc())
            .first()
        )

    def get_paid_or_delivered(self, telegram_user_id: str, take_id: str) -> TrialBundleOrder | None:
        return (
            self.db.query(TrialBundleOrder)
            .filter(
                TrialBundleOrder.telegram_user_id == telegram_user_id,
                TrialBundleOrder.take_id == take_id,
                TrialBundleOrder.status.in_(("paid", "delivered", "delivery_failed")),
            )
            .order_by(TrialBundleOrder.updated_at.desc())
            .first()
        )

    def _variants_for_take(self, take: Take) -> list[str]:
        out: list[str] = []
        if take.variant_a_original:
            out.append("A")
        if take.variant_b_original:
            out.append("B")
        if take.variant_c_original:
            out.append("C")
        return out

    def create_or_get_order(
        self,
        *,
        telegram_user_id: str,
        take_id: str,
    ) -> tuple[TrialBundleOrder | None, str | None]:
        pending = self.get_pending_order(telegram_user_id, take_id)
        if pending and pending.confirmation_url:
            return pending, pending.confirmation_url

        take = TakeService(self.db).get_take(take_id)
        if not take:
            return None, None
        variants = self._variants_for_take(take)
        if len(variants) != 3:
            return None, None

        order = TrialBundleOrder(
            id=str(uuid4()),
            telegram_user_id=telegram_user_id,
            take_id=take_id,
            variants=variants,
            amount_kopecks=TRIAL_BUNDLE_AMOUNT_KOPECKS,
            status="created",
        )
        self.db.add(order)
        self.db.flush()

        def _rollback_order() -> tuple[TrialBundleOrder | None, str | None]:
            try:
                self.db.delete(order)
                self.db.flush()
            except Exception:
                pass
            return None, None

        bot_username = (getattr(settings, "telegram_bot_username", "") or "").strip()
        if not bot_username:
            return _rollback_order()

        return_url = f"https://t.me/{bot_username}?start=trial_bundle_done_{order.id}"
        idempotence_key = str(uuid4())
        description = "Оплата Trial bundle · открыть все 3 фото"
        client = YooKassaClient()
        if not client.is_configured():
            return _rollback_order()
        try:
            result = client.create_payment(
                order_id=order.id,
                return_url=return_url,
                idempotence_key=idempotence_key,
                amount_value=TRIAL_BUNDLE_AMOUNT_VALUE,
                description=description,
            )
        except YooKassaClientError as e:
            logger.warning(
                "trial_bundle_create_payment_failed",
                extra={"order_id": order.id, "take_id": take_id, "error": str(e)},
            )
            return _rollback_order()

        conf = result.get("confirmation", {}) or {}
        confirmation_url = (conf.get("confirmation_url") or "").strip()
        yookassa_payment_id = (result.get("id") or "").strip()
        if not confirmation_url or not yookassa_payment_id:
            return _rollback_order()

        order.yookassa_payment_id = yookassa_payment_id
        order.confirmation_url = confirmation_url
        order.idempotence_key = idempotence_key
        order.status = "payment_pending"
        order.updated_at = datetime.now(timezone.utc)
        self.db.add(order)
        self.db.flush()
        return order, confirmation_url

    def mark_paid(self, *, order_id: str | None = None, yookassa_payment_id: str | None = None) -> TrialBundleOrder | None:
        if order_id:
            order = self.get_by_id(order_id)
        elif yookassa_payment_id:
            order = self.get_by_yookassa_payment_id(yookassa_payment_id)
        else:
            return None
        if not order or order.status not in ("created", "payment_pending"):
            return None
        order.status = "paid"
        order.updated_at = datetime.now(timezone.utc)
        self.db.add(order)
        self.db.flush()
        return order

    def mark_delivered(self, order_id: str) -> TrialBundleOrder | None:
        order = self.get_by_id(order_id)
        if not order or order.status not in ("paid", "delivery_failed"):
            return None
        order.status = "delivered"
        order.delivered_at = datetime.now(timezone.utc)
        order.updated_at = datetime.now(timezone.utc)
        self.db.add(order)
        self.db.flush()
        return order

    def mark_delivery_failed(self, order_id: str) -> TrialBundleOrder | None:
        order = self.get_by_id(order_id)
        if not order or order.status not in ("paid", "delivery_failed"):
            return None
        order.status = "delivery_failed"
        order.updated_at = datetime.now(timezone.utc)
        self.db.add(order)
        self.db.flush()
        return order

    def mark_canceled(self, *, order_id: str | None = None, yookassa_payment_id: str | None = None) -> TrialBundleOrder | None:
        if order_id:
            order = self.get_by_id(order_id)
        elif yookassa_payment_id:
            order = self.get_by_yookassa_payment_id(yookassa_payment_id)
        else:
            return None
        if not order or order.status not in ("created", "payment_pending"):
            return None
        order.status = "canceled"
        order.updated_at = datetime.now(timezone.utc)
        self.db.add(order)
        self.db.flush()
        return order
