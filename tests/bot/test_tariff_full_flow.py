"""End-to-end style tests for tariff purchase flow: /start -> paywall -> payment check."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.handlers.session import pack_check_callback, paywall_pack_selected
from app.bot.handlers.start import cmd_start
from tests.bot.conftest import make_callback, make_db_user, make_message, make_session


@pytest.mark.asyncio
async def test_tariff_full_flow_from_start_to_pack_activation(mock_state, mock_bot):
    user = make_db_user()

    # Step 1: /start
    start_msg = make_message(text="/start")
    with patch("app.bot.handlers.start.SUBSCRIPTION_CHANNEL_USERNAME", ""), patch(
        "app.bot.handlers.start._user_subscribed", return_value=True
    ), patch("app.bot.handlers.start.get_db_session") as start_gs, patch(
        "app.bot.handlers.start.UserService"
    ) as StartUS, patch("app.bot.handlers.start.AuditService"), patch(
        "app.bot.handlers.start.ProductAnalyticsService"
    ), patch("app.bot.handlers.start.SessionService") as StartSS, patch(
        "app.bot.handlers.start.PaymentService"
    ), patch("app.bot.handlers.start.ReferralService"), patch(
        "app.bot.handlers.start.bot_started_total"
    ), patch("app.bot.handlers.start.os.path.exists", return_value=False):
        db = MagicMock()

        @contextmanager
        def _fake_start():
            yield db

        start_gs.side_effect = lambda: _fake_start()
        StartUS.return_value.get_or_create_user.return_value = user
        StartUS.return_value.get_by_telegram_id.return_value = user
        StartSS.return_value.get_active_session.return_value = make_session()
        await cmd_start(start_msg, mock_state)

    assert start_msg.answer.await_count + start_msg.answer_photo.await_count >= 1

    # Step 2: user selects tariff (neo_start) and receives payment link + pack_check button
    pay_cb = make_callback(data="paywall:neo_start")
    pack = SimpleNamespace(
        id="neo_start",
        enabled=True,
        is_trial=False,
        name="Neo Start",
        emoji="🔥",
        takes_limit=15,
        hd_amount=15,
        stars_price=153,
    )
    order = SimpleNamespace(id="order-1", confirmation_url="https://pay.local/confirm")

    with patch("app.bot.handlers.session.get_db_session") as pay_gs, patch(
        "app.bot.handlers.session.IdempotencyStore"
    ) as LockCls, patch("app.bot.handlers.session.YooKassaClient") as YooCls, patch(
        "app.services.pack_order.service.PackOrderService"
    ) as PackOrderCls, patch("app.bot.handlers.session.UserService") as SessUS, patch(
        "app.bot.handlers.session.SessionService"
    ) as SessSS, patch("app.bot.handlers.session.ProductAnalyticsService"), patch(
        "app.bot.handlers.session.settings"
    ) as settings_mock:
        db = MagicMock()
        db.query.return_value.filter.return_value.one_or_none.return_value = pack

        @contextmanager
        def _fake_pay():
            yield db

        pay_gs.side_effect = lambda: _fake_pay()
        LockCls.return_value.check_and_set.return_value = True
        YooCls.return_value.is_configured.return_value = True
        PackOrderCls.return_value.get_pending_order.return_value = None
        PackOrderCls.return_value.create_order.return_value = (order, order.confirmation_url)
        SessUS.return_value.get_or_create_user.return_value = user
        SessSS.return_value.get_active_session.return_value = SimpleNamespace(id="sess-1")
        settings_mock.telegram_bot_username = "test_bot"
        settings_mock.star_to_rub = 1.3

        await paywall_pack_selected(pay_cb, mock_bot)

    pay_cb.message.answer.assert_awaited()
    pay_reply_markup = pay_cb.message.answer.await_args.kwargs["reply_markup"]
    pay_buttons = [btn for row in pay_reply_markup.inline_keyboard for btn in row]
    assert any(btn.callback_data == "pack_check:order-1" for btn in pay_buttons if isinstance(btn, InlineKeyboardButton))
    assert any((btn.url or "").startswith("https://pay.local") for btn in pay_buttons)

    # Step 3: user clicks "Проверить оплату", payment succeeded, pack gets activated
    check_cb = make_callback(data="pack_check:order-1")
    pack_order = SimpleNamespace(
        id="order-1",
        telegram_user_id="123456",
        status="payment_pending",
        yookassa_payment_id="yk-pay-1",
        pack_id="neo_start",
        amount_kopecks=19900,
    )
    activated_keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 В меню", callback_data="nav:menu")]])

    with patch("app.bot.handlers.session.get_db_session") as check_gs, patch(
        "app.bot.handlers.session.IdempotencyStore"
    ) as LockCls, patch("app.services.pack_order.service.PackOrderService") as PackOrderCls, patch(
        "app.bot.handlers.session.UserService"
    ) as SessUS, patch("app.bot.handlers.session.ProductAnalyticsService"), patch(
        "app.bot.handlers.session.YooKassaClient"
    ) as YooCls, patch("app.bot.handlers.session.PaymentService") as PaySvcCls, patch(
        "app.bot.handlers.results._pack_activated_message_and_keyboard",
        return_value=("🎉 Пакет активирован", activated_keyboard),
    ):
        db = MagicMock()

        @contextmanager
        def _fake_check():
            yield db

        check_gs.side_effect = lambda: _fake_check()
        LockCls.return_value.check_and_set.return_value = True
        PackOrderCls.return_value.get_by_id.return_value = pack_order
        SessUS.return_value.get_by_telegram_id.return_value = user
        YooCls.return_value.is_configured.return_value = True
        YooCls.return_value.get_payment.return_value = {"status": "succeeded"}
        PaySvcCls.return_value.get_pack.return_value = pack
        PaySvcCls.return_value.process_session_purchase_yookassa_link.return_value = (
            object(),
            SimpleNamespace(id="sess-paid", takes_limit=15, takes_used=0),
            None,
            None,
        )

        await pack_check_callback(check_cb)

    PackOrderCls.return_value.mark_paid.assert_called_once_with(order_id="order-1")
    PackOrderCls.return_value.mark_completed.assert_called_once_with("order-1")
    check_cb.message.answer.assert_awaited()
    assert "активирован" in (check_cb.message.answer.await_args.args[0] or "").lower()
