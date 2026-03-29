"""Subscription-gate middleware: block unsubscribed users until they join the channel."""
import logging

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from app.bot.helpers import get_db_session, t, _is_private_chat, _user_subscribed, _send_subscription_prompt
from app.bot.constants import SUBSCRIPTION_CHANNEL_USERNAME, SUBSCRIPTION_CALLBACK, SUBSCRIBE_TEXT_DEFAULT
from app.bot.keyboards import _subscription_keyboard
from app.models.user import User

logger = logging.getLogger("bot")


class SubscriptionMiddleware(BaseMiddleware):
    """
    Для новых пользователей: блокировать все действия кроме /start и кнопки «Я подписался»,
    пока не подписались на канал (subscription_channel_username). Только в личных чатах.
    """
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if not SUBSCRIPTION_CHANNEL_USERNAME:
            return await handler(event, data)
        if not _is_private_chat(event):
            return await handler(event, data)
        user_id = None
        if hasattr(event, "from_user") and event.from_user:
            user_id = str(event.from_user.id)
        elif hasattr(event, "message") and event.message and event.message.from_user:
            user_id = str(event.message.from_user.id)
        if not user_id:
            return await handler(event, data)
        try:
            with get_db_session() as db:
                user = db.query(User).filter(User.telegram_id == user_id).first()
                if not user or _user_subscribed(user):
                    return await handler(event, data)
                if isinstance(event, Message):
                    text = (event.text or "").strip()
                    if text.lower().startswith("/start"):
                        return await handler(event, data)
                    msg = event
                else:
                    if getattr(event, "data", None) == SUBSCRIPTION_CALLBACK:
                        return await handler(event, data)
                    msg = getattr(event, "message", None)
                if msg:
                    kb = _subscription_keyboard()
                    await _send_subscription_prompt(
                        msg,
                        t("subscription.prompt", SUBSCRIBE_TEXT_DEFAULT),
                        kb,
                    )
                    if isinstance(event, CallbackQuery):
                        await event.answer()
                return
        except Exception as e:
            logger.warning(f"Subscription middleware error: {e}")
            return await handler(event, data)
