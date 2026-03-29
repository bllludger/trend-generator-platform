"""Unit tests for app.bot.keyboards builders."""
from __future__ import annotations

from unittest.mock import patch

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from app.bot.constants import (
    GENERATION_NEGATIVE_REASONS,
    NAV_THEMES,
    SUBSCRIPTION_CALLBACK,
    TREND_CUSTOM_ID,
    THEME_CB_PREFIX,
)
from app.bot import keyboards as kb_mod


def _reply_button_count(markup: ReplyKeyboardMarkup) -> int:
    return sum(len(row) for row in markup.keyboard)


def _inline_buttons(markup: InlineKeyboardMarkup) -> list[InlineKeyboardButton]:
    return [btn for row in markup.inline_keyboard for btn in row]


def test_main_menu_keyboard_structure():
    m = kb_mod.main_menu_keyboard()
    assert isinstance(m, ReplyKeyboardMarkup)
    assert len(m.keyboard) == 3
    assert _reply_button_count(m) == 5


def test_create_photo_only_keyboard_structure():
    m = kb_mod.create_photo_only_keyboard()
    assert isinstance(m, ReplyKeyboardMarkup)
    assert len(m.keyboard) == 1
    assert _reply_button_count(m) == 1


def test_themes_keyboard_empty_only_custom_idea():
    m = kb_mod.themes_keyboard([])
    assert isinstance(m, InlineKeyboardMarkup)
    assert len(m.inline_keyboard) == 1
    last = m.inline_keyboard[-1][0]
    assert last.callback_data == f"trend:{TREND_CUSTOM_ID}"
    assert "Своя идея" in (last.text or "")


def test_themes_keyboard_one_theme_plus_custom():
    themes = [{"id": "t1", "name": "A", "emoji": "🌟"}]
    m = kb_mod.themes_keyboard(themes)
    assert len(m.inline_keyboard) == 2
    assert m.inline_keyboard[0][0].callback_data == f"{THEME_CB_PREFIX}t1"
    last = m.inline_keyboard[-1][0]
    assert last.callback_data == f"trend:{TREND_CUSTOM_ID}"
    assert last.text == "💡 Своя идея"


def test_themes_keyboard_three_themes_rows_of_two():
    themes = [
        {"id": "a", "name": "A", "emoji": "1"},
        {"id": "b", "name": "B", "emoji": "2"},
        {"id": "c", "name": "C", "emoji": "3"},
    ]
    m = kb_mod.themes_keyboard(themes)
    assert len(m.inline_keyboard) == 3
    assert len(m.inline_keyboard[0]) == 2
    assert len(m.inline_keyboard[1]) == 1
    assert m.inline_keyboard[-1][0].callback_data == f"trend:{TREND_CUSTOM_ID}"


def test_trends_in_theme_keyboard_groups_three_per_row():
    theme_id = "thr1"
    trends = [
        {"id": f"tr{i}", "name": f"N{i}", "emoji": str(i)}
        for i in range(6)
    ]
    m = kb_mod.trends_in_theme_keyboard(theme_id, trends, page=0, total_pages=1)
    trend_rows = m.inline_keyboard[:-2]
    assert len(trend_rows) == 2
    assert all(len(r) == 3 for r in trend_rows)


def test_trends_in_theme_keyboard_multi_page_navigation():
    theme_id = "multi"
    trends = [{"id": "t1", "name": "One", "emoji": "🎬"}]
    m = kb_mod.trends_in_theme_keyboard(theme_id, trends, page=1, total_pages=3)
    # Rows: trend row(s), pagination row, back+menu row
    nav_row = m.inline_keyboard[-2]
    cbs = [b.callback_data for b in nav_row]
    assert any(cb and cb.startswith(f"{THEME_CB_PREFIX}{theme_id}:") for cb in cbs)
    assert f"{THEME_CB_PREFIX}{theme_id}:0" in cbs


def test_trends_in_theme_keyboard_back_and_menu():
    m = kb_mod.trends_in_theme_keyboard("th", [], page=0, total_pages=1)
    bottom = m.inline_keyboard[-1]
    assert len(bottom) == 2
    assert bottom[0].callback_data == NAV_THEMES
    assert bottom[1].callback_data == "nav:menu"


def test_trends_keyboard_one_per_row_and_custom_tail():
    trends = [
        {"id": "a", "name": "Alpha", "emoji": "🔹"},
        {"id": "b", "name": "Beta", "emoji": "🔸"},
    ]
    m = kb_mod.trends_keyboard(trends)
    assert len(m.inline_keyboard) == 3
    assert all(len(row) == 1 for row in m.inline_keyboard[:-1])
    assert m.inline_keyboard[-1][0].callback_data == f"trend:{TREND_CUSTOM_ID}"


@patch.object(kb_mod, "_get_default_aspect_ratio", return_value="4:3")
def test_format_keyboard_five_formats_and_nav(_mock_ar):
    m = kb_mod.format_keyboard()
    flat = _inline_buttons(m)
    format_cbs = [b.callback_data for b in flat if b.callback_data and b.callback_data.startswith("format:")]
    assert set(format_cbs) == {"format:1:1", "format:16:9", "format:4:3", "format:9:16", "format:3:4"}
    assert m.inline_keyboard[-1][0].callback_data == "nav:trends"
    assert m.inline_keyboard[-1][1].callback_data == "nav:menu"
    labels = [b.text for b in flat if b.callback_data and b.callback_data.startswith("format:")]
    assert any("по умолч." in (x or "") for x in labels)


def test_feedback_keyboard_four_callbacks():
    m = kb_mod._feedback_keyboard("take-9", "v2")
    flat = _inline_buttons(m)
    assert len(flat) == 4
    assert flat[0].callback_data == "gen_fb:take-9:v2:1"
    assert flat[1].callback_data == "gen_fb:take-9:v2:0"
    assert flat[2].callback_data == "ln:take-9:v2:yes"
    assert flat[3].callback_data == "ln:take-9:v2:no"


def test_negative_reason_keyboard_seven_in_two_rows():
    m = kb_mod._negative_reason_keyboard("tid", "va")
    assert len(m.inline_keyboard) == 2
    assert len(m.inline_keyboard[0]) == 4
    assert len(m.inline_keyboard[1]) == 3
    assert len(GENERATION_NEGATIVE_REASONS) == 7
    for i, (slug, label) in enumerate(GENERATION_NEGATIVE_REASONS):
        row_idx, col = (0, i) if i < 4 else (1, i - 4)
        btn = m.inline_keyboard[row_idx][col]
        assert btn.text == label
        assert btn.callback_data == f"nr:tid:va:{slug}"


def test_subscription_keyboard_none_without_channel():
    with patch.object(kb_mod, "SUBSCRIPTION_CHANNEL_USERNAME", ""):
        assert kb_mod._subscription_keyboard() is None


def test_subscription_keyboard_with_channel_url_and_callback():
    with patch.object(kb_mod, "SUBSCRIPTION_CHANNEL_USERNAME", "mychannel"):
        m = kb_mod._subscription_keyboard()
        assert isinstance(m, InlineKeyboardMarkup)
        assert len(m.inline_keyboard) == 2
        url_btn = m.inline_keyboard[0][0]
        assert url_btn.url == "https://t.me/mychannel"
        assert m.inline_keyboard[1][0].callback_data == SUBSCRIPTION_CALLBACK


def test_profile_keyboard_paid_active_with_remaining():
    m = kb_mod._profile_keyboard(is_paid_active=True, has_remaining=True, is_trial_profile=False)
    cbs = [b.callback_data for b in _inline_buttons(m)]
    assert "take_more" in cbs
    assert "open_favorites" in cbs
    assert "referral:invite" in cbs
    assert "profile:support" in cbs


def test_profile_keyboard_trial():
    m = kb_mod._profile_keyboard(is_paid_active=False, has_remaining=False, is_trial_profile=True)
    cbs = [b.callback_data for b in _inline_buttons(m)]
    assert "trial_ref:get_link" in cbs
    assert "shop:open" in cbs
    assert "profile:support" in cbs
    assert "referral:invite" not in cbs


def test_profile_keyboard_free_user():
    m = kb_mod._profile_keyboard(is_paid_active=False, has_remaining=False, is_trial_profile=False)
    cbs = [b.callback_data for b in _inline_buttons(m)]
    assert "shop:open" in cbs
    assert "trial_ref:get_link" in cbs
    assert "referral:invite" in cbs
    assert "profile:payment" in cbs


def test_audience_keyboard_three_buttons():
    m = kb_mod.audience_keyboard()
    flat = _inline_buttons(m)
    assert len(flat) == 3
    assert {b.callback_data for b in flat} == {"audience:women", "audience:men", "audience:couples"}


def test_payment_method_keyboard_embeds_pack_id():
    pack_id = "pack_xyz"
    m = kb_mod._payment_method_keyboard(pack_id)
    flat = _inline_buttons(m)
    assert flat[0].callback_data == f"pay_method:yoomoney:{pack_id}"
    assert flat[1].callback_data == f"pay_method:yoomoney_link:{pack_id}"
