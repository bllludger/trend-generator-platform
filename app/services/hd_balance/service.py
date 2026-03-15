import logging

from sqlalchemy import update
from sqlalchemy.orm import Session as DBSession

from app.models.user import User

logger = logging.getLogger(__name__)


class HDBalanceService:
    """HD balance lives on User, not Session. Spend order: promo first, then paid."""

    def __init__(self, db: DBSession):
        self.db = db

    def credit_paid(self, user: User, amount: int) -> None:
        user.hd_paid_balance = (user.hd_paid_balance or 0) + amount
        self.db.add(user)
        self.db.flush()

    def credit_promo(self, user: User, amount: int) -> None:
        user.hd_promo_balance = (user.hd_promo_balance or 0) + amount
        self.db.add(user)
        self.db.flush()

    def can_spend(self, user: User, amount: int = 1) -> bool:
        total = (user.hd_promo_balance or 0) + (user.hd_paid_balance or 0)
        return total >= amount

    def spend(self, user: User, amount: int = 1) -> bool:
        """Atomically deduct HD. Promo first, then paid. Returns False if insufficient."""
        promo = user.hd_promo_balance or 0
        paid = user.hd_paid_balance or 0
        total = promo + paid
        if total < amount:
            return False

        from_promo = min(promo, amount)
        from_paid = amount - from_promo

        locked = (
            self.db.query(User)
            .filter(User.id == user.id)
            .with_for_update()
            .one()
        )
        actual_total = (locked.hd_promo_balance or 0) + (locked.hd_paid_balance or 0)
        if actual_total < amount:
            return False

        actual_promo = min(locked.hd_promo_balance or 0, amount)
        actual_paid = amount - actual_promo

        locked.hd_promo_balance = (locked.hd_promo_balance or 0) - actual_promo
        locked.hd_paid_balance = (locked.hd_paid_balance or 0) - actual_paid
        self.db.flush()

        self.db.refresh(user)
        return True

    def debit(self, user: User, amount: int) -> int:
        """
        Списать до amount HD с баланса пользователя (при рефанде).
        Списываем сначала paid, затем promo. Возвращает фактически списанную сумму (не больше amount и не больше баланса).
        """
        if amount <= 0:
            return 0
        locked = (
            self.db.query(User)
            .filter(User.id == user.id)
            .with_for_update()
            .one()
        )
        paid = locked.hd_paid_balance or 0
        promo = locked.hd_promo_balance or 0
        total = paid + promo
        to_deduct = min(amount, total)
        if to_deduct <= 0:
            return 0
        from_paid = min(paid, to_deduct)
        from_promo = to_deduct - from_paid
        locked.hd_paid_balance = paid - from_paid
        locked.hd_promo_balance = promo - from_promo
        self.db.flush()
        self.db.refresh(user)
        return to_deduct

    def get_balance(self, user: User) -> dict:
        paid = user.hd_paid_balance or 0
        promo = user.hd_promo_balance or 0
        return {"paid": paid, "promo": promo, "total": paid + promo}
