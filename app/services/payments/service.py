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
import time
from datetime import datetime, timezone
from uuid import uuid4

import redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.job import Job
from app.models.pack import Pack
from app.models.payment import Payment
from app.models.session import Session as SessionModel
from app.models.trial_bundle_order import TrialBundleOrder
from app.models.unlock_order import UnlockOrder
from app.models.take import Take
from app.models.user import User
from app.services.audit.service import AuditService
from app.services.product_analytics.service import ProductAnalyticsService
from app.services.sessions.service import SessionService
from app.services.hd_balance.service import HDBalanceService
from app.utils.metrics import payment_processing_errors_total, pay_refund_total

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
        ladder_meta = {
            "trial": ("Trial", "🎬"),
            "neo_start": ("Neo Start", "🚀"),
            "neo_pro": ("Neo Pro", "⭐"),
            "neo_unlimited": ("Neo Unlimited", "👑"),
        }
        existing = self.db.query(Pack).count()
        if existing > 0:
            # Нормализуем параметры продуктовой лестницы, чтобы UI и цены были консистентными.
            ladder_defaults = {
                "neo_start": {
                    "name": "Neo Start",
                    "emoji": "🚀",
                    "stars_price": 153,
                    "description": "15 фото + 15 4K без водяного знака",
                    "order_index": 1,
                    "takes_limit": 15,
                    "hd_amount": 15,
                    "pack_type": "session",
                    "enabled": True,
                },
                "neo_pro": {
                    "name": "Neo Pro",
                    "emoji": "⭐",
                    "stars_price": 384,
                    "description": "50 фото + 50 4K без водяного знака",
                    "order_index": 2,
                    "takes_limit": 50,
                    "hd_amount": 50,
                    "pack_type": "session",
                    "enabled": True,
                },
                "neo_unlimited": {
                    "name": "Neo Unlimited",
                    "emoji": "👑",
                    "stars_price": 762,
                    "description": "120 фото + 120 4K без водяного знака",
                    "order_index": 3,
                    "takes_limit": 120,
                    "hd_amount": 120,
                    "pack_type": "session",
                    "enabled": True,
                },
            }
            for pid, (pname, pemoji) in ladder_meta.items():
                pack = self.get_pack(pid)
                if not pack:
                    continue
                if pack.id in ladder_defaults:
                    defaults = ladder_defaults[pack.id]
                    pack.name = defaults["name"]
                    pack.emoji = defaults["emoji"]
                    pack.stars_price = defaults["stars_price"]
                    pack.description = defaults["description"]
                    pack.order_index = defaults["order_index"]
                    pack.takes_limit = defaults["takes_limit"]
                    pack.hd_amount = defaults["hd_amount"]
                    pack.pack_type = defaults["pack_type"]
                    pack.enabled = defaults["enabled"]
                    pack.tokens = 0
                    self.db.add(pack)
                elif pack.name != pname or pack.emoji != pemoji:
                    pack.name = pname
                    pack.emoji = pemoji
                    self.db.add(pack)

            # У существующих инсталляций мог не быть пакета Plus — добавить при отсутствии
            if self.get_pack("plus") is None:
                plus = Pack(
                    id="plus",
                    name="Plus",
                    emoji="✨",
                    tokens=30,
                    stars_price=115,
                    description="30 фото без водяного знака",
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
                ("premium", "Premium", "👑", 80, 249, "80 фото без водяного знака", 4),
                ("ultra", "Ultra", "🚀", 170, 499, "170 фото без водяного знака", 5),
            ]:
                if self.get_pack(pid) is None:
                    self.db.add(Pack(
                        id=pid, name=pname, emoji=pemoji, tokens=ptokens,
                        stars_price=pstars, description=pdesc, order_index=pidx, enabled=True,
                    ))
                    self.db.flush()
                    logger.info(f"{pid}_pack_added", extra={"reason": "missing_in_existing_db"})
            for pid, pname, pemoji, pstars, pdesc, pidx, ptakes, phd in [
                ("neo_start", "Neo Start", "🚀", 153, "15 фото + 15 4K без водяного знака", 1, 15, 15),
                ("neo_pro", "Neo Pro", "⭐", 384, "50 фото + 50 4K без водяного знака", 2, 50, 50),
                ("neo_unlimited", "Neo Unlimited", "👑", 762, "120 фото + 120 4K без водяного знака", 3, 120, 120),
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
                description="5 фото без водяного знака",
                order_index=0,
            ),
            Pack(
                id="standard",
                name="Standard",
                emoji="🌟",
                tokens=15,
                stars_price=65,
                description="15 фото без водяного знака",
                order_index=1,
            ),
            Pack(
                id="plus",
                name="Plus",
                emoji="✨",
                tokens=30,
                stars_price=115,
                description="30 фото без водяного знака",
                order_index=2,
            ),
            Pack(
                id="pro",
                name="Pro",
                emoji="💎",
                tokens=50,
                stars_price=175,
                description="50 фото без водяного знака",
                order_index=3,
            ),
            Pack(
                id="premium",
                name="Premium",
                emoji="👑",
                tokens=80,
                stars_price=249,
                description="80 фото без водяного знака",
                order_index=4,
            ),
            Pack(
                id="ultra",
                name="Ultra",
                emoji="🚀",
                tokens=170,
                stars_price=499,
                description="170 фото без водяного знака",
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

    def build_payload(
        self,
        pack_id: str,
        user_id: str,
        job_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """
        Формирует payload для invoice (1–128 байт, лимит Telegram).
        Если строка длиннее 128 байт — сохраняем в Redis, в invoice передаём короткий токен.
        """
        nonce = str(uuid4())
        base = f"pack:{pack_id}:user:{user_id}:nonce:{nonce}"
        if job_id:
            base += f":job:{job_id}"
        if session_id:
            base += f":session:{session_id}"
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
            elif key == "session":
                result["session_id"] = val
            i += 2
        return result

    def validate_pre_checkout(
        self,
        payload: str,
        telegram_user_id: str,
        total_amount: int | None = None,
        currency: str | None = None,
    ) -> tuple[bool, str]:
        """
        Валидация pre_checkout_query.
        Returns: (ok, error_message)
        Supports payloads: yoomoney_session:{pack_id}, session:{pack_id}, upgrade:{pack_id}:{session_id}, legacy (pack:...:user:...)
        """
        # YooMoney native (RUB, amount in kopecks)
        if payload.startswith("yoomoney_session:"):
            if currency is not None and currency != "RUB":
                return False, "Неверная валюта"
            parts = payload.split(":")
            if len(parts) < 2:
                return False, "Некорректный payload"
            pack_id = parts[1]
            user = self.db.query(User).filter(User.telegram_id == telegram_user_id).one_or_none()
            if not user:
                return False, "Пользователь не найден"
            if user.is_access_blocked():
                return False, "Ваш аккаунт заблокирован"
            if not self._check_rate_limit(telegram_user_id):
                return False, "Слишком много покупок. Попробуйте позже."
            pack = self.get_pack(pack_id)
            if not pack or not pack.enabled:
                return False, "Пакет недоступен"
            if pack.is_trial and user.trial_purchased:
                return False, "Trial уже использован"
            from app.services.balance_tariffs import DISPLAY_RUB
            rub = DISPLAY_RUB.get(pack_id)
            if rub is None:
                from app.core.config import settings
                rub = round((pack.stars_price or 0) * getattr(settings, "star_to_rub", 1.3))
            expected_kopecks = rub * 100
            if total_amount is not None and total_amount != expected_kopecks:
                return False, "Неверная сумма платежа"
            return True, ""

        # New session-based payloads (Stars, XTR)
        if payload.startswith("session:") or payload.startswith("upgrade:"):
            if currency is not None and currency != "XTR":
                return False, "Неверная валюта"
            user = self.db.query(User).filter(User.telegram_id == telegram_user_id).one_or_none()
            if not user:
                return False, "Пользователь не найден"
            if user.is_access_blocked():
                return False, "Ваш аккаунт заблокирован"
            if not self._check_rate_limit(telegram_user_id):
                return False, "Слишком много покупок. Попробуйте позже."

            expected_amount: int | None = None
            if payload.startswith("session:"):
                parts = payload.split(":")
                if len(parts) < 2:
                    return False, "Некорректный payload"
                pack_id = parts[1]
                pack = self.get_pack(pack_id)
                if not pack or not pack.enabled:
                    return False, "Пакет недоступен"
                if pack.is_trial and user.trial_purchased:
                    return False, "Trial уже использован"
                expected_amount = pack.stars_price
            elif payload.startswith("upgrade:"):
                parts = payload.split(":")
                if len(parts) not in (3, 4):
                    return False, "Некорректный payload"
                pack_id, old_session_id = parts[1], parts[2]
                pack = self.get_pack(pack_id)
                if not pack or not pack.enabled:
                    return False, "Пакет недоступен"
                old_session = self.db.query(SessionModel).filter(SessionModel.id == old_session_id).one_or_none()
                if not old_session or old_session.user_id != user.id:
                    return False, "Сессия не найдена"
                old_pack = self.get_pack(old_session.pack_id)
                old_price = old_pack.stars_price if old_pack else 0
                expected_amount = max(0, (pack.stars_price or 0) - old_price)

            if total_amount is not None and expected_amount is not None and total_amount != expected_amount:
                return False, "Неверная сумма платежа"
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
        if pack_id == "unlock":
            job_id = parsed.get("job_id")
            if not job_id:
                return False, "Некорректный payload"
            job = self.db.query(Job).filter(Job.job_id == job_id).one_or_none()
            if not job or job.user_id != user.id:
                return False, "Фото не найдено"
            if getattr(job, "unlocked_at", None) or self.has_unlock_payment_for_job(job_id):
                return False, "Фото уже разблокировано"
        else:
            pack = self.get_pack(pack_id)
            if not pack or not pack.enabled:
                return False, "Пакет недоступен"

        if not self._check_rate_limit(telegram_user_id):
            return False, "Слишком много покупок. Попробуйте позже."

        if total_amount is not None:
            if pack_id == "unlock":
                from app.paywall.config import get_unlock_cost_stars
                expected_amount = get_unlock_cost_stars()
            else:
                expected_amount = pack.stars_price
            if total_amount != expected_amount:
                return False, "Неверная сумма платежа"
        if currency is not None and currency != "XTR":
            return False, "Неверная валюта"
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
                payment_processing_errors_total.labels(reason="user_not_found").inc()
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
            payment_processing_errors_total.labels(reason="duplicate").inc()
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
        payment = (
            self.db.query(Payment)
            .filter(Payment.id == payment_id)
            .with_for_update()
            .one_or_none()
        )
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

        # Session-платёж: закрыть сессию и списать HD в пределах возможного
        if payment.session_id:
            session = (
                self.db.query(SessionModel)
                .filter(SessionModel.id == payment.session_id)
                .with_for_update()
                .one_or_none()
            )
            if session:
                session.status = "refunded"
                self.db.add(session)
            pack = self.get_pack(payment.pack_id)
            if pack and (pack.hd_amount or 0) > 0:
                hd_svc = HDBalanceService(self.db)
                hd_deducted = hd_svc.debit(user, pack.hd_amount or 0)
                logger.info(
                    "refund_hd_deducted",
                    extra={"payment_id": payment_id, "user_id": user.id, "hd_deducted": hd_deducted},
                )
            self.db.flush()

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

        pay_refund_total.labels(reason="refund").inc()
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

    def record_yookassa_unlock_payment(self, order: UnlockOrder) -> Payment | None:
        """
        Записать в payments успешную оплату разблокировки по ЮKassa (централизация).
        Идемпотентно по charge_id = "yookassa_unlock:{yookassa_payment_id}".
        Вызывать из вебхука после mark_paid заказа.
        """
        if not order.yookassa_payment_id:
            return None
        charge_id = f"yookassa_unlock:{order.yookassa_payment_id}"
        existing = (
            self.db.query(Payment)
            .filter(Payment.telegram_payment_charge_id == charge_id)
            .one_or_none()
        )
        if existing:
            return existing
        user = (
            self.db.query(User)
            .filter(User.telegram_id == order.telegram_user_id)
            .one_or_none()
        )
        if not user:
            logger.warning(
                "record_yookassa_unlock_user_not_found",
                extra={"order_id": order.id, "telegram_user_id": order.telegram_user_id},
            )
            return None
        try:
            payment = Payment(
                user_id=user.id,
                telegram_payment_charge_id=charge_id,
                provider_payment_charge_id=order.yookassa_payment_id,
                pack_id="unlock",
                stars_amount=0,
                amount_kopecks=order.amount_kopecks,
                tokens_granted=0,
                status="completed",
                payload=f"yookassa_unlock:{order.yookassa_payment_id}",
                job_id=order.take_id,
                session_id=None,
            )
            self.db.add(payment)
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            logger.warning(
                "record_yookassa_unlock_duplicate",
                extra={"order_id": order.id, "charge_id": charge_id},
            )
            raise
        logger.info(
            "yookassa_unlock_payment_recorded",
            extra={
                "payment_id": payment.id,
                "order_id": order.id,
                "user_id": user.id,
                "amount_kopecks": order.amount_kopecks,
            },
        )
        try:
            ProductAnalyticsService(self.db).track_payment_event(
                "pay_success",
                user.id,
                method="yookassa_unlock",
                pack_id="unlock",
                price_rub=round((order.amount_kopecks or 0) / 100, 2),
                currency="RUB",
                source_component="service.payments",
                properties={
                    "job_id": order.take_id,
                    "flow": "unlock",
                    "order_id": order.id,
                },
            )
        except Exception as e:
            logger.warning("product_analytics track(pay_success yookassa_unlock) failed: %s", e)
        return payment

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

    def record_yookassa_trial_bundle_payment(self, order: TrialBundleOrder) -> Payment | None:
        """
        Record successful Trial bundle (unlock all 3 variants) payment in payments.
        Idempotent by charge_id = "yookassa_trial_bundle:{yookassa_payment_id}".
        """
        if not order.yookassa_payment_id:
            return None
        charge_id = f"yookassa_trial_bundle:{order.yookassa_payment_id}"
        existing = (
            self.db.query(Payment)
            .filter(Payment.telegram_payment_charge_id == charge_id)
            .one_or_none()
        )
        if existing:
            return existing
        user = (
            self.db.query(User)
            .filter(User.telegram_id == order.telegram_user_id)
            .one_or_none()
        )
        if not user:
            logger.warning(
                "record_yookassa_trial_bundle_user_not_found",
                extra={"order_id": order.id, "telegram_user_id": order.telegram_user_id},
            )
            return None
        payment = Payment(
            user_id=user.id,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id=order.yookassa_payment_id,
            pack_id="trial_bundle",
            stars_amount=0,
            amount_kopecks=order.amount_kopecks,
            tokens_granted=0,
            status="completed",
            payload=f"yookassa_trial_bundle:{order.yookassa_payment_id}",
            job_id=order.take_id,
            session_id=None,
        )
        self.db.add(payment)
        self.db.flush()
        try:
            ProductAnalyticsService(self.db).track_payment_event(
                "pay_success",
                user.id,
                method="yookassa_trial_bundle",
                pack_id="trial_bundle",
                price_rub=round((order.amount_kopecks or 0) / 100, 2),
                currency="RUB",
                source_component="service.payments",
                properties={"take_id": order.take_id, "order_id": order.id},
            )
        except Exception as e:
            logger.warning("product_analytics track(pay_success yookassa_trial_bundle) failed: %s", e)
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

    def has_unlock_payment_for_job(self, job_id: str) -> bool:
        """Есть ли успешный платёж за разблокировку этого job (защита от повторной оплаты)."""
        return (
            self.db.query(Payment.id)
            .filter(
                Payment.pack_id == "unlock",
                Payment.job_id == job_id,
                Payment.status == "completed",
            )
            .limit(1)
            .first()
            is not None
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
        target_session_id: str | None = None,
    ) -> tuple[Payment | None, SessionModel | None, str | None, int]:
        """
        Process session pack purchase: create Session, credit HD to user, record Payment.
        Attaches free Take (from pre-session) to the new session if exists.
        Returns (payment, session, None, attached_free_takes) on success; (None, None, "trial_already_used", 0) when trial was already used (caller must refund).
        """
        existing = (
            self.db.query(Payment)
            .filter(Payment.telegram_payment_charge_id == telegram_payment_charge_id)
            .one_or_none()
        )
        if existing:
            return existing, None, None, 0

        try:
            user = (
                self.db.query(User)
                .filter(User.telegram_id == telegram_user_id)
                .with_for_update()
                .one_or_none()
            )
            if not user:
                return None, None, None, 0

            pack = self.get_pack(pack_id)
            if not pack:
                return None, None, None, 0

            # Trial: claim trial_purchased before creating session, to avoid charging without delivery on race
            if pack.is_trial:
                from sqlalchemy import update as sa_update
                res = self.db.execute(
                    sa_update(User)
                    .where(User.id == user.id, (User.trial_purchased == False) | (User.trial_purchased == None))
                    .values(trial_purchased=True)
                )
                if res.rowcount == 0:
                    logger.warning(
                        "trial_already_used_on_payment",
                        extra={"telegram_user_id": telegram_user_id, "charge_id": telegram_payment_charge_id},
                    )
                    return None, None, "trial_already_used", 0

            session_svc = SessionService(self.db)
            hd_svc = HDBalanceService(self.db)

            if getattr(pack, "pack_subtype", "standalone") == "collection":
                if not pack.playlist or not isinstance(pack.playlist, list) or len(pack.playlist) == 0:
                    raise ValueError(f"Collection pack {pack_id} has no playlist — cannot sell")
                session = session_svc.create_collection_session(user.id, pack, session_id=target_session_id)
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
                try:
                    ProductAnalyticsService(self.db).track(
                        "collection_started",
                        user.id,
                        session_id=session.id,
                        pack_id=pack_id,
                    )
                except Exception as e:
                    logger.warning("product_analytics track(collection_started) failed: %s", e)
            else:
                session = session_svc.create_session(user.id, pack_id, session_id=target_session_id)
            hd_svc.credit_paid(user, pack.hd_amount or 0)

            # Attach free Take from pre-session
            attached_free_takes = 0
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
                attached_free_takes = len(free_takes)
                for take in free_takes:
                    session_svc.attach_take_to_session(take, session)
                session.takes_used = min(attached_free_takes, session.takes_limit)
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
            return payment, session, None, attached_free_takes
        except IntegrityError:
            self.db.rollback()
            logger.warning(
                "session_purchase_race",
                extra={"charge_id": telegram_payment_charge_id},
            )
            time.sleep(0.15)
            existing = (
                self.db.query(Payment)
                .filter(Payment.telegram_payment_charge_id == telegram_payment_charge_id)
                .one_or_none()
            )
            session = None
            if existing and existing.session_id:
                session = (
                    self.db.query(SessionModel)
                    .filter(SessionModel.id == existing.session_id)
                    .one_or_none()
                )
            return (existing, session, None, 0)

    def grant_session_pack_admin(
        self,
        telegram_user_id: str,
        pack_id: str,
        reference: str,
        allow_trial_regrant: bool = False,
    ) -> tuple[Payment | None, SessionModel | None, str | None]:
        """
        Ручная выдача session-pack админом (без реального платежа).
        Returns (payment, session, None) on success; (None, None, "trial_already_used") if trial already used.
        """
        user = (
            self.db.query(User)
            .filter(User.telegram_id == telegram_user_id)
            .with_for_update()
            .one_or_none()
        )
        if not user:
            return None, None, None
        pack = self.get_pack(pack_id)
        if not pack:
            return None, None, None
        if pack.is_trial and not allow_trial_regrant:
            from sqlalchemy import update as sa_update
            res = self.db.execute(
                sa_update(User)
                .where(User.id == user.id, (User.trial_purchased == False) | (User.trial_purchased == None))
                .values(trial_purchased=True)
            )
            if res.rowcount == 0:
                return None, None, "trial_already_used"
        session_svc = SessionService(self.db)
        hd_svc = HDBalanceService(self.db)
        if getattr(pack, "pack_subtype", "standalone") == "collection":
            if not pack.playlist or not isinstance(pack.playlist, list) or len(pack.playlist) == 0:
                raise ValueError(f"Collection pack {pack_id} has no playlist")
            session = session_svc.create_collection_session(user.id, pack)
        else:
            session = session_svc.create_session(user.id, pack_id)
        hd_svc.credit_paid(user, pack.hd_amount or 0)
        charge_id = f"admin_manual:{reference}"
        payload = f"admin_manual:{reference}"
        payment = Payment(
            user_id=user.id,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id=None,
            pack_id=pack_id,
            stars_amount=0,
            tokens_granted=0,
            status="completed",
            payload=payload,
            session_id=session.id,
        )
        self.db.add(payment)
        self.db.flush()
        logger.info(
            "admin_grant_session_pack",
            extra={"user_id": user.id, "pack_id": pack_id, "session_id": session.id},
        )
        return payment, session, None

    def process_session_purchase_yoomoney(
        self,
        telegram_user_id: str,
        provider_payment_charge_id: str,
        pack_id: str,
        amount_kopecks: int,
        payload: str,
        target_session_id: str | None = None,
    ) -> tuple[Payment | None, SessionModel | None, str | None, int]:
        """
        Обработка успешной оплаты через ЮMoney (нативная интеграция).
        charge_id в Payment = "yoomoney:{provider_payment_charge_id}".
        Returns (payment, session, None, attached_free_takes) on success; (None, None, "trial_already_used", 0) when trial was already used (caller must handle refund via YooKassa if needed).
        """
        charge_id = f"yoomoney:{provider_payment_charge_id}"
        existing = (
            self.db.query(Payment)
            .filter(Payment.telegram_payment_charge_id == charge_id)
            .one_or_none()
        )
        if existing:
            session = (
                self.db.query(SessionModel).filter(SessionModel.id == existing.session_id).one_or_none()
                if existing.session_id else None
            )
            return existing, session, None, 0

        try:
            user = (
                self.db.query(User)
                .filter(User.telegram_id == telegram_user_id)
                .with_for_update()
                .one_or_none()
            )
            if not user:
                return None, None, None, 0

            pack = self.get_pack(pack_id)
            if not pack:
                return None, None, None, 0

            if pack.is_trial:
                from sqlalchemy import update as sa_update
                res = self.db.execute(
                    sa_update(User)
                    .where(User.id == user.id, (User.trial_purchased == False) | (User.trial_purchased == None))
                    .values(trial_purchased=True)
                )
                if res.rowcount == 0:
                    logger.warning(
                        "trial_already_used_on_payment",
                        extra={"telegram_user_id": telegram_user_id, "charge_id": charge_id},
                    )
                    return None, None, "trial_already_used", 0

            session_svc = SessionService(self.db)
            hd_svc = HDBalanceService(self.db)

            if getattr(pack, "pack_subtype", "standalone") == "collection":
                if not pack.playlist or not isinstance(pack.playlist, list) or len(pack.playlist) == 0:
                    raise ValueError(f"Collection pack {pack_id} has no playlist — cannot sell")
                session = session_svc.create_collection_session(user.id, pack, session_id=target_session_id)
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
                try:
                    ProductAnalyticsService(self.db).track(
                        "collection_started",
                        user.id,
                        session_id=session.id,
                        pack_id=pack_id,
                    )
                except Exception as e:
                    logger.warning("product_analytics track(collection_started) failed: %s", e)
            else:
                session = session_svc.create_session(user.id, pack_id, session_id=target_session_id)
            hd_svc.credit_paid(user, pack.hd_amount or 0)

            attached_free_takes = 0
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
                attached_free_takes = len(free_takes)
                for take in free_takes:
                    session_svc.attach_take_to_session(take, session)
                session.takes_used = min(attached_free_takes, session.takes_limit)
                free_session.status = "completed"
                self.db.add(free_session)
                self.db.add(session)

            payment = Payment(
                user_id=user.id,
                telegram_payment_charge_id=charge_id,
                provider_payment_charge_id=provider_payment_charge_id,
                pack_id=pack_id,
                stars_amount=0,
                amount_kopecks=amount_kopecks,
                tokens_granted=0,
                status="completed",
                payload=payload,
                session_id=session.id,
            )
            self.db.add(payment)
            self.db.flush()

            logger.info(
                "session_purchase_yoomoney_completed",
                extra={
                    "user_id": user.id,
                    "pack_id": pack_id,
                    "session_id": session.id,
                    "hd_credited": pack.hd_amount,
                    "amount_kopecks": amount_kopecks,
                },
            )
            return payment, session, None, attached_free_takes
        except IntegrityError:
            self.db.rollback()
            logger.warning(
                "session_purchase_yoomoney_race",
                extra={"charge_id": charge_id},
            )
            time.sleep(0.15)
            existing = (
                self.db.query(Payment)
                .filter(Payment.telegram_payment_charge_id == charge_id)
                .one_or_none()
            )
            session = None
            if existing and existing.session_id:
                session = (
                    self.db.query(SessionModel)
                    .filter(SessionModel.id == existing.session_id)
                    .one_or_none()
                )
            return (existing, session, None, 0)

    def process_session_purchase_yookassa_link(
        self,
        telegram_user_id: str,
        pack_id: str,
        yookassa_payment_id: str,
        amount_kopecks: int,
    ) -> tuple[Payment | None, SessionModel | None, str | None, int]:
        """
        Обработка успешной оплаты пакета по ссылке ЮKassa (redirect).
        charge_id = "yookassa_link:{yookassa_payment_id}" для идемпотентности (webhook и pack_check вызывают один раз).
        Returns (payment, session, None, attached_free_takes) on success; (existing, session, None, 0) if already processed.
        """
        charge_id = f"yookassa_link:{yookassa_payment_id}"
        existing = (
            self.db.query(Payment)
            .filter(Payment.telegram_payment_charge_id == charge_id)
            .one_or_none()
        )
        if existing:
            session = (
                self.db.query(SessionModel).filter(SessionModel.id == existing.session_id).one_or_none()
                if existing.session_id else None
            )
            return existing, session, None, 0

        try:
            user = (
                self.db.query(User)
                .filter(User.telegram_id == telegram_user_id)
                .with_for_update()
                .one_or_none()
            )
            if not user:
                return None, None, None, 0

            pack = self.get_pack(pack_id)
            if not pack:
                return None, None, None, 0

            if pack.is_trial:
                from sqlalchemy import update as sa_update
                res = self.db.execute(
                    sa_update(User)
                    .where(User.id == user.id, (User.trial_purchased == False) | (User.trial_purchased == None))
                    .values(trial_purchased=True)
                )
                if res.rowcount == 0:
                    logger.warning(
                        "session_purchase_yookassa_link_trial_already_used",
                        extra={"telegram_user_id": telegram_user_id, "charge_id": charge_id},
                    )
                    return None, None, "trial_already_used", 0

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
                try:
                    ProductAnalyticsService(self.db).track(
                        "collection_started",
                        user.id,
                        session_id=session.id,
                        pack_id=pack_id,
                    )
                except Exception as e:
                    logger.warning("product_analytics track(collection_started) failed: %s", e)
            else:
                session = session_svc.create_session(user.id, pack_id)
            hd_svc.credit_paid(user, pack.hd_amount or 0)

            attached_free_takes = 0
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
                attached_free_takes = len(free_takes)
                for take in free_takes:
                    session_svc.attach_take_to_session(take, session)
                session.takes_used = min(attached_free_takes, session.takes_limit)
                free_session.status = "completed"
                self.db.add(free_session)
                self.db.add(session)

            payload = f"yookassa_link_pack:{pack_id}:{yookassa_payment_id}"
            payment = Payment(
                user_id=user.id,
                telegram_payment_charge_id=charge_id,
                provider_payment_charge_id=yookassa_payment_id,
                pack_id=pack_id,
                stars_amount=0,
                amount_kopecks=amount_kopecks,
                tokens_granted=0,
                status="completed",
                payload=payload,
                session_id=session.id,
            )
            self.db.add(payment)
            self.db.flush()

            logger.info(
                "session_purchase_yookassa_link_completed",
                extra={
                    "user_id": user.id,
                    "pack_id": pack_id,
                    "session_id": session.id,
                    "hd_credited": pack.hd_amount,
                    "amount_kopecks": amount_kopecks,
                },
            )
            try:
                ProductAnalyticsService(self.db).track_payment_event(
                    "pay_success",
                    user.id,
                    method="yoomoney_link",
                    session_id=session.id,
                    pack_id=pack_id,
                    price=float(pack.stars_price or 0),
                    price_rub=round((amount_kopecks or 0) / 100, 2),
                    currency="RUB",
                    source_component="service.payments",
                    properties={"amount_kopecks": amount_kopecks},
                )
            except Exception as e:
                logger.warning("product_analytics track(pay_success yoomoney_link) failed: %s", e)
            return payment, session, None, attached_free_takes
        except IntegrityError:
            self.db.rollback()
            logger.warning(
                "session_purchase_yookassa_link_race",
                extra={"charge_id": charge_id},
            )
            time.sleep(0.15)
            existing = (
                self.db.query(Payment)
                .filter(Payment.telegram_payment_charge_id == charge_id)
                .one_or_none()
            )
            session = None
            if existing and existing.session_id:
                session = (
                    self.db.query(SessionModel)
                    .filter(SessionModel.id == existing.session_id)
                    .one_or_none()
                )
            return (existing, session, None, 0)

    def process_session_purchase_bank_transfer(
        self,
        telegram_user_id: str,
        pack_id: str,
        amount_rub: float,
        reference: str,
        target_session_id: str | None = None,
        analytics_session_id: str | None = None,
    ) -> tuple[Payment | None, SessionModel | None, str | None, int]:
        """
        Обработка успешной оплаты переводом на карту для пакетов из продуктовой лестницы.
        Создаёт Session, начисляет HD, записывает Payment (charge_id = bank_transfer:{reference}).
        Returns (payment, session, None, attached_free_takes) on success; (None, None, "trial_already_used", 0) when trial already used.
        """
        charge_id = f"bank_transfer:{reference}"
        existing = (
            self.db.query(Payment)
            .filter(Payment.telegram_payment_charge_id == charge_id)
            .one_or_none()
        )
        if existing:
            session = (
                self.db.query(SessionModel).filter(SessionModel.id == existing.session_id).one_or_none()
                if existing.session_id else None
            )
            return existing, session, None, 0

        try:
            user = (
                self.db.query(User)
                .filter(User.telegram_id == telegram_user_id)
                .with_for_update()
                .one_or_none()
            )
            if not user:
                return None, None, None, 0

            pack = self.get_pack(pack_id)
            if not pack:
                return None, None, None, 0

            if pack.is_trial:
                from sqlalchemy import update as sa_update
                res = self.db.execute(
                    sa_update(User)
                    .where(User.id == user.id, (User.trial_purchased == False) | (User.trial_purchased == None))
                    .values(trial_purchased=True)
                )
                if res.rowcount == 0:
                    logger.warning(
                        "trial_already_used_on_bank_transfer",
                        extra={"telegram_user_id": telegram_user_id, "charge_id": charge_id},
                    )
                    return None, None, "trial_already_used", 0

            session_svc = SessionService(self.db)
            hd_svc = HDBalanceService(self.db)

            if getattr(pack, "pack_subtype", "standalone") == "collection":
                if not pack.playlist or not isinstance(pack.playlist, list) or len(pack.playlist) == 0:
                    raise ValueError(f"Collection pack {pack_id} has no playlist — cannot sell")
                session = session_svc.create_collection_session(user.id, pack, session_id=target_session_id)
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
                try:
                    ProductAnalyticsService(self.db).track(
                        "collection_started",
                        user.id,
                        session_id=session.id,
                        pack_id=pack_id,
                    )
                except Exception as e:
                    logger.warning("product_analytics track(collection_started) failed: %s", e)
            else:
                session = session_svc.create_session(user.id, pack_id, session_id=target_session_id)
            hd_svc.credit_paid(user, pack.hd_amount or 0)

            attached_free_takes = 0
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
                attached_free_takes = len(free_takes)
                for take in free_takes:
                    session_svc.attach_take_to_session(take, session)
                session.takes_used = min(attached_free_takes, session.takes_limit)
                free_session.status = "completed"
                self.db.add(free_session)
                self.db.add(session)

            amount_kopecks = int(round(amount_rub * 100))
            payment = Payment(
                user_id=user.id,
                telegram_payment_charge_id=charge_id,
                provider_payment_charge_id=None,
                pack_id=pack_id,
                stars_amount=0,
                amount_kopecks=amount_kopecks,
                tokens_granted=0,
                status="completed",
                payload=charge_id,
                session_id=session.id,
            )
            self.db.add(payment)
            self.db.flush()

            logger.info(
                "session_purchase_bank_transfer_completed",
                extra={
                    "user_id": user.id,
                    "pack_id": pack_id,
                    "session_id": session.id,
                    "hd_credited": pack.hd_amount,
                    "amount_rub": amount_rub,
                },
            )
            try:
                ProductAnalyticsService(self.db).track_payment_event(
                    "pay_success",
                    user.id,
                    method="bank_transfer",
                    session_id=analytics_session_id or session.id,
                    pack_id=pack_id,
                    price=float(pack.stars_price or 0),
                    price_rub=amount_rub,
                    currency="RUB",
                    source_component="service.payments",
                )
            except Exception as e:
                logger.warning("product_analytics track(pay_success bank_transfer) failed: %s", e)
            return payment, session, None, attached_free_takes
        except IntegrityError:
            self.db.rollback()
            logger.warning(
                "session_purchase_bank_transfer_race",
                extra={"charge_id": charge_id},
            )
            time.sleep(0.15)
            existing = (
                self.db.query(Payment)
                .filter(Payment.telegram_payment_charge_id == charge_id)
                .one_or_none()
            )
            session = None
            if existing and existing.session_id:
                session = (
                    self.db.query(SessionModel)
                    .filter(SessionModel.id == existing.session_id)
                    .one_or_none()
                )
            return (existing, session, None, 0)

    def process_session_upgrade(
        self,
        telegram_user_id: str,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str | None,
        new_pack_id: str,
        old_session_id: str,
        stars_amount: int,
        payload: str,
        target_session_id: str | None = None,
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

            new_session = session_svc.upgrade_session(
                old_session,
                new_pack_id,
                credit_stars,
                new_session_id=target_session_id,
            )
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
            logger.warning(
                "session_upgrade_race",
                extra={"charge_id": telegram_payment_charge_id},
            )
            time.sleep(0.15)
            existing = (
                self.db.query(Payment)
                .filter(Payment.telegram_payment_charge_id == telegram_payment_charge_id)
                .one_or_none()
            )
            new_session = None
            if existing and existing.session_id:
                new_session = (
                    self.db.query(SessionModel)
                    .filter(SessionModel.id == existing.session_id)
                    .one_or_none()
                )
            return (existing, new_session)

    # ------------------------------------------------------------------
    # Rate-limit (Redis — общий для всех воркеров/реплик бота)
    # ------------------------------------------------------------------

    def _check_rate_limit(self, telegram_user_id: str) -> bool:
        """Не более PURCHASE_RATE_LIMIT покупок за PURCHASE_RATE_WINDOW сек. Fail closed при недоступности Redis."""
        key = f"purchase_rate:{telegram_user_id}"
        try:
            current = self._redis.incr(key)
            if current == 1:
                self._redis.expire(key, PURCHASE_RATE_WINDOW)
            return current <= PURCHASE_RATE_LIMIT
        except redis.RedisError as e:
            logger.warning("purchase_rate_limit_redis_error", extra={"error": str(e)})
            return False  # fail closed: при недоступности Redis отклоняем покупку
