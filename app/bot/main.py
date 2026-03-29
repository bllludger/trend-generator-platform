"""
Telegram bot using aiogram 3.x — bootstrap entry point.

All handlers are in app.bot.handlers.* modules;
shared code lives in app.bot.helpers, keyboards, states, constants.
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

from app.core.config import settings
from app.core.logging import configure_logging
from app.bot.helpers import patch_aiogram_message_methods, get_db_session
from app.bot.middleware.security import SecurityMiddleware
from app.bot.middleware.subscription import SubscriptionMiddleware
from app.bot.handlers import all_routers
from app.bot.handlers.fallback import on_error
from app.services.telegram_messages.runtime import runtime_templates

configure_logging()
logger = logging.getLogger("bot")


async def main():
    """Start the bot."""
    logger.info("Starting bot...")

    try:
        from app.utils.metrics_server import start_metrics_http_server
        _metrics_port = int(os.environ.get("BOT_METRICS_PORT", "8002"))
        start_metrics_http_server(port=_metrics_port)
    except Exception as e:
        logger.warning("Could not start metrics server: %s", e)

    patch_aiogram_message_methods()

    bot = Bot(token=settings.telegram_bot_token)
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)

    dp.errors.register(on_error)

    dp.message.middleware(SecurityMiddleware())
    dp.callback_query.middleware(SecurityMiddleware())
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    for router in all_routers:
        dp.include_router(router)

    runtime_templates.start_listener()

    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Bot started successfully!")

    try:
        with get_db_session() as db:
            from app.services.payments.service import PaymentService as _PS
            _PS(db).seed_default_packs()
    except Exception:
        logger.warning("Failed to seed default packs on startup")

    try:
        await dp.start_polling(
            bot,
            allowed_updates=[
                "message",
                "callback_query",
                "pre_checkout_query",
            ],
        )
    finally:
        runtime_templates.stop_listener()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
