from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import update

from app.models.token_ledger import TokenLedger
from app.models.user import User


class UserService:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create_user(
        self,
        telegram_id: str,
        telegram_username: str | None = None,
        telegram_first_name: str | None = None,
        telegram_last_name: str | None = None,
    ) -> User:
        user = self.db.query(User).filter(User.telegram_id == telegram_id).one_or_none()
        if user:
            if telegram_username is not None or telegram_first_name is not None or telegram_last_name is not None:
                if telegram_username is not None:
                    user.telegram_username = telegram_username
                if telegram_first_name is not None:
                    user.telegram_first_name = telegram_first_name
                if telegram_last_name is not None:
                    user.telegram_last_name = telegram_last_name
                self.db.add(user)
                self.db.commit()
                self.db.refresh(user)
            return user
        user = User(
            telegram_id=telegram_id,
            telegram_username=telegram_username,
            telegram_first_name=telegram_first_name,
            telegram_last_name=telegram_last_name,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_by_telegram_id(self, telegram_id: str) -> User | None:
        return self.db.query(User).filter(User.telegram_id == telegram_id).one_or_none()

    def update_admin(self, user: User, token_balance: int, subscription_active: bool) -> User:
        user.token_balance = token_balance
        user.subscription_active = subscription_active
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def _is_moderator(self, user: User) -> bool:
        """Модератор не ограничен лимитами."""
        return getattr(user, "is_moderator", False) is True

    def can_reserve(self, user: User, amount: int) -> bool:
        if self._is_moderator(user):
            return True
        return user.token_balance >= amount

    def try_use_free_generation(self, user: User) -> bool:
        """
        Atomically consume 1 of 3 free generations. Prevents abuse.
        Moderator: always returns True without consuming.
        """
        if self._is_moderator(user):
            return True
        from app.services.security.settings_service import SecuritySettingsService
        sec = SecuritySettingsService(self.db).get_or_create()
        limit = getattr(sec, "free_generations_per_user", 3)
        result = self.db.execute(
            update(User)
            .where(User.id == user.id, User.free_generations_used < limit)
            .values(free_generations_used=User.free_generations_used + 1)
        )
        self.db.flush()
        return result.rowcount > 0

    def try_use_copy_generation(self, user: User) -> bool:
        """
        Atomically consume 1 of N copy generations («Сделать такую же»). Prevents abuse.
        Moderator: always returns True without consuming.
        """
        if self._is_moderator(user):
            return True
        from app.services.security.settings_service import SecuritySettingsService
        sec = SecuritySettingsService(self.db).get_or_create()
        limit = getattr(sec, "copy_generations_per_user", 1)
        result = self.db.execute(
            update(User)
            .where(User.id == user.id, User.copy_generations_used < limit)
            .values(copy_generations_used=User.copy_generations_used + 1)
        )
        self.db.flush()
        return result.rowcount > 0

    def hold_tokens(self, user: User, job_id: str, amount: int) -> bool:
        if self._is_moderator(user):
            return True
        try:
            if self._ledger_exists(user.id, job_id, "HOLD"):
                return True
            locked_user = (
                self.db.query(User)
                .filter(User.id == user.id)
                .with_for_update()
                .one()
            )
            if locked_user.token_balance < amount:
                return False
            locked_user.token_balance -= amount
            ledger = TokenLedger(user_id=locked_user.id, job_id=job_id, operation="HOLD", amount=amount)
            self.db.add(ledger)
            self.db.flush()
            return True
        except IntegrityError:
            self.db.rollback()
            return True

    def capture_tokens(self, user: User, job_id: str, amount: int) -> None:
        try:
            if self._ledger_exists(user.id, job_id, "CAPTURE"):
                return
            if self._ledger_exists(user.id, job_id, "RELEASE"):
                return
            ledger = TokenLedger(user_id=user.id, job_id=job_id, operation="CAPTURE", amount=amount)
            self.db.add(ledger)
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            return

    def release_tokens(self, user: User, job_id: str, amount: int) -> None:
        try:
            if self._ledger_exists(user.id, job_id, "RELEASE"):
                return
            if self._ledger_exists(user.id, job_id, "CAPTURE"):
                return
            if not self._ledger_exists(user.id, job_id, "HOLD"):
                return
            locked_user = (
                self.db.query(User)
                .filter(User.id == user.id)
                .with_for_update()
                .one()
            )
            locked_user.token_balance += amount
            ledger = TokenLedger(user_id=locked_user.id, job_id=job_id, operation="RELEASE", amount=amount)
            self.db.add(ledger)
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            return

    def debit_tokens_for_unlock(self, user: User, job_id: str, amount: int) -> bool:
        """
        Списание токенов с баланса при разблокировке фото (кнопка «За N токен»).
        Не используется при оплате unlock за Stars.
        Атомарно: row-level lock + HOLD и CAPTURE в ledger.
        Возвращает True если успешно.
        """
        if self._is_moderator(user):
            return True
        try:
            if self._ledger_exists(user.id, job_id, "HOLD"):
                return True  # уже списано
            locked_user = (
                self.db.query(User)
                .filter(User.id == user.id)
                .with_for_update()
                .one()
            )
            if locked_user.token_balance < amount:
                return False
            locked_user.token_balance -= amount
            ledger = TokenLedger(
                user_id=locked_user.id,
                job_id=job_id,
                operation="HOLD",
                amount=amount,
            )
            self.db.add(ledger)
            # Сразу CAPTURE (разблокировка = финальная операция)
            capture = TokenLedger(
                user_id=locked_user.id,
                job_id=f"{job_id}:unlock",
                operation="CAPTURE",
                amount=amount,
            )
            self.db.add(capture)
            self.db.flush()
            return True
        except IntegrityError:
            self.db.rollback()
            return True  # idempotent

    def reset_all_limits(self) -> int:
        """
        Сброс счётчиков бесплатных и copy-генераций у всех пользователей.
        Возвращает количество обновлённых строк.
        """
        result = self.db.execute(
            update(User).values(
                free_generations_used=0,
                copy_generations_used=0,
            )
        )
        self.db.flush()
        return result.rowcount

    def _ledger_exists(self, user_id: str, job_id: str, operation: str) -> bool:
        """Check if ledger entry exists. Uses scalar subquery for efficiency."""
        from sqlalchemy import exists, select
        stmt = (
            select(TokenLedger.id)
            .where(
                TokenLedger.user_id == user_id,
                TokenLedger.job_id == job_id,
                TokenLedger.operation == operation,
            )
            .exists()
        )
        return self.db.query(stmt).scalar() or False