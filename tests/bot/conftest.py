"""Shared fixtures for bot tests."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# DB session
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_db():
    """Mock SQLAlchemy session."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.one_or_none.return_value = None
    return db


@pytest.fixture(autouse=True)
def patch_db_session(mock_db):
    @contextmanager
    def _fake():
        yield mock_db

    with patch("app.bot.helpers.get_db_session", _fake):
        with patch("app.bot.helpers.SessionLocal", return_value=mock_db):
            yield


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def patch_redis():
    mock_redis = MagicMock()
    mock_redis.incr.return_value = 1
    with patch("app.bot.helpers.redis_client", mock_redis):
        with patch("app.bot.middleware.security.redis_client", mock_redis):
            yield mock_redis


# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def patch_celery():
    mock_celery = MagicMock()
    with patch("app.core.celery_app.celery_app", mock_celery):
        yield mock_celery


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def patch_settings():
    fake = SimpleNamespace(
        telegram_bot_token="test:token",
        redis_url="redis://localhost",
        database_url="sqlite://",
        support_username="test_support",
        max_file_size_mb=20,
        storage_base_path="/tmp/test_storage",
        unlock_cost_stars=50,
        subscription_channel_username="",
        trend_examples_dir="data/trend_examples",
        star_to_rub=1.3,
    )
    with patch("app.bot.helpers.settings", fake):
        with patch("app.bot.keyboards.settings", fake, create=True):
            yield fake


# ---------------------------------------------------------------------------
# Runtime templates
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def patch_runtime_templates():
    mock_rt = MagicMock()
    mock_rt.get.side_effect = lambda key, default: default
    mock_rt.render.side_effect = lambda key, default, **kw: default.format(**{k: kw[k] for k in kw if f"{{{k}}}" in default}) if kw else default
    mock_rt.resolve_literal.side_effect = lambda text: text
    with patch("app.bot.helpers.runtime_templates", mock_rt):
        yield mock_rt


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.get_file = AsyncMock(return_value=SimpleNamespace(file_path="photos/file.jpg"))
    bot.download_file = AsyncMock()
    bot.send_message = AsyncMock()
    bot.send_document = AsyncMock()
    bot.edit_message_text = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.refund_star_payment = AsyncMock()
    return bot


# ---------------------------------------------------------------------------
# FSM state
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_state():
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    state.get_state = AsyncMock(return_value=None)
    state.set_state = AsyncMock()
    state.set_data = AsyncMock()
    state.update_data = AsyncMock()
    state.clear = AsyncMock()
    return state


# ---------------------------------------------------------------------------
# Message / CallbackQuery factories
# ---------------------------------------------------------------------------
def _make_user(user_id="123456", username="testuser", first_name="Test", last_name="User"):
    return SimpleNamespace(
        id=int(user_id),
        username=username,
        first_name=first_name,
        last_name=last_name,
    )


def make_message(
    text=None,
    from_user_id="123456",
    chat_type="private",
    photo=None,
    document=None,
    successful_payment=None,
):
    msg = AsyncMock()
    msg.from_user = _make_user(from_user_id)
    msg.chat = SimpleNamespace(id=int(from_user_id), type=chat_type)
    msg.text = text
    msg.photo = photo
    msg.document = document
    msg.successful_payment = successful_payment
    msg.caption = None
    msg.message_id = 100
    msg.answer = AsyncMock(return_value=SimpleNamespace(message_id=101))
    msg.answer_photo = AsyncMock(return_value=SimpleNamespace(message_id=102))
    msg.edit_text = AsyncMock()
    msg.edit_caption = AsyncMock()
    msg.reply = AsyncMock()
    return msg


def make_callback(data="", from_user_id="123456"):
    cb = AsyncMock()
    cb.from_user = _make_user(from_user_id)
    cb.data = data
    cb.message = make_message(from_user_id=from_user_id)
    cb.answer = AsyncMock()
    return cb


def make_pre_checkout(from_user_id="123456", currency="XTR", total_amount=100, payload="pack:starter"):
    pq = AsyncMock()
    pq.from_user = _make_user(from_user_id)
    pq.id = "pq_123"
    pq.currency = currency
    pq.total_amount = total_amount
    pq.invoice_payload = payload
    pq.answer = AsyncMock()
    return pq


def make_db_user(telegram_id="123456", user_id="user-uuid-1", token_balance=10, flags=None):
    return SimpleNamespace(
        id=user_id,
        telegram_id=telegram_id,
        token_balance=token_balance,
        is_banned=False,
        is_suspended=False,
        suspended_until=None,
        ban_reason=None,
        suspend_reason=None,
        flags=flags or {},
        data_deletion_requested_at=None,
        get_effective_rate_limit=lambda default=60, subscriber_limit=120: default,
    )


def make_session(session_id="sess-1", pack_id="starter", remaining=5):
    return SimpleNamespace(
        id=session_id,
        pack_id=pack_id,
        remaining_takes=remaining,
        status="active",
    )
