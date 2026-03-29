"""Tests for /start and subscription_check handlers."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Router

from app.bot.handlers.start import cmd_start, start_router, subscription_check
from app.bot.states import BotStates
from tests.bot.conftest import make_callback, make_db_user, make_message, make_session


def test_start_router_exists():
    assert isinstance(start_router, Router)


@pytest.mark.asyncio
async def test_cmd_start_new_user_sends_welcome(mock_state, mock_bot):
    msg = make_message(text="/start")
    user = make_db_user()
    with patch("app.bot.handlers.start.SUBSCRIPTION_CHANNEL_USERNAME", ""), patch(
        "app.bot.handlers.start._user_subscribed", return_value=True
    ), patch("app.bot.handlers.start.get_db_session") as mock_gs, patch(
        "app.bot.handlers.start.UserService"
    ) as MockUS, patch("app.bot.handlers.start.AuditService"), patch(
        "app.bot.handlers.start.ProductAnalyticsService"
    ), patch("app.bot.handlers.start.SessionService") as MockSS, patch(
        "app.bot.handlers.start.PaymentService"
    ), patch("app.bot.handlers.start.ReferralService"), patch(
        "app.bot.handlers.start.bot_started_total"
    ), patch("app.bot.handlers.start.os.path.exists", return_value=False):
        db = MagicMock()

        @contextmanager
        def _fake():
            yield db

        mock_gs.side_effect = lambda: _fake()
        MockUS.return_value.get_or_create_user.return_value = user
        MockUS.return_value.get_by_telegram_id.return_value = user
        MockSS.return_value.get_active_session.return_value = make_session()
        await cmd_start(msg, mock_state)
    assert msg.answer.await_count + msg.answer_photo.await_count >= 1


@pytest.mark.asyncio
async def test_cmd_start_with_referral_deeplink(mock_state, mock_bot):
    msg = make_message(text="/start ref_ABC123")
    user = make_db_user()
    with patch("app.bot.handlers.start.SUBSCRIPTION_CHANNEL_USERNAME", ""), patch(
        "app.bot.handlers.start._user_subscribed", return_value=True
    ), patch("app.bot.handlers.start.get_db_session") as mock_gs, patch(
        "app.bot.handlers.start.UserService"
    ) as MockUS, patch("app.bot.handlers.start.AuditService"), patch(
        "app.bot.handlers.start.ProductAnalyticsService"
    ), patch("app.bot.handlers.start.SessionService"), patch(
        "app.bot.handlers.start.PaymentService"
    ), patch("app.bot.handlers.start.ReferralService") as MockRS, patch(
        "app.bot.handlers.start.bot_started_total"
    ), patch("app.bot.handlers.start.os.path.exists", return_value=False):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        @contextmanager
        def _fake():
            yield db

        mock_gs.side_effect = lambda: _fake()
        MockUS.return_value.get_or_create_user.return_value = user
        MockUS.return_value.get_by_telegram_id.return_value = user
        MockRS.return_value.attribute.return_value = False
        await cmd_start(msg, mock_state)
    MockRS.return_value.attribute.assert_called_once()
    call_kw = MockRS.return_value.attribute.call_args
    assert call_kw[0][1] == "ABC123"


@pytest.mark.asyncio
async def test_cmd_start_with_trend_deeplink(mock_state, mock_bot):
    msg = make_message(text="/start trend_abc")
    user = make_db_user()
    trend = SimpleNamespace(id="trend-abc", name="Test trend", enabled=True)
    with patch("app.bot.handlers.start.SUBSCRIPTION_CHANNEL_USERNAME", ""), patch(
        "app.bot.handlers.start._user_subscribed", return_value=True
    ), patch("app.bot.handlers.start.get_db_session") as mock_gs, patch(
        "app.bot.handlers.start.UserService"
    ) as MockUS, patch("app.bot.handlers.start.AuditService"), patch(
        "app.bot.handlers.start.ProductAnalyticsService"
    ), patch("app.bot.handlers.start.SessionService"), patch(
        "app.bot.handlers.start.PaymentService"
    ), patch("app.bot.handlers.start.ReferralService"), patch(
        "app.bot.handlers.start.TrendService"
    ) as MockTS, patch("app.bot.handlers.start.bot_started_total"), patch(
        "app.bot.handlers.start.os.path.exists", return_value=False
    ):
        db = MagicMock()

        @contextmanager
        def _fake():
            yield db

        mock_gs.side_effect = lambda: _fake()
        MockUS.return_value.get_or_create_user.return_value = user
        MockUS.return_value.get_by_telegram_id.return_value = user
        MockTS.return_value.get.return_value = trend
        await cmd_start(msg, mock_state)
    mock_state.set_state.assert_awaited()
    set_args = [c.args[0] for c in mock_state.set_state.await_args_list]
    assert BotStates.waiting_for_photo in set_args


@pytest.mark.asyncio
async def test_cmd_start_db_error_graceful(mock_state, mock_bot):
    msg = make_message(text="/start")
    with patch("app.bot.handlers.start.get_db_session") as mock_gs, patch(
        "app.bot.handlers.start.UserService"
    ) as MockUS, patch("app.bot.handlers.start.os.path.exists", return_value=False):
        db = MagicMock()

        @contextmanager
        def _fake():
            yield db

        mock_gs.side_effect = lambda: _fake()
        MockUS.return_value.get_or_create_user.side_effect = RuntimeError("db down")
        await cmd_start(msg, mock_state)
    msg.answer.assert_awaited()


@pytest.mark.asyncio
async def test_cmd_start_trend_disabled_falls_through_to_welcome(mock_state, mock_bot):
    msg = make_message(text="/start trend_xyz")
    user = make_db_user()
    trend = SimpleNamespace(id="trend-x", name="Off", enabled=False)
    with patch("app.bot.handlers.start.SUBSCRIPTION_CHANNEL_USERNAME", ""), patch(
        "app.bot.handlers.start._user_subscribed", return_value=True
    ), patch("app.bot.handlers.start.get_db_session") as mock_gs, patch(
        "app.bot.handlers.start.UserService"
    ) as MockUS, patch("app.bot.handlers.start.AuditService"), patch(
        "app.bot.handlers.start.ProductAnalyticsService"
    ), patch("app.bot.handlers.start.SessionService"), patch(
        "app.bot.handlers.start.PaymentService"
    ), patch("app.bot.handlers.start.ReferralService"), patch(
        "app.bot.handlers.start.TrendService"
    ) as MockTS, patch("app.bot.handlers.start.bot_started_total"), patch(
        "app.bot.handlers.start.os.path.exists", return_value=False
    ):
        db = MagicMock()

        @contextmanager
        def _fake():
            yield db

        mock_gs.side_effect = lambda: _fake()
        MockUS.return_value.get_or_create_user.return_value = user
        MockUS.return_value.get_by_telegram_id.return_value = user
        MockTS.return_value.get.return_value = trend
        await cmd_start(msg, mock_state)
    photo_state_calls = [
        c.args[0]
        for c in mock_state.set_state.await_args_list
        if c.args and c.args[0] == BotStates.waiting_for_photo
    ]
    assert not photo_state_calls
    assert msg.answer.await_count + msg.answer_photo.await_count >= 1


@pytest.mark.asyncio
async def test_subscription_check_subscribed(mock_state, mock_bot):
    mock_state.get_data = AsyncMock(return_value={})
    cb = make_callback(data="subscription_check")
    mock_bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="member"))
    user = make_db_user()
    with patch("app.bot.handlers.start.SUBSCRIPTION_CHANNEL_USERNAME", "news_channel"), patch(
        "app.bot.handlers.start.get_db_session"
    ) as mock_gs, patch("app.bot.handlers.start.UserService") as MockUS, patch(
        "app.bot.handlers.start.AuditService"
    ), patch("app.bot.handlers.start.TrendService"), patch(
        "app.bot.handlers.start.ThemeService"
    ), patch("app.bot.handlers.start.os.path.exists", return_value=False):

        @contextmanager
        def _fake():
            yield MagicMock()

        mock_gs.side_effect = lambda: _fake()
        MockUS.return_value.get_by_telegram_id.return_value = user
        await subscription_check(cb, mock_state, mock_bot)
    assert cb.message.answer.await_count >= 1
    assert cb.answer.await_count >= 1
    assert "Спасибо" in str(cb.answer.call_args)


@pytest.mark.asyncio
async def test_subscription_check_not_subscribed(mock_state, mock_bot):
    mock_state.get_data = AsyncMock(return_value={})
    cb = make_callback(data="subscription_check")
    mock_bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="left"))
    with patch("app.bot.handlers.start.SUBSCRIPTION_CHANNEL_USERNAME", "news_channel"):
        await subscription_check(cb, mock_state, mock_bot)
    cb.answer.assert_awaited()
    assert cb.answer.call_args.kwargs.get("show_alert") is True
    assert "подпишитесь" in str(cb.answer.call_args).lower()
