"""Unit tests for SecurityMiddleware and SubscriptionMiddleware."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import redis
from aiogram.types import Chat, Message, User as TgUser

from app.bot.middleware.security import SecurityMiddleware
from app.bot.middleware.subscription import SubscriptionMiddleware
from app.bot.constants import SUBSCRIPTION_CALLBACK

from tests.bot.conftest import make_callback, make_db_user, make_message


def make_telegram_message(text="hello", chat_type="private", from_user_id="123456"):
    """Real aiogram Message so isinstance(event, Message) and data comparisons behave."""
    uid = int(from_user_id)
    return Message(
        message_id=100,
        date=datetime.now(),
        chat=Chat(id=uid, type=chat_type),
        from_user=TgUser(id=uid, is_bot=False, first_name="Test"),
        text=text,
    )


@contextmanager
def _security_settings(default=60, subscriber=120, vip_bypass=False):
    with patch("app.bot.middleware.security.SecuritySettingsService") as MockSecSvc:
        sec = SimpleNamespace(
            default_rate_limit_per_hour=default,
            subscriber_rate_limit_per_hour=subscriber,
            vip_bypass_rate_limit=vip_bypass,
        )
        MockSecSvc.return_value.get_or_create.return_value = sec
        yield MockSecSvc


@pytest.fixture(autouse=True)
def patch_middleware_get_db(mock_db):
    """Middleware imports get_db_session from helpers at import time; patch module-local names."""
    @contextmanager
    def _fake():
        yield mock_db

    with patch("app.bot.middleware.security.get_db_session", _fake):
        with patch("app.bot.middleware.subscription.get_db_session", _fake):
            yield


# ---------------------------------------------------------------------------
# SecurityMiddleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_passes_when_no_user_id():
    mw = SecurityMiddleware()
    handler = AsyncMock()
    event = make_message(text="hi")
    event.from_user = None
    data = {}

    with _security_settings():
        await mw(handler, event, data)

    handler.assert_called_once_with(event, data)


@pytest.mark.asyncio
async def test_security_passes_normal_user(mock_db):
    user = make_db_user()
    mock_db.query.return_value.filter.return_value.first.return_value = user
    mw = SecurityMiddleware()
    handler = AsyncMock()
    event = make_message(text="hi")
    data = {}

    with _security_settings():
        await mw(handler, event, data)

    handler.assert_called_once_with(event, data)


@pytest.mark.asyncio
async def test_security_blocks_banned_user(mock_db):
    user = make_db_user()
    user.is_banned = True
    user.ban_reason = "spam"
    mock_db.query.return_value.filter.return_value.first.return_value = user
    mw = SecurityMiddleware()
    handler = AsyncMock()
    event = make_message(text="hi")
    data = {}

    with _security_settings():
        await mw(handler, event, data)

    handler.assert_not_called()
    event.message.answer.assert_awaited()


@pytest.mark.asyncio
async def test_security_blocks_suspended_until_future(mock_db):
    user = make_db_user()
    user.is_suspended = True
    user.suspended_until = datetime.now(timezone.utc) + timedelta(days=1)
    user.suspend_reason = "abuse"
    mock_db.query.return_value.filter.return_value.first.return_value = user
    mw = SecurityMiddleware()
    handler = AsyncMock()
    event = make_message(text="hi")
    data = {}

    with _security_settings():
        await mw(handler, event, data)

    handler.assert_not_called()
    event.message.answer.assert_awaited()


@pytest.mark.asyncio
async def test_security_clears_expired_suspension(mock_db):
    user = make_db_user()
    user.is_suspended = True
    user.suspended_until = datetime.now(timezone.utc) - timedelta(hours=1)
    user.suspend_reason = "old"
    mock_db.query.return_value.filter.return_value.first.return_value = user
    mw = SecurityMiddleware()
    handler = AsyncMock()
    event = make_message(text="hi")
    data = {}

    with _security_settings():
        await mw(handler, event, data)

    assert user.is_suspended is False
    assert user.suspended_until is None
    assert user.suspend_reason is None
    mock_db.commit.assert_called()
    handler.assert_called_once_with(event, data)


@pytest.mark.asyncio
async def test_security_rate_limit_exceeded(mock_db, patch_redis):
    user = make_db_user()
    mock_db.query.return_value.filter.return_value.first.return_value = user
    patch_redis.incr.return_value = 61
    mw = SecurityMiddleware()
    handler = AsyncMock()
    event = make_message(text="hi")
    data = {}

    with _security_settings(default=60, subscriber=120):
        await mw(handler, event, data)

    handler.assert_not_called()
    event.message.answer.assert_awaited()


@pytest.mark.asyncio
async def test_security_rate_limit_under(mock_db, patch_redis):
    user = make_db_user()
    mock_db.query.return_value.filter.return_value.first.return_value = user
    patch_redis.incr.return_value = 1
    mw = SecurityMiddleware()
    handler = AsyncMock()
    event = make_message(text="hi")
    data = {}

    with _security_settings(default=60, subscriber=120):
        await mw(handler, event, data)

    handler.assert_called_once_with(event, data)


@pytest.mark.asyncio
async def test_security_redis_error_passes_through(mock_db, patch_redis):
    user = make_db_user()
    mock_db.query.return_value.filter.return_value.first.return_value = user
    patch_redis.incr.side_effect = redis.RedisError("unavailable")
    mw = SecurityMiddleware()
    handler = AsyncMock()
    event = make_message(text="hi")
    data = {}

    with _security_settings():
        await mw(handler, event, data)

    handler.assert_called_once_with(event, data)


@pytest.mark.asyncio
async def test_security_db_error_passes_through(mock_db):
    mock_db.query.side_effect = RuntimeError("db down")
    mw = SecurityMiddleware()
    handler = AsyncMock()
    event = make_message(text="hi")
    data = {}

    with _security_settings():
        await mw(handler, event, data)

    handler.assert_called_once_with(event, data)


# ---------------------------------------------------------------------------
# SubscriptionMiddleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscription_passes_when_channel_empty(mock_db):
    user = make_db_user(flags={})
    mock_db.query.return_value.filter.return_value.first.return_value = user
    mw = SubscriptionMiddleware()
    handler = AsyncMock()
    event = make_message(text="hello")
    data = {}

    with patch("app.bot.middleware.subscription.SUBSCRIPTION_CHANNEL_USERNAME", ""):
        await mw(handler, event, data)

    handler.assert_called_once_with(event, data)


@pytest.mark.asyncio
async def test_subscription_passes_non_private_chat(mock_db):
    user = make_db_user(flags={})
    mock_db.query.return_value.filter.return_value.first.return_value = user
    mw = SubscriptionMiddleware()
    handler = AsyncMock()
    event = make_message(text="hello", chat_type="group")
    data = {}

    with patch("app.bot.middleware.subscription.SUBSCRIPTION_CHANNEL_USERNAME", "test_channel"):
        with patch("app.bot.middleware.subscription._send_subscription_prompt", new_callable=AsyncMock):
            await mw(handler, event, data)

    handler.assert_called_once_with(event, data)


@pytest.mark.asyncio
async def test_subscription_passes_start_for_unsubscribed(mock_db):
    user = make_db_user(flags={})
    mock_db.query.return_value.filter.return_value.first.return_value = user
    mw = SubscriptionMiddleware()
    handler = AsyncMock()
    event = make_telegram_message(text="/start")
    data = {}

    with patch("app.bot.middleware.subscription.SUBSCRIPTION_CHANNEL_USERNAME", "test_channel"):
        with patch("app.bot.middleware.subscription._send_subscription_prompt", new_callable=AsyncMock):
            await mw(handler, event, data)

    handler.assert_called_once_with(event, data)


@pytest.mark.asyncio
async def test_subscription_passes_subscription_check_callback(mock_db):
    user = make_db_user(flags={})
    mock_db.query.return_value.filter.return_value.first.return_value = user
    mw = SubscriptionMiddleware()
    handler = AsyncMock()
    event = make_callback(data=SUBSCRIPTION_CALLBACK)
    data = {}

    with patch("app.bot.middleware.subscription.SUBSCRIPTION_CHANNEL_USERNAME", "test_channel"):
        with patch("app.bot.middleware.subscription._send_subscription_prompt", new_callable=AsyncMock):
            await mw(handler, event, data)

    handler.assert_called_once_with(event, data)


@pytest.mark.asyncio
async def test_subscription_blocks_unsubscribed_sends_prompt(mock_db):
    user = make_db_user(flags={})
    mock_db.query.return_value.filter.return_value.first.return_value = user
    mw = SubscriptionMiddleware()
    handler = AsyncMock()
    event = make_telegram_message(text="hello")
    data = {}

    with patch("app.bot.middleware.subscription.SUBSCRIPTION_CHANNEL_USERNAME", "test_channel"):
        with patch("app.bot.middleware.subscription._send_subscription_prompt", new_callable=AsyncMock) as mock_prompt:
            await mw(handler, event, data)

    handler.assert_not_called()
    mock_prompt.assert_awaited()


@pytest.mark.asyncio
async def test_subscription_passes_subscribed_user(mock_db):
    user = make_db_user(flags={"subscribed_examples_channel": True})
    mock_db.query.return_value.filter.return_value.first.return_value = user
    mw = SubscriptionMiddleware()
    handler = AsyncMock()
    event = make_telegram_message(text="hello")
    data = {}

    with patch("app.bot.middleware.subscription.SUBSCRIPTION_CHANNEL_USERNAME", "test_channel"):
        with patch("app.bot.middleware.subscription._send_subscription_prompt", new_callable=AsyncMock):
            await mw(handler, event, data)

    handler.assert_called_once_with(event, data)


@pytest.mark.asyncio
async def test_subscription_passes_user_not_in_db(mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mw = SubscriptionMiddleware()
    handler = AsyncMock()
    event = make_telegram_message(text="hello")
    data = {}

    with patch("app.bot.middleware.subscription.SUBSCRIPTION_CHANNEL_USERNAME", "test_channel"):
        with patch("app.bot.middleware.subscription._send_subscription_prompt", new_callable=AsyncMock):
            await mw(handler, event, data)

    handler.assert_called_once_with(event, data)
