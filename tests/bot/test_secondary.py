"""Unit tests for secondary bot handler modules (commands, bank_transfer, trial, favorites, session, fallback)."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Router
from aiogram.types import ErrorEvent, InlineKeyboardMarkup

from app.bot.handlers.bank_transfer import bank_pack_selected, bank_transfer_start
from app.bot.handlers.commands import cmd_cancel, cmd_help, cmd_trends
from app.bot.handlers.fallback import handle_error_recovery, on_error, unknown_message
from app.bot.handlers.favorites import favorites_router, open_favorites
from app.bot.handlers.session import session_router
from app.bot.handlers.trial import trial_router
from app.bot.states import BotStates
from tests.bot.conftest import make_callback, make_db_user, make_message


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cmd_help_answers_markdown():
    msg = make_message(text="/help")
    with patch("app.bot.handlers.commands.get_db_session") as mock_gs:

        @contextmanager
        def _fake():
            yield MagicMock()

        mock_gs.side_effect = _fake
        with patch("app.bot.handlers.commands.UserService"), patch(
            "app.bot.handlers.commands.ProductAnalyticsService"
        ):
            await cmd_help(msg)
    msg.answer.assert_called_once()
    kw = msg.answer.call_args.kwargs
    assert kw.get("parse_mode") == "Markdown"


@pytest.mark.asyncio
async def test_cmd_cancel_clears_state(mock_state):
    msg = make_message(text="/cancel")
    with patch("app.bot.handlers.commands.get_db_session") as mock_gs:

        @contextmanager
        def _fake():
            yield MagicMock()

        mock_gs.side_effect = _fake
        with patch("app.bot.handlers.commands.UserService"), patch(
            "app.bot.handlers.commands.ProductAnalyticsService"
        ):
            await cmd_cancel(msg, mock_state)
    mock_state.clear.assert_called_once()
    msg.answer.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_trends_answers():
    msg = make_message(text="/trends")
    with patch("app.bot.handlers.commands.get_db_session") as mock_gs:

        @contextmanager
        def _fake():
            yield MagicMock()

        mock_gs.side_effect = _fake
        with patch("app.bot.handlers.commands.UserService"), patch(
            "app.bot.handlers.commands.ProductAnalyticsService"
        ):
            await cmd_trends(msg)
    msg.answer.assert_called_once()


# ---------------------------------------------------------------------------
# Bank transfer
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bank_pack_selected_imports_from_keyboards(mock_state):
    cb = make_callback(data="bank_pack:starter")
    with patch("app.bot.handlers.bank_transfer.get_db_session") as mock_gs:

        @contextmanager
        def _fake():
            yield MagicMock()

        mock_gs.side_effect = _fake
        with patch(
            "app.bot.keyboards._payment_method_keyboard",
            return_value=InlineKeyboardMarkup(inline_keyboard=[]),
        ):
            await bank_pack_selected(cb, mock_state)
    mock_state.clear.assert_called_once()
    cb.answer.assert_called_once()
    cb.message.answer.assert_called_once()
    text = cb.message.answer.call_args[0][0]
    assert "магазин" in text.lower() or "юmoney" in text.lower()


@pytest.mark.asyncio
async def test_bank_pack_selected_ladder_calls_payment_keyboard(mock_state):
    cb = make_callback(data="bank_pack:trial")
    fake_kb = InlineKeyboardMarkup(inline_keyboard=[])
    with patch("app.bot.handlers.bank_transfer.get_db_session") as mock_gs:

        @contextmanager
        def _fake():
            yield MagicMock()

        mock_gs.side_effect = _fake
        with patch(
            "app.bot.keyboards._payment_method_keyboard", return_value=fake_kb
        ) as pmk:
            await bank_pack_selected(cb, mock_state)
    pmk.assert_called_once_with("trial")
    cb.message.answer.assert_called_once()
    assert "юmoney" in cb.message.answer.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_bank_transfer_start_answers(mock_state):
    cb = make_callback(data="bank_transfer:start")
    await bank_transfer_start(cb, mock_state)
    mock_state.clear.assert_called_once()
    cb.answer.assert_called_once()
    cb.message.answer.assert_called_once()
    text = cb.message.answer.call_args[0][0]
    assert "магазин" in text.lower() or "юmoney" in text.lower()


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
def test_trial_router_exists():
    assert isinstance(trial_router, Router)


def test_favorites_router_exists():
    assert isinstance(favorites_router, Router)


def test_session_router_exists():
    assert isinstance(session_router, Router)


# ---------------------------------------------------------------------------
# Favorites
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_open_favorites_answers(mock_state):
    cb = make_callback(data="open_favorites")
    with patch("app.bot.handlers.favorites.get_db_session") as mock_gs:

        @contextmanager
        def _fake():
            yield MagicMock()

        mock_gs.side_effect = _fake
        with patch(
            "app.bot.handlers.favorites._build_favorites_message",
            return_value=("Избранное (тест)", [], 2),
        ), patch("app.bot.handlers.favorites.UserService") as us_cls, patch(
            "app.bot.handlers.favorites.ProductAnalyticsService"
        ), patch("app.bot.handlers.favorites.AuditService"):
            us_cls.return_value.get_or_create_user.return_value = make_db_user()
            await open_favorites(cb, mock_state)
    cb.message.answer.assert_called_once_with(
        "Избранное (тест)", reply_markup=None
    )
    mock_state.set_state.assert_called_once_with(BotStates.viewing_favorites)
    cb.answer.assert_called_once()


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_handle_error_recovery_menu_action(mock_state):
    cb = make_callback(data="error_action:menu")
    with patch("app.bot.handlers.fallback.get_db_session") as mock_gs:

        @contextmanager
        def _fake():
            yield MagicMock()

        mock_gs.side_effect = _fake
        with patch("app.bot.handlers.fallback.UserService"), patch(
            "app.bot.handlers.fallback.ProductAnalyticsService"
        ):
            await handle_error_recovery(cb, mock_state)
    mock_state.clear.assert_called_once()
    cb.message.answer.assert_called_once()
    cb.answer.assert_called_once()


@pytest.mark.asyncio
async def test_handle_error_recovery_retry_action(mock_state):
    cb = make_callback(data="error_action:retry")
    with patch("app.bot.handlers.fallback.get_db_session") as mock_gs:

        @contextmanager
        def _fake():
            yield MagicMock()

        mock_gs.side_effect = _fake
        with patch("app.bot.handlers.fallback.UserService"), patch(
            "app.bot.handlers.fallback.ProductAnalyticsService"
        ):
            await handle_error_recovery(cb, mock_state)
    mock_state.clear.assert_called_once()
    cb.message.answer.assert_called_once()
    cb.answer.assert_called_once()


@pytest.mark.asyncio
async def test_unknown_message_no_state(mock_state):
    mock_state.get_state = AsyncMock(return_value=None)
    msg = make_message(text="???")
    await unknown_message(msg, mock_state)
    msg.answer.assert_called_once()


@pytest.mark.asyncio
async def test_unknown_message_waiting_for_photo(mock_state):
    mock_state.get_state = AsyncMock(return_value=BotStates.waiting_for_photo)
    msg = make_message(text="not a photo")
    await unknown_message(msg, mock_state)
    msg.answer.assert_called_once()
    called_text = msg.answer.call_args[0][0]
    assert "фото" in called_text.lower() or "создать" in called_text.lower()


@pytest.mark.asyncio
async def test_unknown_message_group_chat_ignored(mock_state):
    mock_state.get_state = AsyncMock(return_value=None)
    msg = make_message(text="hello", chat_type="group")
    await unknown_message(msg, mock_state)
    msg.answer.assert_not_called()


@pytest.mark.asyncio
async def test_on_error_logs_exception():
    event = MagicMock(spec=ErrorEvent)
    event.exception = RuntimeError("test error")
    with patch("app.bot.handlers.fallback.logger") as log:
        await on_error(event)
    log.exception.assert_called_once()
    assert "Error in handler" in log.exception.call_args[0][0]


@pytest.mark.asyncio
async def test_on_error_does_not_crash():
    event = MagicMock(spec=ErrorEvent)
    event.exception = RuntimeError("test error")
    with patch("app.bot.handlers.fallback.logger"):
        await on_error(event)


@pytest.mark.asyncio
async def test_session_status_trial_shows_all_neo_tariffs():
    from app.bot.handlers.session import session_status

    cb = make_callback(data="session_status")
    state = AsyncMock()

    session_obj = SimpleNamespace(
        id="sess-1",
        pack_id="trial",
        takes_used=2,
        takes_limit=15,
        hd_limit=15,
    )
    user = make_db_user()

    mock_user_svc = MagicMock()
    mock_user_svc.get_or_create_user.return_value = user

    mock_session_svc = MagicMock()
    mock_session_svc.get_active_session.return_value = session_obj
    mock_session_svc.is_collection.return_value = False
    mock_session_svc.hd_remaining.return_value = 13

    mock_hd_svc = MagicMock()
    mock_hd_svc.get_balance.return_value = {"total": 13}

    mock_fav_svc = MagicMock()
    mock_fav_svc.count_favorites.return_value = 0
    mock_fav_svc.count_selected_for_hd.return_value = 0

    with patch("app.bot.handlers.session.get_db_session") as mock_gs:

        @contextmanager
        def _fake():
            yield MagicMock()

        mock_gs.side_effect = _fake
        with patch("app.bot.handlers.session.UserService", return_value=mock_user_svc), patch(
            "app.bot.handlers.session.SessionService", return_value=mock_session_svc
        ), patch("app.bot.handlers.session.HDBalanceService", return_value=mock_hd_svc), patch(
            "app.bot.handlers.session.FavoriteService", return_value=mock_fav_svc
        ), patch(
            "app.bot.handlers.session.ProductAnalyticsService"
        ):
            await session_status(cb, state)

    cb.message.answer.assert_awaited()
    reply_markup = cb.message.answer.await_args.kwargs["reply_markup"]
    texts = [btn.text for row in reply_markup.inline_keyboard for btn in row]
    assert any("Neo Start" in t and "199" in t for t in texts)
    assert any("Neo Pro" in t and "499" in t for t in texts)
    assert any("Neo Unlimited" in t and "990" in t for t in texts)


@pytest.mark.asyncio
async def test_unlock_check_succeeded_records_payment_and_enqueues_delivery():
    from app.bot.handlers.session import unlock_check_callback

    cb = make_callback(data="unlock_check:ord-1")
    order = SimpleNamespace(
        id="ord-1",
        telegram_user_id="123456",
        status="payment_pending",
        yookassa_payment_id="pay-1",
        amount_kopecks=9900,
        take_id="take-1",
    )
    user = make_db_user()
    unlock_svc = MagicMock()
    unlock_svc.get_by_id.return_value = order

    with patch("app.bot.handlers.session.get_db_session") as mock_gs:

        @contextmanager
        def _fake():
            db = MagicMock()
            yield db

        mock_gs.side_effect = _fake
        with patch("app.bot.handlers.session.IdempotencyStore") as lock_cls, patch(
            "app.bot.handlers.session.UnlockOrderService", return_value=unlock_svc
        ), patch("app.bot.handlers.session.UserService") as user_cls, patch(
            "app.bot.handlers.session.ProductAnalyticsService"
        ), patch(
            "app.bot.handlers.session.YooKassaClient"
        ) as yoo_cls, patch(
            "app.bot.handlers.session.PaymentService"
        ) as pay_cls, patch(
            "app.core.celery_app.celery_app.send_task"
        ) as send_task:
            lock_cls.return_value.check_and_set.return_value = True
            user_cls.return_value.get_by_telegram_id.return_value = user
            yoo_cls.return_value.is_configured.return_value = True
            yoo_cls.return_value.get_payment.return_value = {"status": "succeeded"}
            await unlock_check_callback(cb)

    unlock_svc.mark_paid.assert_called_once_with(order_id="ord-1")
    pay_cls.return_value.record_yookassa_unlock_payment.assert_called_once_with(order)
    send_task.assert_called_once()
    cb.answer.assert_awaited()


@pytest.mark.asyncio
async def test_unlock_check_pending_does_not_mark_paid_or_enqueue():
    from app.bot.handlers.session import unlock_check_callback

    cb = make_callback(data="unlock_check:ord-1")
    order = SimpleNamespace(
        id="ord-1",
        telegram_user_id="123456",
        status="payment_pending",
        yookassa_payment_id="pay-1",
        amount_kopecks=9900,
        take_id="take-1",
    )
    user = make_db_user()
    unlock_svc = MagicMock()
    unlock_svc.get_by_id.return_value = order

    with patch("app.bot.handlers.session.get_db_session") as mock_gs:

        @contextmanager
        def _fake():
            db = MagicMock()
            yield db

        mock_gs.side_effect = _fake
        with patch("app.bot.handlers.session.IdempotencyStore") as lock_cls, patch(
            "app.bot.handlers.session.UnlockOrderService", return_value=unlock_svc
        ), patch("app.bot.handlers.session.UserService") as user_cls, patch(
            "app.bot.handlers.session.ProductAnalyticsService"
        ), patch(
            "app.bot.handlers.session.YooKassaClient"
        ) as yoo_cls, patch(
            "app.core.celery_app.celery_app.send_task"
        ) as send_task:
            lock_cls.return_value.check_and_set.return_value = True
            user_cls.return_value.get_by_telegram_id.return_value = user
            yoo_cls.return_value.is_configured.return_value = True
            yoo_cls.return_value.get_payment.return_value = {"status": "pending"}
            await unlock_check_callback(cb)

    unlock_svc.mark_paid.assert_not_called()
    send_task.assert_not_called()
    cb.answer.assert_awaited()
    assert "пока не поступила" in (cb.answer.await_args_list[-1].args[0] or "").lower()
