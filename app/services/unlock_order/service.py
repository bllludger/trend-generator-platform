"""
UnlockOrder service: создание/получение заказа на разблокировку одного фото по ЮKassa.
Правило: один активный payment_pending на (telegram_user_id, take_id, variant).
"""
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.take import Take
from app.models.unlock_order import UnlockOrder
from app.models.user import User
from app.paywall.config import get_unlock_amount_kopecks
from app.services.takes.service import TakeService

logger = logging.getLogger(__name__)

VALID_VARIANTS = ("A", "B", "C")
VALID_TAKE_STATUSES = ("ready", "partial_fail")


def unlock_photo_display_filename(order_id: str, file_path: str) -> str:
    """Имя файла для отправки в Telegram: neobanana_photo_{short_id}.png (brand + short-id вместо UUID)."""
    ext = (os.path.splitext(file_path)[1] or ".png").lower()
    if ext != ".png" and ext not in (".jpg", ".jpeg", ".webp"):
        ext = ".png"
    hex_part = order_id.replace("-", "")[:8]
    try:
        short = int(hex_part, 16) % 100000
    except ValueError:
        short = abs(hash(order_id)) % 100000
    return f"neobanana_photo_{short}{ext}"


def validate_can_create_unlock(
    db: DBSession,
    telegram_user_id: str,
    take_id: str,
    variant: str,
) -> tuple[bool, str]:
    """
    Проверки перед созданием платежа:
    - take принадлежит пользователю (user по telegram_id, take.user_id == user.id)
    - variant существует (A/B/C)
    - take в допустимом статусе (ready или partial_fail)
    - original path для варианта существует
    Returns (ok, error_message).
    """
    from app.services.users.service import UserService

    user = UserService(db).get_by_telegram_id(telegram_user_id)
    if not user:
        return False, "Пользователь не найден"

    take = TakeService(db).get_take(take_id)
    if not take:
        return False, "Фото не найдено"
    if str(take.user_id) != str(user.id):
        return False, "Фото не принадлежит пользователю"

    v = variant.upper()
    if v not in VALID_VARIANTS:
        return False, "Неверный вариант"
    if take.status not in VALID_TAKE_STATUSES:
        return False, "Фото ещё не готово к разблокировке"

    _, original_path = TakeService(db).get_variant_paths(take, v)
    if not original_path:
        return False, "Файл варианта недоступен"
    return True, ""


class UnlockOrderService:
    def __init__(self, db: DBSession):
        self.db = db

    def get_pending_order(
        self,
        telegram_user_id: str,
        take_id: str,
        variant: str,
    ) -> UnlockOrder | None:
        """Один активный payment_pending на связку. Если есть — вернуть его."""
        return (
            self.db.query(UnlockOrder)
            .filter(
                UnlockOrder.telegram_user_id == telegram_user_id,
                UnlockOrder.take_id == take_id,
                UnlockOrder.variant == variant.upper(),
                UnlockOrder.status == "payment_pending",
            )
            .order_by(UnlockOrder.created_at.desc())
            .first()
        )

    def get_order_with_paid_or_delivered(
        self,
        telegram_user_id: str,
        take_id: str,
        variant: str,
    ) -> UnlockOrder | None:
        """Есть ли уже оплаченный или доставленный заказ (для кнопки «Получить фото снова»)."""
        return (
            self.db.query(UnlockOrder)
            .filter(
                UnlockOrder.telegram_user_id == telegram_user_id,
                UnlockOrder.take_id == take_id,
                UnlockOrder.variant == variant.upper(),
                UnlockOrder.status.in_(("paid", "delivered")),
            )
            .order_by(UnlockOrder.updated_at.desc())
            .first()
        )

    def get_reusable_created_order(
        self,
        telegram_user_id: str,
        take_id: str,
        variant: str,
    ) -> UnlockOrder | None:
        """Заказ в статусе created без yookassa_payment_id (можно переиспользовать при повторе после ошибки)."""
        return (
            self.db.query(UnlockOrder)
            .filter(
                UnlockOrder.telegram_user_id == telegram_user_id,
                UnlockOrder.take_id == take_id,
                UnlockOrder.variant == variant.upper(),
                UnlockOrder.status == "created",
                UnlockOrder.yookassa_payment_id.is_(None),
            )
            .order_by(UnlockOrder.created_at.desc())
            .first()
        )

    def create_or_get_pending_order(
        self,
        telegram_user_id: str,
        take_id: str,
        variant: str,
    ) -> tuple[UnlockOrder, bool]:
        """
        Если есть payment_pending на связку — вернуть его (confirmation_url уже есть).
        Иначе если есть created без yookassa_payment_id — вернуть его для повтора (is_new=False, caller создаст платёж заново).
        Иначе создать новый order со статусом created.
        Returns (order, is_new).
        """
        existing = self.get_pending_order(telegram_user_id, take_id, variant)
        if existing:
            return existing, False

        reusable = self.get_reusable_created_order(telegram_user_id, take_id, variant)
        if reusable:
            return reusable, False

        order = UnlockOrder(
            id=str(uuid4()),
            telegram_user_id=telegram_user_id,
            take_id=take_id,
            variant=variant.upper(),
            amount_kopecks=get_unlock_amount_kopecks(),
            status="created",
        )
        self.db.add(order)
        self.db.flush()
        return order, True

    def set_payment_created(
        self,
        order_id: str,
        yookassa_payment_id: str,
        confirmation_url: str,
        idempotence_key: str,
    ) -> UnlockOrder | None:
        """После успешного создания платежа ЮKassa: сохранить данные и перевести в payment_pending."""
        order = self.db.query(UnlockOrder).filter(UnlockOrder.id == order_id).one_or_none()
        if not order or order.status != "created":
            return None
        order.yookassa_payment_id = yookassa_payment_id
        order.confirmation_url = confirmation_url
        order.idempotence_key = idempotence_key
        order.status = "payment_pending"
        order.updated_at = datetime.now(timezone.utc)
        self.db.add(order)
        self.db.flush()
        return order

    def get_by_id(self, order_id: str) -> UnlockOrder | None:
        return self.db.query(UnlockOrder).filter(UnlockOrder.id == order_id).one_or_none()

    def get_by_yookassa_payment_id(self, yookassa_payment_id: str) -> UnlockOrder | None:
        return (
            self.db.query(UnlockOrder)
            .filter(UnlockOrder.yookassa_payment_id == yookassa_payment_id)
            .one_or_none()
        )

    def mark_paid(self, order_id: str | None = None, yookassa_payment_id: str | None = None) -> UnlockOrder | None:
        """Пометить заказ как оплаченный (по id заказа или по yookassa_payment_id)."""
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

    def mark_delivered(self, order_id: str) -> UnlockOrder | None:
        order = self.get_by_id(order_id)
        if not order or order.status != "paid":
            return None
        order.status = "delivered"
        order.delivered_at = datetime.now(timezone.utc)
        order.updated_at = datetime.now(timezone.utc)
        self.db.add(order)
        self.db.flush()
        return order

    def mark_delivery_failed(self, order_id: str) -> UnlockOrder | None:
        order = self.get_by_id(order_id)
        if not order or order.status != "paid":
            return None
        order.status = "delivery_failed"
        order.updated_at = datetime.now(timezone.utc)
        self.db.add(order)
        self.db.flush()
        return order

    def mark_canceled(self, order_id: str | None = None, yookassa_payment_id: str | None = None) -> UnlockOrder | None:
        """Пометить заказ как отменённый (по id или по yookassa_payment_id)."""
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

    def get_order_for_delivery(self, order_id: str) -> tuple[UnlockOrder | None, str | None]:
        """
        Для Celery-задачи доставки: загрузить order, проверить status=paid,
        вернуть (order, original_path). Path из TakeService.get_variant_paths.
        """
        order = self.get_by_id(order_id)
        if not order:
            return None, None
        if order.status != "paid":
            return order, None
        take = TakeService(self.db).get_take(order.take_id)
        if not take:
            return order, None
        _, original_path = TakeService(self.db).get_variant_paths(take, order.variant)
        return order, original_path
