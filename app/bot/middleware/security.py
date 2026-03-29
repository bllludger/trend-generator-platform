"""Security middleware: ban / suspend / rate-limit checks."""
import logging
from datetime import datetime, timezone, timedelta

import redis
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from app.bot.helpers import get_db_session, redis_client, tr
from app.services.security.settings_service import SecuritySettingsService
from app.models.user import User

logger = logging.getLogger("bot")


async def _notify_block(event: TelegramObject, text: str, *, dedupe_key: str | None = None, dedupe_ttl: int = 20) -> None:
    """Показать блокирующее сообщение: для callback — alert, для message — ответ в чат (с антиспамом)."""
    if dedupe_key:
        try:
            if redis_client.get(dedupe_key):
                return
            redis_client.setex(dedupe_key, dedupe_ttl, "1")
        except Exception:
            pass
    if isinstance(event, CallbackQuery):
        try:
            await event.answer(text, show_alert=True)
            return
        except Exception:
            pass
    msg = event if isinstance(event, Message) else getattr(event, "message", None)
    if msg:
        try:
            await msg.answer(text)
        except Exception:
            pass


async def _send_rate_limit_emoji_once(event: TelegramObject, user_id: str) -> None:
    """Отправить отдельный эмодзи 🫠 один раз в час перед текстом лимита."""
    hour_key = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    once_key = f"notify:rate_limit_emoji:{user_id}:{hour_key}"
    try:
        if redis_client.get(once_key):
            return
        redis_client.setex(once_key, 3600, "1")
    except Exception:
        pass
    msg = event if isinstance(event, Message) else getattr(event, "message", None)
    if msg:
        try:
            await msg.answer("🫠")
        except Exception:
            pass


class SecurityMiddleware(BaseMiddleware):
    """
    Middleware to check user access:
    1. Check if user is banned → block
    2. Check if user is suspended → block until expires
    3. Check rate limit → block if exceeded
    """

    async def __call__(
        self,
        handler,
        event: TelegramObject,
        data: dict,
    ):
        user_id = None
        if hasattr(event, 'from_user') and event.from_user:
            user_id = str(event.from_user.id)
        elif hasattr(event, 'message') and event.message and event.message.from_user:
            user_id = str(event.message.from_user.id)

        if not user_id:
            return await handler(event, data)

        try:
            with get_db_session() as db:
                user = db.query(User).filter(User.telegram_id == user_id).first()

                if user:
                    if user.is_banned:
                        await _notify_block(
                            event,
                            tr("errors.banned", "🚫 Ваш аккаунт заблокирован.\n\nПричина: {reason}", reason=user.ban_reason or "Не указана"),
                            dedupe_key=f"notify:banned:{user_id}",
                        )
                        logger.warning("Blocked banned user", extra={"user_id": user_id})
                        return

                    if user.is_suspended and user.suspended_until:
                        if datetime.now(timezone.utc) < user.suspended_until:
                            until_str = user.suspended_until.strftime("%d.%m.%Y %H:%M")
                            await _notify_block(
                                event,
                                tr(
                                    "errors.suspended",
                                    "⏸ Ваш аккаунт временно приостановлен до {until}.\n\nПричина: {reason}",
                                    until=until_str,
                                    reason=user.suspend_reason or "Не указана",
                                ),
                                dedupe_key=f"notify:suspended:{user_id}",
                            )
                            logger.warning("Blocked suspended user", extra={"user_id": user_id})
                            return
                        else:
                            user.is_suspended = False
                            user.suspended_until = None
                            user.suspend_reason = None
                            db.commit()

                    sec_svc = SecuritySettingsService(db)
                    sec = sec_svc.get_or_create()
                    vip_bypass = bool(sec.vip_bypass_rate_limit and (user.flags or {}).get("VIP"))
                    if not vip_bypass:
                        base_rate_limit = user.get_effective_rate_limit(
                            default=sec.default_rate_limit_per_hour,
                            subscriber_limit=sec.subscriber_rate_limit_per_hour,
                        )
                        # Product requirement: increase request limits by x2.
                        rate_limit = max(1, int(base_rate_limit) * 2)
                        rate_key = f"rate_limit:{user_id}:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"

                        try:
                            current = redis_client.incr(rate_key)
                            if current == 1:
                                redis_client.expire(rate_key, 3600)

                            if current > rate_limit:
                                now_local = datetime.now().astimezone()
                                resume_at = (now_local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).strftime("%H:%M")
                                await _send_rate_limit_emoji_once(event, user_id)
                                await _notify_block(
                                    event,
                                    tr(
                                        "errors.rate_limit",
                                        "⚠️ Слишком быстро\n\nВы отправили много запросов подряд.\nСделаем небольшую паузу и продолжим.\n\nПопробуйте снова после {resume_time}.",
                                        resume_time=resume_at,
                                    ),
                                    dedupe_key=f"notify:rate_limit:{user_id}",
                                )
                                logger.warning("Rate limit exceeded", extra={"user_id": user_id, "limit": rate_limit})
                                return
                        except redis.RedisError as e:
                            logger.warning(f"Redis error in rate limit check: {e}")
                else:
                    sec_svc = SecuritySettingsService(db)
                    sec = sec_svc.get_or_create()
                    rate_limit = max(1, int(sec.default_rate_limit_per_hour) * 2)
                    rate_key = f"rate_limit:{user_id}:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
                    try:
                        current = redis_client.incr(rate_key)
                        if current == 1:
                            redis_client.expire(rate_key, 3600)
                        if current > rate_limit:
                            now_local = datetime.now().astimezone()
                            resume_at = (now_local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).strftime("%H:%M")
                            await _send_rate_limit_emoji_once(event, user_id)
                            await _notify_block(
                                event,
                                tr(
                                    "errors.rate_limit",
                                    "⚠️ Слишком быстро\n\nВы отправили много запросов подряд.\nСделаем небольшую паузу и продолжим.\n\nПопробуйте снова после {resume_time}.",
                                    resume_time=resume_at,
                                ),
                                dedupe_key=f"notify:rate_limit:{user_id}",
                            )
                            return
                    except redis.RedisError:
                        pass
        except Exception as e:
            logger.warning(f"Security middleware error: {e}")

        return await handler(event, data)
