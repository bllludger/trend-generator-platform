"""Unit tests for app.bot.helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from aiogram.types import Chat, Message

# Import before any test runs; local binding stays the real contextmanager even though
# tests/bot/conftest.py autouse patches app.bot.helpers.get_db_session for other modules.
from app.bot.helpers import (
    _document_image_ext,
    _escape_markdown,
    _has_paid_profile,
    _is_private_chat,
    _parse_referral_code,
    _parse_start_arg,
    _parse_start_raw_arg,
    _parse_start_theme,
    _parse_traffic_source,
    get_db_session,
    t,
    tr,
)


def _make_message(chat_type: str) -> Message:
    return Message.model_construct(
        message_id=1,
        date=0,
        chat=Chat.model_construct(id=1, type=chat_type),
    )


# ---------------------------------------------------------------------------
# _escape_markdown
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("*", "\\*"),
        ("_", "\\_"),
        ("`", "\\`"),
        ("[", "\\["),
        ("\\", "\\\\"),
        ("", ""),
    ],
)
def test_escape_markdown_special_chars(raw, expected):
    assert _escape_markdown(raw) == expected


def test_escape_markdown_combined_sequence():
    raw = "*_" + "`" + "[" + "\\"
    assert _escape_markdown(raw) == "\\*\\_\\`\\[\\\\"


def test_escape_markdown_none_like_returns_falsy():
    assert _escape_markdown(None) is None


# ---------------------------------------------------------------------------
# _parse_start_raw_arg
# ---------------------------------------------------------------------------
def test_parse_start_raw_arg_with_payload():
    assert _parse_start_raw_arg("/start trend_abc") == "trend_abc"


def test_parse_start_raw_arg_start_only():
    assert _parse_start_raw_arg("/start") is None


def test_parse_start_raw_arg_none():
    assert _parse_start_raw_arg(None) is None


def test_parse_start_raw_arg_empty():
    assert _parse_start_raw_arg("") is None


def test_parse_start_raw_arg_whitespace_only():
    assert _parse_start_raw_arg("   ") is None


# ---------------------------------------------------------------------------
# _parse_start_arg
# ---------------------------------------------------------------------------
def test_parse_start_arg_trend_suffix():
    assert _parse_start_arg("/start trend_abc") == "abc"


def test_parse_start_arg_ref_not_trend():
    assert _parse_start_arg("/start ref_xyz") is None


def test_parse_start_arg_missing_payload():
    assert _parse_start_arg("/start") is None


# ---------------------------------------------------------------------------
# _parse_start_theme
# ---------------------------------------------------------------------------
def test_parse_start_theme_uuid():
    assert _parse_start_theme("/start theme_uuid") == "uuid"


def test_parse_start_theme_rejects_trend():
    assert _parse_start_theme("/start trend_x") is None


# ---------------------------------------------------------------------------
# _parse_referral_code
# ---------------------------------------------------------------------------
def test_parse_referral_code_ref_payload():
    assert _parse_referral_code("/start ref_ABCD") == "ABCD"


def test_parse_referral_code_rejects_trend():
    assert _parse_referral_code("/start trend_x") is None


# ---------------------------------------------------------------------------
# _parse_traffic_source
# ---------------------------------------------------------------------------
def test_parse_traffic_source_slug_only():
    assert _parse_traffic_source("/start src_google") == ("google", None)


def test_parse_traffic_source_slug_and_campaign():
    assert _parse_traffic_source("/start src_google_c_spring") == ("google", "spring")


def test_parse_traffic_source_rejects_ref():
    assert _parse_traffic_source("/start ref_x") == (None, None)


def test_parse_traffic_source_empty_after_prefix():
    assert _parse_traffic_source("/start src_") == (None, None)


# ---------------------------------------------------------------------------
# _document_image_ext
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("mime_type", "file_name", "expected"),
    [
        ("image/jpeg", None, ".jpg"),
        ("image/jpg", None, ".jpg"),
        ("image/png", None, ".png"),
        ("image/webp", None, ".webp"),
        (None, "photo.PNG", ".png"),
        (None, "x.JPEG", ".jpeg"),
        ("application/pdf", "doc.pdf", None),
        ("text/plain", "x.txt", None),
    ],
)
def test_document_image_ext_mime_and_filename(mime_type, file_name, expected):
    assert _document_image_ext(mime_type, file_name) == expected


def test_document_image_ext_filename_wins_over_mime():
    assert _document_image_ext("image/png", "a.jpg") == ".jpg"


def test_document_image_ext_none_inputs():
    assert _document_image_ext(None, None) is None


# ---------------------------------------------------------------------------
# _is_private_chat
# ---------------------------------------------------------------------------
def test_is_private_chat_message_private():
    assert _is_private_chat(_make_message("private")) is True


def test_is_private_chat_message_group():
    assert _is_private_chat(_make_message("group")) is False


def test_is_private_chat_callback_like_private():
    event = SimpleNamespace(
        message=SimpleNamespace(chat=SimpleNamespace(type="private")),
    )
    assert _is_private_chat(event) is True


def test_is_private_chat_callback_like_group():
    event = SimpleNamespace(
        message=SimpleNamespace(chat=SimpleNamespace(type="group")),
    )
    assert _is_private_chat(event) is False


def test_is_private_chat_plain_object_defaults_true():
    assert _is_private_chat(SimpleNamespace()) is True


# ---------------------------------------------------------------------------
# _has_paid_profile
# ---------------------------------------------------------------------------
def test_has_paid_profile_no_user():
    assert _has_paid_profile(None, SimpleNamespace(pack_id="starter")) is False


def test_has_paid_profile_no_session():
    user = SimpleNamespace()
    assert _has_paid_profile(user, None) is False


def test_has_paid_profile_free_preview():
    user = SimpleNamespace()
    session = SimpleNamespace(pack_id="free_preview")
    assert _has_paid_profile(user, session) is False


def test_has_paid_profile_trial():
    user = SimpleNamespace()
    session = SimpleNamespace(pack_id="trial")
    assert _has_paid_profile(user, session) is False


def test_has_paid_profile_paid_pack():
    user = SimpleNamespace()
    session = SimpleNamespace(pack_id="starter")
    assert _has_paid_profile(user, session) is True


# ---------------------------------------------------------------------------
# get_db_session
# ---------------------------------------------------------------------------
def test_get_db_session_commits_and_closes_on_success():
    db = MagicMock()
    with patch("app.bot.helpers.SessionLocal", return_value=db):
        with get_db_session() as session:
            assert session is db
    db.commit.assert_called_once()
    db.rollback.assert_not_called()
    db.close.assert_called_once()


def test_get_db_session_rollback_and_closes_on_error():
    db = MagicMock()
    with patch("app.bot.helpers.SessionLocal", return_value=db):
        with pytest.raises(RuntimeError, match="boom"):
            with get_db_session():
                raise RuntimeError("boom")
    db.rollback.assert_called_once()
    db.commit.assert_not_called()
    db.close.assert_called_once()


# ---------------------------------------------------------------------------
# t() / tr()
# ---------------------------------------------------------------------------
def test_t_delegates_to_runtime_templates(patch_runtime_templates):
    patch_runtime_templates.get.side_effect = None
    patch_runtime_templates.get.return_value = "resolved"
    assert t("greeting", "fallback") == "resolved"
    patch_runtime_templates.get.assert_called_once_with("greeting", "fallback")


def test_tr_delegates_to_runtime_templates(patch_runtime_templates):
    patch_runtime_templates.render.side_effect = None
    patch_runtime_templates.render.return_value = "Hello, Ada"
    assert tr("welcome", "Hello, {name}", name="Ada") == "Hello, Ada"
    patch_runtime_templates.render.assert_called_once_with("welcome", "Hello, {name}", name="Ada")
