"""Tests for merge, copy_style, rescue, and results bot flows."""
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Router
from aiogram.types import InlineKeyboardMarkup

from app.bot.handlers.copy_style import copy_flow_wrong_input_ref, copy_style_router
from app.bot.handlers.merge import (
    merge_count_selected,
    merge_router,
    merge_wrong_input_1,
    start_merge_flow,
)
from app.bot.handlers.rescue import rescue_reason_more, rescue_router
from app.bot.handlers.results import (
    _pack_activated_message_and_keyboard,
    choose_variant,
    results_router,
)
from app.bot.states import BotStates
from tests.bot.conftest import make_callback, make_db_user, make_message, make_session


def test_merge_router_exists():
    assert isinstance(merge_router, Router)


@pytest.mark.asyncio
async def test_start_merge_flow_sets_state(mock_state, mock_bot):
    msg = make_message(text="🧩 Соединить фото")
    with patch("app.bot.handlers.merge.get_db_session") as mock_gs, patch(
        "app.bot.handlers.merge.UserService"
    ) as MockUS, patch("app.bot.handlers.merge.ProductAnalyticsService"), patch(
        "app.bot.handlers.merge.PhotoMergeSettingsService"
    ) as MockPM, patch("app.bot.handlers.merge.AuditService"), patch(
        "app.bot.handlers.merge.os.path.isfile", return_value=False
    ):
        MockPM.return_value.as_dict.return_value = {"enabled": True, "max_input_file_mb": 20}
        MockUS.return_value.get_or_create_user.return_value = MagicMock()

        @contextmanager
        def _fake():
            yield MagicMock()

        mock_gs.side_effect = lambda: _fake()
        await start_merge_flow(msg, mock_state)
    mock_state.set_state.assert_awaited()
    assert BotStates.merge_waiting_count in [c.args[0] for c in mock_state.set_state.await_args_list]


@pytest.mark.asyncio
async def test_merge_count_selected_sets_photo_state(mock_state, mock_bot):
    cb = make_callback(data="merge_count:2")
    with patch("app.bot.handlers.merge._edit_message_text_or_caption", new_callable=AsyncMock):
        await merge_count_selected(cb, mock_state)
    mock_state.set_state.assert_awaited()
    assert BotStates.merge_waiting_photo_1 in [c.args[0] for c in mock_state.set_state.await_args_list]


@pytest.mark.asyncio
async def test_merge_wrong_input_answers_hint(mock_state, mock_bot):
    msg = make_message(text="not a photo")
    await merge_wrong_input_1(msg)
    msg.answer.assert_awaited()
    text = str(msg.answer.call_args[0][0]).lower()
    assert "отправьте фото" in text or "фото" in text


def test_copy_style_router_exists():
    assert isinstance(copy_style_router, Router)


@pytest.mark.asyncio
async def test_copy_flow_wrong_input_ref_answers(mock_state, mock_bot):
    msg = make_message(text="plain text")
    await copy_flow_wrong_input_ref(msg)
    msg.answer.assert_awaited()
    assert "образец" in str(msg.answer.call_args[0][0]).lower() or "картинк" in str(
        msg.answer.call_args[0][0]
    ).lower()


def test_rescue_router_exists():
    assert isinstance(rescue_router, Router)


@pytest.mark.asyncio
async def test_rescue_reason_more_imports_from_generation(mock_state, mock_bot):
    """Calling the handler runs the lazy import from generation (no ImportError)."""
    cb = make_callback(data="rescue:reason:more:take-uuid-1")
    with patch("app.bot.handlers.rescue.IdempotencyStore") as MockStore:
        MockStore.return_value.check_and_set.return_value = False
        await rescue_reason_more(cb, mock_state, mock_bot)
    cb.answer.assert_awaited()
    assert MockStore.return_value.check_and_set.called


def test_results_router_exists():
    assert isinstance(results_router, Router)


def test_pack_activated_message_and_keyboard_returns_tuple():
    db = MagicMock()
    db.query.return_value.filter.return_value.one_or_none.return_value = None
    text, kb = _pack_activated_message_and_keyboard(db, "123456", "🎁", "Starter", 5)
    assert isinstance(text, str)
    assert "Пакет" in text or "активирован" in text
    assert isinstance(kb, InlineKeyboardMarkup)


@pytest.mark.asyncio
async def test_choose_variant_wrong_format(mock_state, mock_bot):
    cb = make_callback(data="choose:ab")
    await choose_variant(cb, mock_state, mock_bot)
    cb.answer.assert_awaited()
    assert cb.answer.call_args.kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_choose_variant_invalid_variant(mock_state, mock_bot):
    cb = make_callback(data="choose:tid1:X")
    await choose_variant(cb, mock_state, mock_bot)
    cb.answer.assert_awaited()
    assert "вариант" in str(cb.answer.call_args).lower()


@pytest.mark.asyncio
async def test_choose_variant_take_not_found(mock_state, mock_bot):
    cb = make_callback(data="choose:missing-id:A")
    with patch("app.bot.handlers.results.get_db_session") as mock_gs, patch(
        "app.bot.handlers.results.TakeService"
    ) as MockTS, patch("app.bot.handlers.results.favorite_selected_total"):
        MockTS.return_value.get_take.return_value = None

        @contextmanager
        def _fake():
            yield MagicMock()

        mock_gs.side_effect = lambda: _fake()
        await choose_variant(cb, mock_state, mock_bot)
    cb.answer.assert_awaited()
    assert "не найден" in str(cb.answer.call_args).lower()


@pytest.mark.asyncio
async def test_choose_variant_no_access(mock_state, mock_bot):
    cb = make_callback(data="choose:tid1:A")
    take = MagicMock()
    take.user_id = "other-user"
    take.session_id = make_session().id
    take.trend_id = "tr1"
    user = make_db_user(user_id="my-user")
    with patch("app.bot.handlers.results.get_db_session") as mock_gs, patch(
        "app.bot.handlers.results.TakeService"
    ) as MockTS, patch("app.bot.handlers.results.UserService") as MockUS, patch(
        "app.bot.handlers.results.favorite_selected_total"
    ):

        @contextmanager
        def _fake():
            yield MagicMock()

        mock_gs.side_effect = lambda: _fake()
        MockTS.return_value.get_take.return_value = take
        MockUS.return_value.get_or_create_user.return_value = user
        await choose_variant(cb, mock_state, mock_bot)
    cb.answer.assert_awaited()
    assert "доступ" in str(cb.answer.call_args).lower()


