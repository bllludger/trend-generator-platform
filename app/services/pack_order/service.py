"""
PackOrder service: создание и обработка заказов на пакет по ссылке ЮKassa.
"""
import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.pack_order import PackOrder
from app.services.payments.service import PaymentService
from app.services.yookassa.client import YooKassaClient, YooKassaClientError

logger = logging.getLogger(__name__)

PACK_ORDER_PACK_IDS = ("neo_start", "neo_pro", "neo_unlimited")

# Цены в рублях (DISPLAY_RUB из balance_tariffs)
PACK_AMOUNT_RUB = {
    "neo_start": 199,
    "neo_pro": 699,
    "neo_unlimited": 1990,
}


def _pack_description(pack_id: str, pack) -> str:
    """Описание платежа для ЮKassa (до 128 символов)."""
    if not pack:
        return f"Оплата пакета {pack_id}"
    name = getattr(pack, "name", pack_id)
    emoji = getattr(pack, "emoji", "")
    takes = getattr(pack, "takes_limit", 0) or 0
    label = f"{emoji} {name}".strip() or pack_id
    return f"Оплата пакета {label} · {takes} фото"[:128]


class PackOrderService:
    def __init__(self, db: DBSession):
        self.db = db

    def get_by_id(self, order_id: str) -> PackOrder | None:
        return self.db.query(PackOrder).filter(PackOrder.id == order_id).one_or_none()

    def get_by_yookassa_payment_id(self, yookassa_payment_id: str) -> PackOrder | None:
        return (
            self.db.query(PackOrder)
            .filter(PackOrder.yookassa_payment_id == yookassa_payment_id)
            .one_or_none()
        )

    def get_pending_order(
        self,
        telegram_user_id: str,
        pack_id: str,
    ) -> PackOrder | None:
        """Активный заказ в статусе payment_pending на связку (для повторного показа ссылки)."""
        return (
            self.db.query(PackOrder)
            .filter(
                PackOrder.telegram_user_id == telegram_user_id,
                PackOrder.pack_id == pack_id,
                PackOrder.status == "payment_pending",
            )
            .order_by(PackOrder.created_at.desc())
            .first()
        )

    def create_order(
        self,
        telegram_user_id: str,
        pack_id: str,
        bot_username: str,
    ) -> tuple[PackOrder | None, str | None]:
        """
        Создать PackOrder и платёж в ЮKassa. Возвращает (order, confirmation_url) или (None, None) при ошибке.
        """
        if pack_id not in PACK_ORDER_PACK_IDS or pack_id not in PACK_AMOUNT_RUB:
            return None, None
        amount_rub = PACK_AMOUNT_RUB[pack_id]
        amount_kopecks = amount_rub * 100
        amount_value = f"{amount_rub}.00"

        payment_service = PaymentService(self.db)
        pack = payment_service.get_pack(pack_id)
        description = _pack_description(pack_id, pack)

        order = PackOrder(
            id=str(uuid4()),
            telegram_user_id=telegram_user_id,
            pack_id=pack_id,
            amount_kopecks=amount_kopecks,
            status="created",
        )
        self.db.add(order)
        self.db.flush()

        def _rollback_order() -> tuple[PackOrder | None, str | None]:
            try:
                self.db.delete(order)
                self.db.flush()
            except Exception:
                pass
            return None, None

        return_url = f"https://t.me/{bot_username}?start=pack_done_{order.id}"
        idempotence_key = str(uuid4())

        try:
            client = YooKassaClient()
            if not client.is_configured():
                return _rollback_order()
            result = client.create_payment(
                order_id=order.id,
                return_url=return_url,
                idempotence_key=idempotence_key,
                amount_value=amount_value,
                description=description,
            )
        except YooKassaClientError as e:
            logger.warning(
                "pack_order_create_payment_failed",
                extra={"order_id": order.id, "pack_id": pack_id, "error": str(e)},
            )
            return _rollback_order()

        conf = result.get("confirmation", {}) or {}
        confirmation_url = (conf.get("confirmation_url") or "").strip()
        yookassa_payment_id = (result.get("id") or "").strip()
        if not confirmation_url or not yookassa_payment_id:
            logger.warning(
                "pack_order_missing_confirmation",
                extra={"order_id": order.id, "has_url": bool(confirmation_url), "has_id": bool(yookassa_payment_id)},
            )
            return _rollback_order()

        order.yookassa_payment_id = yookassa_payment_id
        order.confirmation_url = confirmation_url
        order.idempotence_key = idempotence_key
        order.status = "payment_pending"
        order.updated_at = datetime.now(timezone.utc)
        self.db.add(order)
        self.db.flush()
        return order, confirmation_url

    def mark_paid(self, order_id: str | None = None, yookassa_payment_id: str | None = None) -> PackOrder | None:
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

    def mark_completed(self, order_id: str) -> PackOrder | None:
        order = self.get_by_id(order_id)
        if not order or order.status not in ("paid",):
            return None
        order.status = "completed"
        order.updated_at = datetime.now(timezone.utc)
        self.db.add(order)
        self.db.flush()
        return order

    def mark_canceled(self, order_id: str | None = None, yookassa_payment_id: str | None = None) -> PackOrder | None:
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

    def mark_failed(self, order_id: str | None = None, yookassa_payment_id: str | None = None) -> PackOrder | None:
        if order_id:
            order = self.get_by_id(order_id)
        elif yookassa_payment_id:
            order = self.get_by_yookassa_payment_id(yookassa_payment_id)
        else:
            return None
        if not order or order.status not in ("created", "payment_pending"):
            return None
        order.status = "failed"
        order.updated_at = datetime.now(timezone.utc)
        self.db.add(order)
        self.db.flush()
        return order
