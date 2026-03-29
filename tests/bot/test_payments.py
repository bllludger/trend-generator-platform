"""Unit tests for app.bot.handlers.payments (direct async handler calls)."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Router

from app.bot.handlers.payments import (
    buy_pack,
    cmd_paysupport,
    cmd_terms,
    handle_pre_checkout,
    handle_successful_payment,
    payments_router,
    shop_menu_callback,
    shop_menu_text,
    unlock_photo,
)
from app.models.job import Job
from app.models.user import User
from app.services.payments.service import PaymentService as RealPaymentService
from tests.bot.conftest import (
    make_callback,
    make_db_user,
    make_message,
    make_pre_checkout,
    make_session,
)


@pytest.fixture
def patch_payment_services(mock_db):
    """Patch DB session and services imported by payments.py."""
    with patch("app.bot.handlers.payments.get_db_session") as mock_gs:

        @contextmanager
        def _fake():
            yield mock_db

        mock_gs.side_effect = _fake
        with (
            patch("app.bot.handlers.payments.UserService") as MockUS,
            patch("app.bot.handlers.payments.PaymentService") as MockPS,
            patch("app.bot.handlers.payments.SessionService") as MockSS,
            patch("app.bot.handlers.payments.AuditService") as MockAS,
            patch("app.bot.handlers.payments.ProductAnalyticsService") as MockPAS,
            patch("app.bot.handlers.payments.HDBalanceService") as MockHD,
            patch("app.bot.handlers.payments.ReferralService") as MockRS,
        ):
            # Класс замокан целиком — оставляем реальный статический parse_payload.
            MockPS.parse_payload = RealPaymentService.parse_payload
            yield SimpleNamespace(
                user_svc=MockUS.return_value,
                payment_svc=MockPS.return_value,
                session_svc=MockSS.return_value,
                audit_svc=MockAS.return_value,
                analytics_svc=MockPAS.return_value,
                hd_svc=MockHD.return_value,
                referral_svc=MockRS.return_value,
            )


# ---------------------------------------------------------------------------
# Pre-checkout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_pre_checkout_answers_ok(mock_bot, patch_payment_services):
    pq = make_pre_checkout()
    patch_payment_services.payment_svc.validate_pre_checkout.return_value = (True, None)
    await handle_pre_checkout(pq, mock_bot)
    mock_bot.answer_pre_checkout_query.assert_called_once_with(pq.id, ok=True)


@pytest.mark.asyncio
async def test_handle_pre_checkout_rejects_when_invalid(mock_bot, patch_payment_services):
    pq = make_pre_checkout()
    patch_payment_services.payment_svc.validate_pre_checkout.return_value = (False, "Неверная сумма")
    patch_payment_services.user_svc.get_by_telegram_id.return_value = None
    await handle_pre_checkout(pq, mock_bot)
    mock_bot.answer_pre_checkout_query.assert_called_once_with(
        pq.id, ok=False, error_message="Неверная сумма"
    )


# ---------------------------------------------------------------------------
# Shop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shop_menu_text_answers(mock_bot, patch_payment_services):
    patch_payment_services.user_svc.get_or_create_user.return_value = SimpleNamespace(id="u1")
    patch_payment_services.payment_svc.seed_default_packs = MagicMock()
    patch_payment_services.user_svc.get_by_telegram_id.return_value = None
    with (
        patch("app.bot.handlers.payments.build_balance_tariffs_message") as mock_btm,
        patch("app.bot.handlers.payments.os.path.exists", return_value=False),
    ):
        mock_btm.return_value = (
            "<b>Shop</b>",
            {"inline_keyboard": [[{"text": "Pack", "callback_data": "tariff:x"}]]},
        )
        msg = make_message(text="🛒 Купить пакет")
        await shop_menu_text(msg)
    msg.answer.assert_awaited()
    call_kw = msg.answer.await_args.kwargs
    assert call_kw.get("parse_mode") == "HTML"


@pytest.mark.asyncio
async def test_shop_menu_callback_answers(mock_bot, patch_payment_services):
    patch_payment_services.user_svc.get_by_telegram_id.return_value = None
    patch_payment_services.payment_svc.seed_default_packs = MagicMock()
    cb = make_callback(data="shop:open")
    with (
        patch("app.bot.handlers.payments.build_balance_tariffs_message") as mock_btm,
        patch("app.bot.handlers.payments.os.path.exists", return_value=False),
    ):
        mock_btm.return_value = (
            "<b>Shop</b>",
            {"inline_keyboard": [[{"text": "Pack", "callback_data": "tariff:x"}]]},
        )
        await shop_menu_callback(cb)
    cb.message.answer.assert_awaited()
    cb.answer.assert_awaited()


# ---------------------------------------------------------------------------
# buy: (Stars disabled — redirect to YooMoney, no send_invoice)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_buy_pack_redirects_no_send_invoice(mock_bot, patch_payment_services):
    cb = make_callback(data="buy:starter")
    await buy_pack(cb, mock_bot)
    mock_bot.send_invoice.assert_not_called()
    cb.answer.assert_awaited()
    assert cb.answer.await_args.kwargs.get("show_alert") is True
    cb.message.answer.assert_awaited()


# ---------------------------------------------------------------------------
# Successful payment — session / legacy / unlock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_payment_session_payload(
    mock_bot, mock_state, mock_db, patch_payment_services,
):
    user = make_db_user()
    session = SimpleNamespace(id="sess-1", takes_limit=10, takes_used=2)
    pack = SimpleNamespace(emoji="🎨", name="Neo", pack_subtype="standalone", playlist=None)

    def _query_side_effect(model):
        qm = MagicMock()
        if model is User:
            qm.filter.return_value.one_or_none.return_value = user
        return qm

    mock_db.query.side_effect = _query_side_effect

    patch_payment_services.payment_svc.process_session_purchase.return_value = (
        MagicMock(),
        session,
        None,
        0,
    )
    patch_payment_services.payment_svc.get_pack.return_value = pack
    patch_payment_services.hd_svc.get_balance.return_value = {"total": 0}

    sp = SimpleNamespace(
        invoice_payload="session:neo_studio:sess-1",
        telegram_payment_charge_id="tg_ch",
        provider_payment_charge_id="pr_ch",
        total_amount=100,
    )
    msg = make_message(successful_payment=sp)

    with patch(
        "app.bot.handlers.results._pack_activated_message_and_keyboard",
        return_value=("activated", MagicMock()),
    ):
        await handle_successful_payment(msg, mock_state, mock_bot)

    patch_payment_services.payment_svc.process_session_purchase.assert_called_once()
    msg.answer.assert_awaited()


@pytest.mark.asyncio
async def test_successful_payment_pack_payload(
    mock_bot, mock_state, mock_db, patch_payment_services,
):
    user = make_db_user(token_balance=7)
    pack = SimpleNamespace(id="starter", emoji="⭐", name="Start", stars_price=50, tokens=5)

    patch_payment_services.payment_svc.resolve_payload.side_effect = lambda p: p
    patch_payment_services.payment_svc.get_pack.return_value = pack
    patch_payment_services.payment_svc.credit_tokens.return_value = MagicMock()
    patch_payment_services.user_svc.get_by_telegram_id.return_value = user
    patch_payment_services.session_svc.get_active_session.return_value = None

    payload = "pack:starter:user:1:nonce:abc"
    sp = SimpleNamespace(
        invoice_payload=payload,
        telegram_payment_charge_id="tg_ch",
        provider_payment_charge_id="pr_ch",
        total_amount=50,
    )
    msg = make_message(successful_payment=sp)

    await handle_successful_payment(msg, mock_state, mock_bot)

    patch_payment_services.payment_svc.credit_tokens.assert_called_once()
    c = patch_payment_services.payment_svc.credit_tokens.call_args.kwargs
    assert c["pack_id"] == "starter"
    assert c["tokens_granted"] == 5
    msg.answer.assert_awaited()


@pytest.mark.asyncio
async def test_successful_payment_credit_tokens_fails(
    mock_bot, mock_state, mock_db, patch_payment_services,
):
    user = make_db_user()
    job = SimpleNamespace(
        job_id="job-1",
        user_id=user.id,
        output_path_original="/tmp/orig.jpg",
        is_preview=True,
        unlocked_at=None,
    )

    def _query_side_effect(model):
        qm = MagicMock()
        if model is Job:
            qm.filter.return_value.one_or_none.return_value = job
        return qm

    mock_db.query.side_effect = _query_side_effect

    patch_payment_services.payment_svc.resolve_payload.side_effect = lambda p: p
    patch_payment_services.payment_svc.has_unlock_payment_for_job.return_value = False
    patch_payment_services.payment_svc.credit_tokens.return_value = None
    patch_payment_services.user_svc.get_by_telegram_id.return_value = user

    payload = "pack:unlock:job:job-1"
    sp = SimpleNamespace(
        invoice_payload=payload,
        telegram_payment_charge_id="tg_ch",
        provider_payment_charge_id="pr_ch",
        total_amount=50,
    )
    msg = make_message(successful_payment=sp)

    await handle_successful_payment(msg, mock_state, mock_bot)

    patch_payment_services.payment_svc.credit_tokens.assert_called_once()
    mock_bot.refund_star_payment.assert_not_called()
    msg.answer.assert_awaited()
    assert "Оплата получена" in (msg.answer.await_args.args[0] or "")


@pytest.mark.asyncio
async def test_successful_payment_unlock_payload_sets_delivery_context(
    mock_bot, mock_state, mock_db, patch_payment_services,
):
    """After credit_tokens for unlock, TelegramClient sends document (unlock_delivery_context)."""
    user = make_db_user()
    job = SimpleNamespace(
        job_id="job-1",
        user_id=user.id,
        output_path_original="/tmp/orig_unlock.jpg",
        is_preview=True,
        unlocked_at=None,
    )

    def _query_side_effect(model):
        qm = MagicMock()
        if model is Job:
            qm.filter.return_value.one_or_none.return_value = job
        return qm

    mock_db.query.side_effect = _query_side_effect

    patch_payment_services.payment_svc.resolve_payload.side_effect = lambda p: p
    patch_payment_services.payment_svc.has_unlock_payment_for_job.return_value = False
    patch_payment_services.payment_svc.credit_tokens.return_value = MagicMock()
    patch_payment_services.user_svc.get_by_telegram_id.return_value = user

    payload = "pack:unlock:job:job-1"
    sp = SimpleNamespace(
        invoice_payload=payload,
        telegram_payment_charge_id="tg_ch",
        provider_payment_charge_id="pr_ch",
        total_amount=50,
    )
    msg = make_message(successful_payment=sp)

    mock_tg = MagicMock()
    mock_tg.send_document = MagicMock()
    mock_tg.close = MagicMock()

    with (
        patch("app.services.telegram.client.TelegramClient", return_value=mock_tg),
        patch("app.bot.handlers.payments.os.path.isfile", return_value=True),
        patch("app.bot.handlers.payments.paywall_record_unlock"),
    ):
        await handle_successful_payment(msg, mock_state, mock_bot)

    mock_tg.send_document.assert_called_once()
    mock_tg.close.assert_called_once()


@pytest.mark.asyncio
async def test_successful_payment_unlock_owner_mismatch_refunds(
    mock_bot, mock_state, mock_db, patch_payment_services,
):
    """
    Несовпадение владельца job → явный refund_star_payment.
    (Внешний except с payment_committed из-за finally почти не даёт тот же эффект для ошибок внутри блока.)
    """
    user = make_db_user()
    other_job = SimpleNamespace(
        job_id="job-1",
        user_id="other-user",
        output_path_original="/tmp/x.jpg",
        is_preview=True,
        unlocked_at=None,
    )

    def _query_side_effect(model):
        qm = MagicMock()
        if model is Job:
            qm.filter.return_value.one_or_none.return_value = other_job
        return qm

    mock_db.query.side_effect = _query_side_effect

    patch_payment_services.payment_svc.resolve_payload.side_effect = lambda p: p
    patch_payment_services.user_svc.get_by_telegram_id.return_value = user

    payload = "pack:unlock:job:job-1"
    sp = SimpleNamespace(
        invoice_payload=payload,
        telegram_payment_charge_id="tg_ch",
        provider_payment_charge_id="pr_ch",
        total_amount=50,
    )
    msg = make_message(successful_payment=sp)

    await handle_successful_payment(msg, mock_state, mock_bot)

    mock_bot.refund_star_payment.assert_awaited_once()
    patch_payment_services.payment_svc.credit_tokens.assert_not_called()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_paysupport_answers(mock_bot, patch_payment_services):
    patch_payment_services.user_svc.get_or_create_user.return_value = SimpleNamespace(id="u1")
    msg = make_message()
    await cmd_paysupport(msg)
    msg.answer.assert_awaited()
    text = msg.answer.await_args.args[0]
    assert "Поддержка" in text or "платеж" in text.lower()


@pytest.mark.asyncio
async def test_cmd_terms_answers(mock_bot, patch_payment_services):
    patch_payment_services.user_svc.get_or_create_user.return_value = SimpleNamespace(id="u1")
    msg = make_message()
    await cmd_terms(msg)
    msg.answer.assert_awaited()
    text = msg.answer.await_args.args[0]
    assert "Условия" in text or "NeoBanana" in text


# ---------------------------------------------------------------------------
# Unlock photo (Stars invoice)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unlock_photo_callback(mock_bot, patch_payment_services, mock_db):
    user = make_db_user()
    job = SimpleNamespace(
        job_id="take_id:variant",
        user_id=user.id,
        is_preview=True,
        output_path_original="/tmp/o.jpg",
    )

    def _query_side_effect(model):
        qm = MagicMock()
        if model is Job:
            qm.filter.return_value.one_or_none.return_value = job
        return qm

    mock_db.query.side_effect = _query_side_effect

    patch_payment_services.user_svc.get_by_telegram_id.return_value = user
    patch_payment_services.payment_svc.has_unlock_payment_for_job.return_value = False
    patch_payment_services.payment_svc.build_payload.return_value = "unlock:payload-token"
    patch_payment_services.session_svc.get_active_session.return_value = make_session()

    cb = make_callback(data="unlock:take_id:variant")
    await unlock_photo(cb, mock_bot)

    mock_bot.send_invoice.assert_awaited_once()
    inv_kw = mock_bot.send_invoice.await_args.kwargs
    assert inv_kw.get("payload") == "unlock:payload-token"
    cb.answer.assert_awaited()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def test_payments_router_exists():
    assert isinstance(payments_router, Router)
