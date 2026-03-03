"""
PaymentService — безопасная обработка платежей Telegram Stars.

Ответственности:
- Валидация payload при pre_checkout_query
- Атомарное начисление токенов при successful_payment
- Рефанд (через Telegram Bot API + откат баланса)
- Получение истории платежей
"""
import logging
import secrets
from datetime import datetime, timezone
from uuid import uuid4

import redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.pack import Pack
from app.models.payment import Payment
from app.models.session import Session as SessionModel
from app.models.take import Take
from app.models.user import User
from app.services.audit.service import AuditService
from app.services.sessions.service import SessionService
from app.services.hd_balance.service import HDBalanceService

logger = logging.getLogger(__name__)

PURCHASE_RATE_LIMIT = 3  # макс покупок за окно
PURCHASE_RATE_WINDOW = 60  # секунд

# Единственные SKU в продаже (product ladder). Остальные пакеты не показывать и не принимать в paywall/bank.
PRODUCT_LADDER_IDS = ("trial", "neo_start", "neo_pro", "neo_unlimited")


class PaymentService:
    def __init__(self, db: Session):
        self.db = db
        self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    # ------------------------------------------------------------------
    # Pack management
    # ------------------------------------------------------------------

    def list_active_packs(self) -> list[Pack]:
        """Вернуть все активные пакеты, отсортированные по order_index."""
        return (
            self.db.query(Pack)
            .filter(Pack.enabled.is_(True))
            .order_by(Pack.order_index)
            .all()
        )

    def list_product_ladder_packs(self) -> list[Pack]:
        """Пакеты продуктовой лестницы для отображения в боте (магазин, paywall, bank transfer)."""
        return (
            self.db.query(Pack)
            .filter(Pack.id.in_(PRODUCT_LADDER_IDS), Pack.enabled.is_(True))
            .order_by(Pack.order_index)
            .all()
        )

    def get_pack(self, pack_id: str) -> Pack | None:
        return self.db.query(Pack).filter(Pack.id == pack_id).one_or_none()

    def seed_default_packs(self) -> None:
        """Создать пакеты по умолчанию, если таблица пустая. Для непустой БД — добавить Plus, если отсутствует."""
        existing = self.db.query(Pack).count()
        if existing > 0:
            # У существующих инсталляций мог не быть пакета Plus — добавить при отсутствии
            if self.get_pack("plus") is None:
                plus = Pack(
                    id="plus",
                    name="Plus",
                    emoji="✨",
                    tokens=30,
                    stars_price=115,
                    description="30 фото без watermark",
                    order_index=2,
                    enabled=True,
                )
                self.db.add(plus)
                pro = self.get_pack("pro")
                if pro and pro.order_index == 2:
                    pro.order_index = 3
                    self.db.add(pro)
                self.db.flush()
                logger.info("plus_pack_added", extra={"reason": "missing_in_existing_db"})
            for pid, pname, pemoji, ptokens, pstars, pdesc, pidx in [
                ("premium", "Premium", "👑", 80, 249, "80 фото без watermark", 4),
                ("ultra", "Ultra", "🚀", 170, 499, "170 фото без watermark", 5),
            ]:
                if self.get_pack(pid) is None:
                    self.db.add(Pack(
                        id=pid, name=pname, emoji=pemoji, tokens=ptokens,
                        stars_price=pstars, description=pdesc, order_index=pidx, enabled=True,
                    ))
                    self.db.flush()
                    logger.info(f"{pid}_pack_added", extra={"reason": "missing_in_existing_db"})
            for pid, pname, pemoji, pstars, pdesc, pidx, ptakes, phd in [
                ("neo_start", "Neo Start", "🚀", 153, "10 образов + 10 4K без watermark", 1, 10, 10),
                ("neo_pro", "Neo Pro", "⭐", 538, "40 образов + 40 4K без watermark", 2, 40, 40),
                ("neo_unlimited", "Neo Unlimited", "👑", 1531, "120 образов + 120 4K без watermark", 3, 120, 120),
            ]:
                if self.get_pack(pid) is None:
                    self.db.add(Pack(
                        id=pid, name=pname, emoji=pemoji, tokens=0,
                        stars_price=pstars, description=pdesc, order_index=pidx, enabled=True,
                        takes_limit=ptakes, hd_amount=phd, pack_type="session",
                    ))
                    self.db.flush()
                    logger.info(f"{pid}_pack_added", extra={"reason": "missing_in_existing_db"})
            return
        defaults = [
            Pack(
                id="starter",
                name="Starter",
                emoji="⭐",
                tokens=5,
                stars_price=25,
                description="5 фото без watermark",
                order_index=0,
            ),
            Pack(
                id="standard",
                name="Standard",
                emoji="🌟",
                tokens=15,
                stars_price=65,
                description="15 фото без watermark",
                order_index=1,
            ),
            Pack(
                id="plus",
                name="Plus",
                emoji="✨",
                tokens=30,
                stars_price=115,
                description="30 фото без watermark",
                order_index=2,
            ),
            Pack(
                id="pro",
                name="Pro",
                emoji="💎",
                tokens=50,
                stars_price=175,
                description="50 фото без watermark",
                order_index=3,
            ),
            Pack(
                id="premium",
                name="Premium",
                emoji="👑",
                tokens=80,
                stars_price=249,
                description="80 фото без watermark",
                order_index=4,
            ),
            Pack(
                id="ultra",
                name="Ultra",
                emoji="🚀",
                tokens=170,
                stars_price=499,
                description="170 фото без watermark",
                order_index=5,
            ),
        ]
        for pack in defaults:
            self.db.add(pack)
        self.db.flush()
        logger.info("default_packs_seeded", extra={"count": len(defaults)})

    # ------------------------------------------------------------------
    # Payload generation & validation
    # ------------------------------------------------------------------

    PAYLOAD_REDIS_PREFIX = "invoice_payload:"
    PAYLOAD_REDIS_TTL = 3600  # 1 час

    def build_payload(self, pack_id: str, user_id: str, job_id: str | None = None) -> str:
        """
        Формирует payload для invoice (1–128 байт, лимит Telegram).
        Если строка длиннее 128 байт — сохраняем в Redis, в invoice передаём короткий токен.
        """
        nonce = str(uuid4())
        base = f"pack:{pack_id}:user:{user_id}:nonce:{nonce}"
        if job_id:
            base += f":job:{job_id}"
        if len(base.encode("utf-8")) <= 128:
            return base
        token = secrets.token_hex(8)  # 16 символов
        key = f"{self.PAYLOAD_REDIS_PREFIX}{token}"
        self._redis.setex(key, self.PAYLOAD_REDIS_TTL, base)
        return token

    def resolve_payload(self, payload: str) -> str:
        """
        Если payload — короткий токен (сохранённый в Redis), возвращает полную строку.
        Иначе возвращает payload как есть (обратная совместимость).
        """
        if ":" in payload and payload.startswith("pack:"):
            return payload
        key = f"{self.PAYLOAD_REDIS_PREFIX}{payload}"
        full = self._redis.get(key)
        if full:
            return full
        return payload

    @staticmethod
    def parse_payload(payload: str) -> dict[str, str]:
        """
        Парсит payload обратно в словарь.
        Returns: {"pack_id": ..., "user_id": ..., "nonce": ..., "job_id": ... | None}
        """
        parts = payload.split(":")
        result: dict[str, str] = {}
        i = 0
        while i < len(parts) - 1:
            key = parts[i]
            val = parts[i + 1]
            if key == "pack":
                result["pack_id"] = val
            elif key == "user":
                result["user_id"] = val
            elif key == "nonce":
                result["nonce"] = val
            elif key == "job":
                result["job_id"] = val
            i += 2
        return result

    def validate_pre_checkout(
        self, payload: str, telegram_user_id: str
    ) -> tuple[bool, str]:
        """
        Валидация pre_checkout_query.
        Returns: (ok, error_message)
        Supports payloads: legacy (pack:...:user:...), session:{pack_id}, upgrade:{pack_id}:{session_id}
        """
        # New session-based payloads
        if payload.startswith("session:") or payload.startswith("upgrade:"):
            user = self.db.query(User).filter(User.telegram_id == telegram_user_id).one_or_none()
            if not user:
                return False, "Пользователь не найден"
            if user.is_access_blocked():
                return False, "Ваш аккаунт заблокирован"
            if not self._check_rate_limit(telegram_user_id):
                return False, "Слишком много покупок. Попробуйте позже."

            if payload.startswith("session:"):
                pack_id = payload.split(":", 1)[1]
                pack = self.get_pack(pack_id)
                if not pack or not pack.enabled:
                    return False, "Пакет недоступен"
                if pack.is_trial and user.trial_purchased:
                    return False, "Trial уже использован"
            elif payload.startswith("upgrade:"):
                parts = payload.split(":")
                if len(parts) != 3:
                    return False, "Некорректный payload"
                pack_id, old_session_id = parts[1], parts[2]
                pack = self.get_pack(pack_id)
                if not pack or not pack.enabled:
                    return False, "Пакет недоступен"
                old_session = self.db.query(SessionModel).filter(SessionModel.id == old_session_id).one_or_none()
                if not old_session or old_session.user_id != user.id:
                    return False, "Сессия не найдена"

            return True, ""

        # Legacy payloads
        full_payload = self.resolve_payload(payload)
        parsed = self.parse_payload(full_payload)
        if not parsed.get("pack_id") or not parsed.get("user_id"):
            return False, "Некорректный payload"

        user = self.db.query(User).filter(User.telegram_id == telegram_user_id).one_or_none()
        if not user:
            return False, "Пользователь не найден"
        if user.id != parsed["user_id"]:
            return False, "Несоответствие пользователя"

        if user.is_access_blocked():
            return False, "Ваш аккаунт заблокирован"

        pack_id = parsed["pack_id"]
        if pack_id != "unlock":
            pack = self.get_pack(pack_id)
            if not pack or not pack.enabled:
                return False, "Пакет недоступен"

        if not self._check_rate_limit(telegram_user_id):
            return False, "Слишком много покупок. Попробуйте позже."

        return True, ""

    # ------------------------------------------------------------------
    # Credit tokens (atomic)
    # ------------------------------------------------------------------

    def credit_tokens(
        self,
        telegram_user_id: str,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str | None,
        pack_id: str,
        stars_amount: int,
        tokens_granted: int,
        payload: str,
        job_id: str | None = None,
    ) -> Payment | None:
        """
        Атомарно создаёт Payment и начисляет token_balance пользователю.
        Idempotent: если telegram_payment_charge_id уже есть — возвращает существующий.
        """
        # Idempotency check
        existing = (
            self.db.query(Payment)
            .filter(Payment.telegram_payment_charge_id == telegram_payment_charge_id)
            .one_or_none()
        )
        if existing:
            logger.info(
                "payment_already_processed",
                extra={"charge_id": telegram_payment_charge_id},
            )
            return existing

        try:
            user = (
                self.db.query(User)
                .filter(User.telegram_id == telegram_user_id)
                .with_for_update()
                .one_or_none()
            )
            if not user:
                logger.error("payment_user_not_found", extra={"tg_id": telegram_user_id})
                return None

            # Начисляем токены
            user.token_balance += tokens_granted
            user.total_purchased += tokens_granted

            # Создаём запись платежа
            payment = Payment(
                user_id=user.id,
                telegram_payment_charge_id=telegram_payment_charge_id,
                provider_payment_charge_id=provider_payment_charge_id,
                pack_id=pack_id,
                stars_amount=stars_amount,
                tokens_granted=tokens_granted,
                status="completed",
                payload=payload,
                job_id=job_id,
            )
            self.db.add(payment)
            self.db.flush()

            logger.info(
                "payment_completed",
                extra={
                    "user_id": user.id,
                    "pack_id": pack_id,
                    "stars": stars_amount,
                    "tokens": tokens_granted,
                    "new_balance": user.token_balance,
                    "charge_id": telegram_payment_charge_id,
                },
            )
            return payment
        except IntegrityError:
            self.db.rollback()
            logger.warning(
                "payment_duplicate",
                extra={"charge_id": telegram_payment_charge_id},
            )
            return (
                self.db.query(Payment)
                .filter(Payment.telegram_payment_charge_id == telegram_payment_charge_id)
                .one_or_none()
            )

    # ------------------------------------------------------------------
    # Refund
    # ------------------------------------------------------------------

    def process_refund(self, payment_id: str) -> tuple[bool, str, Payment | None]:
        """
        Помечает платёж как refunded и списывает токены с баланса.
        Returns: (ok, error_message, payment)
        
        Telegram API refundStarPayment должен быть вызван ОТДЕЛЬНО перед этим.
        """
        payment = self.db.query(Payment).filter(Payment.id == payment_id).one_or_none()
        if not payment:
            return False, "Платёж не найден", None
        if payment.status == "refunded":
            return False, "Уже возвращён", payment

        user = (
            self.db.query(User)
            .filter(User.id == payment.user_id)
            .with_for_update()
            .one_or_none()
        )
        if not user:
            return False, "Пользователь не найден", payment

        # Списываем токены (не ниже 0)
        deduction = min(payment.tokens_granted, user.token_balance)
        user.token_balance -= deduction
        user.total_purchased = max(0, user.total_purchased - payment.tokens_granted)

        payment.status = "refunded"
        payment.refunded_at = datetime.now(timezone.utc)

        self.db.flush()

        # Revoke referral bonus linked to this payment (if any)
        try:
            from app.referral.service import ReferralService
            ref_svc = ReferralService(self.db)
            ref_svc.revoke_bonus_by_payment(payment_id, reason="refund")
        except Exception:
            logger.exception("referral_revoke_on_refund_error", extra={"payment_id": payment_id})

        logger.info(
            "payment_refunded",
            extra={
                "payment_id": payment_id,
                "user_id": user.id,
                "deducted": deduction,
                "new_balance": user.token_balance,
            },
        )
        return True, "", payment

    def credit_tokens_manual(
        self,
        telegram_user_id: str,
        pack_id: str,
        stars_amount: int,
        tokens_granted: int,
        reference: str,
    ) -> Payment | None:
        """
        Зачислить токены за «ручной» платёж (перевод на карту).
        Идемпотентно по charge_id = f"bank_transfer:{reference}".
        """
        charge_id = f"bank_transfer:{reference}"
        return self.credit_tokens(
            telegram_user_id=telegram_user_id,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id=None,
            pack_id=pack_id,
            stars_amount=stars_amount,
            tokens_granted=tokens_granted,
            payload=f"bank_transfer:{reference}",
        )

    def record_unlock_tokens(
        self, user_id: str, job_id: str, tokens_spent: int
    ) -> Payment:
        """
        Записать разблокировку фото за токены в таблицу payments для единой аналитики.
        Не используется для Telegram Stars; рефанд через API для таких записей недоступен.
        """
        charge_id = f"token_unlock:{uuid4()}"
        payment = Payment(
            user_id=user_id,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id=None,
            pack_id="unlock_tokens",
            stars_amount=0,
            tokens_granted=0,
            status="completed",
            payload=job_id,
            job_id=job_id,
        )
        self.db.add(payment)
        self.db.flush()
        logger.info(
            "unlock_tokens_recorded",
            extra={"user_id": user_id, "job_id": job_id, "tokens_spent": tokens_spent},
        )
        return payment

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_user_payments(
        self, user_id: str, limit: int = 50
    ) -> list[Payment]:
        """Получить последние платежи пользователя."""
        return (
            self.db.query(Payment)
            .filter(Payment.user_id == user_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_payment_by_charge_id(self, charge_id: str) -> Payment | None:
        return (
            self.db.query(Payment)
            .filter(Payment.telegram_payment_charge_id == charge_id)
            .one_or_none()
        )

    # ------------------------------------------------------------------
    # Session-based purchases
    # ------------------------------------------------------------------

    def process_session_purchase(
        self,
        telegram_user_id: str,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str | None,
        pack_id: str,
        stars_amount: int,
        payload: str,
    ) -> tuple[Payment | None, SessionModel | None]:
        """
        Process session pack purchase: create Session, credit HD to user, record Payment.
        Attaches free Take (from pre-session) to the new session if exists.
        """
        existing = (
            self.db.query(Payment)
            .filter(Payment.telegram_payment_charge_id == telegram_payment_charge_id)
            .one_or_none()
        )
        if existing:
            return existing, None

        try:
            user = (
                self.db.query(User)
                .filter(User.telegram_id == telegram_user_id)
                .with_for_update()
                .one_or_none()
            )
            if not user:
                return None, None

            pack = self.get_pack(pack_id)
            if not pack:
                return None, None

            session_svc = SessionService(self.db)
            hd_svc = HDBalanceService(self.db)

            if getattr(pack, "pack_subtype", "standalone") == "collection":
                if not pack.playlist or not isinstance(pack.playlist, list) or len(pack.playlist) == 0:
                    raise ValueError(f"Collection pack {pack_id} has no playlist — cannot sell")
                session = session_svc.create_collection_session(user.id, pack)
                audit = AuditService(self.db)
                audit.log(
                    actor_type="system",
                    actor_id="payment",
                    action="collection_start",
                    entity_type="session",
                    entity_id=session.id,
                    payload={
                        "pack_id": pack_id,
                        "collection_run_id": session.collection_run_id,
                    },
                )
            else:
                session = session_svc.create_session(user.id, pack_id)
            hd_svc.credit_paid(user, pack.hd_amount or 0)

            if pack.is_trial:
                from sqlalchemy import update as sa_update
                res = self.db.execute(
                    sa_update(User)
                    .where(User.id == user.id, (User.trial_purchased == False) | (User.trial_purchased == None))
                    .values(trial_purchased=True)
                )
                if res.rowcount == 0:
                    raise ValueError("Trial уже использован (race condition guard)")

            # Attach free Take from pre-session
            free_session = (
                self.db.query(SessionModel)
                .filter(
                    SessionModel.user_id == user.id,
                    SessionModel.pack_id == "free_preview",
                    SessionModel.status == "active",
                )
                .first()
            )
            if free_session:
                free_takes = self.db.query(Take).filter(Take.session_id == free_session.id).all()
                for take in free_takes:
                    session_svc.attach_take_to_session(take, session)
                session.takes_used = min(len(free_takes), session.takes_limit)
                free_session.status = "completed"
                self.db.add(free_session)
                self.db.add(session)

            payment = Payment(
                user_id=user.id,
                telegram_payment_charge_id=telegram_payment_charge_id,
                provider_payment_charge_id=provider_payment_charge_id,
                pack_id=pack_id,
                stars_amount=stars_amount,
                tokens_granted=0,
                status="completed",
                payload=payload,
                session_id=session.id,
            )
            self.db.add(payment)
            self.db.flush()

            logger.info(
                "session_purchase_completed",
                extra={
                    "user_id": user.id,
                    "pack_id": pack_id,
                    "session_id": session.id,
                    "hd_credited": pack.hd_amount,
                },
            )
            return payment, session
        except IntegrityError:
            self.db.rollback()
            return (
                self.db.query(Payment)
                .filter(Payment.telegram_payment_charge_id == telegram_payment_charge_id)
                .one_or_none()
            ), None

    def process_session_upgrade(
        self,
        telegram_user_id: str,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str | None,
        new_pack_id: str,
        old_session_id: str,
        stars_amount: int,
        payload: str,
    ) -> tuple[Payment | None, SessionModel | None]:
        """
        Process session upgrade: create new Session, credit HD, mark old as upgraded.
        """
        existing = (
            self.db.query(Payment)
            .filter(Payment.telegram_payment_charge_id == telegram_payment_charge_id)
            .one_or_none()
        )
        if existing:
            return existing, None

        try:
            user = (
                self.db.query(User)
                .filter(User.telegram_id == telegram_user_id)
                .with_for_update()
                .one_or_none()
            )
            if not user:
                return None, None

            new_pack = self.get_pack(new_pack_id)
            old_session = self.db.query(SessionModel).filter(SessionModel.id == old_session_id).one_or_none()
            if not new_pack or not old_session:
                return None, None

            old_pack = self.get_pack(old_session.pack_id)
            credit_stars = old_pack.stars_price if old_pack else 0

            session_svc = SessionService(self.db)
            hd_svc = HDBalanceService(self.db)

            new_session = session_svc.upgrade_session(old_session, new_pack_id, credit_stars)
            old_hd = (old_pack.hd_amount or 0) if old_pack else 0
            delta_hd = max(0, (new_pack.hd_amount or 0) - old_hd)
            hd_svc.credit_paid(user, delta_hd)

            payment = Payment(
                user_id=user.id,
                telegram_payment_charge_id=telegram_payment_charge_id,
                provider_payment_charge_id=provider_payment_charge_id,
                pack_id=new_pack_id,
                stars_amount=stars_amount,
                tokens_granted=0,
                status="completed",
                payload=payload,
                session_id=new_session.id,
            )
            self.db.add(payment)
            self.db.flush()

            logger.info(
                "session_upgrade_completed",
                extra={
                    "user_id": user.id,
                    "old_session": old_session_id,
                    "new_session": new_session.id,
                    "pack_id": new_pack_id,
                    "credit_stars": credit_stars,
                },
            )
            return payment, new_session
        except IntegrityError:
            self.db.rollback()
            return (
                self.db.query(Payment)
                .filter(Payment.telegram_payment_charge_id == telegram_payment_charge_id)
                .one_or_none()
            ), None

    # ------------------------------------------------------------------
    # Rate-limit (Redis — общий для всех воркеров/реплик бота)
    # ------------------------------------------------------------------

    def _check_rate_limit(self, telegram_user_id: str) -> bool:
        """Не более PURCHASE_RATE_LIMIT покупок за PURCHASE_RATE_WINDOW сек. Работает при нескольких репликах бота."""
        key = f"purchase_rate:{telegram_user_id}"
        try:
            current = self._redis.incr(key)
            if current == 1:
                self._redis.expire(key, PURCHASE_RATE_WINDOW)
            return current <= PURCHASE_RATE_LIMIT
        except redis.RedisError as e:
            logger.warning("purchase_rate_limit_redis_error", extra={"error": str(e)})
            return True  # fail open: при недоступности Redis разрешаем покупку
