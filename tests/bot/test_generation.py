"""Unit tests for generation flow, photo upload delete-data, and themes navigation."""
from __future__ import annotations

import os
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.bot.conftest import make_message, make_callback, make_db_user, make_session


def _session_ctx(mock_db):
    @contextmanager
    def _cm():
        yield mock_db

    return _cm


# ---------------------------------------------------------------------------
# photo_upload.py
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cmd_delete_my_data_tracks_inside_db_session(mock_db, patch_celery):
    from app.bot.handlers.photo_upload import cmd_delete_my_data

    user = make_db_user(user_id="user-del-1")
    user.data_deletion_requested_at = None

    mock_user_svc = MagicMock()
    mock_user_svc.get_or_create_user.return_value = user

    with patch("app.bot.handlers.photo_upload.get_db_session", _session_ctx(mock_db)):
        with patch("app.bot.handlers.photo_upload.UserService", return_value=mock_user_svc):
            with patch("app.bot.handlers.photo_upload.ProductAnalyticsService") as PAS:
                msg = make_message(text="/deletemydata")
                state = AsyncMock()
                await cmd_delete_my_data(msg, state)

    PAS.return_value.track.assert_called_once()
    call_kw = PAS.return_value.track.call_args
    assert call_kw[0][0] == "button_click"
    assert call_kw[0][1] == user.id
    assert call_kw[1].get("properties") == {"button_id": "deletemydata"}
    patch_celery.send_task.assert_called_once()
    assert patch_celery.send_task.call_args[0][0] == "app.workers.tasks.delete_user_data.delete_user_data"
    msg.answer.assert_awaited()


@pytest.mark.asyncio
async def test_request_photo_answers_with_instruction(mock_db, mock_bot):
    from app.bot.handlers.photo_upload import request_photo

    u = make_db_user()
    mock_user_svc = MagicMock()
    mock_user_svc.get_or_create_user.return_value = u

    with patch("app.bot.handlers.photo_upload.get_db_session", _session_ctx(mock_db)):
        with patch("app.bot.handlers.photo_upload.UserService", return_value=mock_user_svc):
            with patch("app.bot.handlers.photo_upload.ProductAnalyticsService"):
                msg = make_message(text="🔥 Создать фото")
                state = AsyncMock()
                state.get_data = AsyncMock(return_value={})
                await request_photo(msg, state, mock_bot)

    msg.answer.assert_awaited()
    assert msg.answer.await_args is not None


# ---------------------------------------------------------------------------
# themes.py
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_nav_profile_tracks_inside_db_session(mock_db):
    from app.bot.handlers.themes import nav_profile

    u = make_db_user()
    mock_user_svc = MagicMock()
    mock_user_svc.get_by_telegram_id.return_value = u
    mock_session_svc = MagicMock()
    mock_session_svc.get_active_session.return_value = make_session()

    with patch("app.bot.handlers.themes.get_db_session", _session_ctx(mock_db)):
        with patch("app.bot.handlers.themes.UserService", return_value=mock_user_svc):
            with patch("app.bot.handlers.themes.SessionService", return_value=mock_session_svc):
                with patch("app.bot.handlers.themes.ProductAnalyticsService") as PAS:
                    with patch(
                        "app.bot.handlers.themes._build_profile_view",
                        return_value=("Profile *text*", MagicMock()),
                    ):
                        cb = make_callback(data="nav:profile")
                        await nav_profile(cb)

    PAS.return_value.track.assert_called_once()
    assert PAS.return_value.track.call_args[0][0] == "button_click"
    assert PAS.return_value.track.call_args[1]["properties"]["button_id"] == "nav_profile"
    cb.message.answer.assert_awaited()


@pytest.mark.asyncio
async def test_nav_back_to_menu_clears_state(mock_db, mock_bot):
    from app.bot.handlers.themes import nav_back_to_menu

    u = make_db_user()
    mock_user_svc = MagicMock()
    mock_user_svc.get_by_telegram_id.return_value = u

    with patch("app.bot.handlers.themes.get_db_session", _session_ctx(mock_db)):
        with patch("app.bot.handlers.themes.UserService", return_value=mock_user_svc):
            with patch("app.bot.handlers.themes.ProductAnalyticsService"):
                with patch("app.bot.handlers.themes._try_delete_messages", new_callable=AsyncMock):
                    cb = make_callback(data="nav:menu")
                    state = AsyncMock()
                    await nav_back_to_menu(cb, state, mock_bot)

    state.clear.assert_awaited()
    cb.message.answer.assert_awaited()
    assert "Главное меню" in (cb.message.answer.await_args[0][0] or "")


@pytest.mark.asyncio
async def test_waiting_prompt_wrong_input_answers():
    from app.bot.handlers.themes import waiting_prompt_wrong_input

    msg = make_message(text=None)
    msg.photo = [MagicMock()]
    await waiting_prompt_wrong_input(msg)
    msg.answer.assert_awaited()


# ---------------------------------------------------------------------------
# generation.py — _mark_take_enqueue_failed
# ---------------------------------------------------------------------------
def test_mark_take_enqueue_failed_marks_take(mock_db):
    from app.bot.handlers.generation import _mark_take_enqueue_failed

    take = SimpleNamespace(
        id="take-1",
        status="generating",
        session_id=None,
        user_id="u1",
        trend_id="t1",
        take_type="TREND",
        is_reroll=False,
        is_rescue_photo_replace=False,
    )
    mock_take_svc = MagicMock()
    mock_take_svc.get_take.return_value = take

    with patch("app.bot.handlers.generation.get_db_session", _session_ctx(mock_db)):
        with patch("app.bot.handlers.generation.TakeService", return_value=mock_take_svc):
            with patch("app.bot.handlers.generation.SessionService"):
                with patch("app.bot.handlers.generation.AuditService"):
                    with patch("app.bot.handlers.generation.ProductAnalyticsService"):
                        with patch("app.bot.handlers.generation.TrialV2Service"):
                            with patch("app.bot.handlers.generation.UserService"):
                                _mark_take_enqueue_failed("take-1", actor_id="123456")

    mock_take_svc.set_status.assert_called_once()
    assert mock_take_svc.set_status.call_args[0][1] == "failed"
    assert mock_take_svc.set_status.call_args[1].get("error_code") == "enqueue_failed"


def test_mark_take_enqueue_failed_skips_when_no_take(mock_db):
    from app.bot.handlers.generation import _mark_take_enqueue_failed

    mock_take_svc = MagicMock()
    mock_take_svc.get_take.return_value = None

    with patch("app.bot.handlers.generation.get_db_session", _session_ctx(mock_db)):
        with patch("app.bot.handlers.generation.TakeService", return_value=mock_take_svc):
            with patch("app.bot.handlers.generation.SessionService"):
                with patch("app.bot.handlers.generation.AuditService"):
                    with patch("app.bot.handlers.generation.ProductAnalyticsService"):
                        _mark_take_enqueue_failed("missing")

    mock_take_svc.set_status.assert_not_called()


# ---------------------------------------------------------------------------
# generation.py — select_format_and_generate
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_select_format_and_generate_starts_celery_task(
    mock_db, mock_bot, mock_state, patch_celery
):
    from app.bot.handlers.generation import select_format_and_generate

    u = make_db_user()
    u.is_moderator = True
    trend = SimpleNamespace(enabled=True)
    created_take = SimpleNamespace(id="take-new-1")

    mock_user_svc = MagicMock()
    mock_user_svc.get_by_telegram_id.return_value = u
    mock_user_svc.get_or_create_user.return_value = u

    mock_trend_svc = MagicMock()
    mock_trend_svc.get.return_value = trend

    mock_take_svc = MagicMock()
    mock_take_svc.create_take.return_value = created_take

    free_sess = SimpleNamespace(id="sess-free-1")
    mock_session_svc = MagicMock()
    mock_session_svc.create_free_preview_session.return_value = free_sess

    mock_state.get_data = AsyncMock(
        return_value={
            "photo_local_path": "/tmp/photo.jpg",
            "photo_file_id": "file_id_123",
            "selected_trend_id": "trend_1",
            "selected_trend_name": "Test Trend",
            "audience_type": "women",
        }
    )

    cb = make_callback(data="format:1:1")

    with patch("app.bot.handlers.generation.get_db_session", _session_ctx(mock_db)):
        with patch("app.bot.handlers.generation.UserService", return_value=mock_user_svc):
            with patch("app.bot.handlers.generation.TrendService", return_value=mock_trend_svc):
                with patch("app.bot.handlers.generation.TakeService", return_value=mock_take_svc):
                    with patch("app.bot.handlers.generation.SessionService", return_value=mock_session_svc):
                        with patch("app.bot.handlers.generation.AuditService"):
                            with patch("app.bot.handlers.generation.ProductAnalyticsService"):
                                with patch("app.bot.handlers.generation.TrialV2Service"):
                                    with patch("app.bot.handlers.generation.CompensationService"):
                                        with patch(
                                            "app.bot.handlers.generation.IdempotencyStore"
                                        ) as IS:
                                            IS.return_value.check_and_set.return_value = True
                                            with patch(
                                                "app.bot.handlers.generation.os.path.exists",
                                                return_value=True,
                                            ):
                                                with patch(
                                                    "app.bot.handlers.generation.os.path.getsize",
                                                    return_value=1024,
                                                ):
                                                    with patch(
                                                        "app.bot.handlers.generation.os.path.isfile",
                                                        return_value=False,
                                                    ):
                                                        await select_format_and_generate(
                                                            cb, mock_state, mock_bot
                                                        )

    patch_celery.send_task.assert_called()
    names = [c.args[0] for c in patch_celery.send_task.call_args_list]
    assert "app.workers.tasks.generate_take.generate_take" in names
    mock_state.clear.assert_awaited()


@pytest.mark.asyncio
async def test_select_format_and_generate_no_tokens_shows_paywall(
    mock_db, mock_bot, mock_state
):
    from app.bot.handlers.generation import select_format_and_generate

    u = make_db_user()
    u.is_moderator = False
    paid_session = make_session(session_id="sess-paid", pack_id="starter", remaining=0)

    mock_user_svc = MagicMock()
    mock_user_svc.get_by_telegram_id.return_value = u
    mock_user_svc.get_or_create_user.return_value = u

    mock_trend_svc = MagicMock()
    mock_trend_svc.get.return_value = SimpleNamespace(enabled=True)

    mock_session_svc = MagicMock()
    mock_session_svc.get_active_session.return_value = paid_session
    mock_session_svc.can_take.return_value = False

    mock_state.get_data = AsyncMock(
        return_value={
            "photo_local_path": "/tmp/photo.jpg",
            "photo_file_id": "file_id_123",
            "selected_trend_id": "trend_1",
            "selected_trend_name": "Test Trend",
            "audience_type": "women",
        }
    )

    cb = make_callback(data="format:4:3")

    with patch("app.bot.handlers.generation.get_db_session", _session_ctx(mock_db)):
        with patch("app.bot.handlers.generation.UserService", return_value=mock_user_svc):
            with patch("app.bot.handlers.generation.TrendService", return_value=mock_trend_svc):
                with patch("app.bot.handlers.generation.TakeService"):
                    with patch("app.bot.handlers.generation.SessionService", return_value=mock_session_svc):
                        with patch("app.bot.handlers.generation.AuditService"):
                            with patch("app.bot.handlers.generation.ProductAnalyticsService"):
                                with patch("app.bot.handlers.generation.TrialV2Service") as TV2:
                                    TV2.return_value.is_trial_v2_user.return_value = False
                                    with patch(
                                        "app.bot.handlers.generation.IdempotencyStore"
                                    ) as IS:
                                        IS.return_value.check_and_set.return_value = True
                                        with patch(
                                            "app.bot.handlers.generation.os.path.exists",
                                            return_value=True,
                                        ):
                                            with patch(
                                                "app.bot.handlers.generation.os.path.getsize",
                                                return_value=1024,
                                            ):
                                                await select_format_and_generate(
                                                    cb, mock_state, mock_bot
                                                )

    cb.answer.assert_awaited()
    alert_text = cb.answer.await_args[0][0]
    assert "запущена" in alert_text.lower()


@pytest.mark.asyncio
async def test_select_format_unknown_format(mock_state, mock_bot):
    from app.bot.handlers.generation import select_format_and_generate

    cb = make_callback(data="format:not_a_real_ratio")
    await select_format_and_generate(cb, mock_state, mock_bot)
    cb.answer.assert_awaited()
    mock_state.clear.assert_not_awaited()


@pytest.mark.asyncio
async def test_select_format_tracks_format_selected_when_user_exists(mock_db, mock_state, mock_bot):
    from app.bot.handlers.generation import select_format_and_generate

    u = make_db_user()
    mock_user_svc = MagicMock()
    mock_user_svc.get_by_telegram_id.return_value = u
    mock_user_svc.get_or_create_user.return_value = u

    mock_state.get_data = AsyncMock(
        return_value={
            "photo_local_path": "/tmp/photo.jpg",
            "photo_file_id": "f1",
            "selected_trend_id": "trend_1",
            "audience_type": "women",
        }
    )

    cb = make_callback(data="format:1:1")

    with patch("app.bot.handlers.generation.get_db_session", _session_ctx(mock_db)):
        with patch("app.bot.handlers.generation.UserService", return_value=mock_user_svc):
            with patch("app.bot.handlers.generation.TrendService") as TS:
                TS.return_value.get.return_value = SimpleNamespace(enabled=True)
                with patch("app.bot.handlers.generation.TakeService"):
                    with patch("app.bot.handlers.generation.SessionService") as SS:
                        SS.return_value.create_free_preview_session.return_value = SimpleNamespace(
                            id="s1"
                        )
                        SS.return_value.get_active_session.return_value = None
                        with patch("app.bot.handlers.generation.AuditService"):
                            with patch("app.bot.handlers.generation.ProductAnalyticsService") as PAS:
                                with patch("app.bot.handlers.generation.TrialV2Service") as TV2:
                                    TV2.return_value.is_trial_v2_user.return_value = False
                                    u.is_moderator = True
                                    with patch(
                                        "app.bot.handlers.generation.IdempotencyStore"
                                    ) as IS:
                                        IS.return_value.check_and_set.return_value = True
                                        with patch(
                                            "app.bot.handlers.generation.os.path.exists",
                                            return_value=True,
                                        ):
                                            with patch(
                                                "app.bot.handlers.generation.os.path.getsize",
                                                return_value=1024,
                                            ):
                                                with patch(
                                                    "app.bot.handlers.generation.os.path.isfile",
                                                    return_value=False,
                                                ):
                                                    await select_format_and_generate(
                                                        cb, mock_state, mock_bot
                                                    )

    track_names = [c.args[0] for c in PAS.return_value.track.call_args_list]
    assert "format_selected" in track_names


# ---------------------------------------------------------------------------
# generation.py — regenerate_same
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_regenerate_same_creates_new_take(mock_db, mock_bot, mock_state, patch_celery):
    from app.bot.handlers.generation import regenerate_same

    job = SimpleNamespace(
        user_id="user-uuid-1",
        status="SUCCEEDED",
        input_file_ids=["file_id_a"],
        trend_id="trend_1",
        image_size="1024x1024",
        custom_prompt=None,
        used_copy_quota=False,
    )
    user_row = SimpleNamespace(id="user-uuid-1", telegram_id="123456")

    def query_side_effect(model):
        q = MagicMock()
        if getattr(model, "__name__", None) == "User":
            q.filter.return_value.first.return_value = user_row
        return q

    mock_db.query.side_effect = query_side_effect

    mock_job_svc = MagicMock()
    mock_job_svc.get.return_value = job
    new_job = SimpleNamespace(job_id="job-new-uuid")
    mock_job_svc.create_job.return_value = new_job

    mock_user_svc = MagicMock()
    mock_user_svc.get_by_telegram_id.return_value = user_row
    mock_user_svc.try_use_free_generation.return_value = True

    mock_trend_svc = MagicMock()
    mock_trend_svc.get.return_value = SimpleNamespace(enabled=True)

    cb = make_callback(data="regenerate:job-old-1")

    with patch("app.bot.handlers.generation.get_db_session", _session_ctx(mock_db)):
        with patch("app.bot.handlers.generation.JobService", return_value=mock_job_svc):
            with patch("app.bot.handlers.generation.UserService", return_value=mock_user_svc):
                with patch("app.bot.handlers.generation.TrendService", return_value=mock_trend_svc):
                    with patch("app.bot.handlers.generation.AuditService"):
                        with patch("app.bot.handlers.generation.ProductAnalyticsService"):
                            with patch("app.bot.handlers.generation.SecuritySettingsService"):
                                with patch("os.makedirs"):
                                    with patch(
                                        "app.bot.handlers.generation.os.path.join",
                                        side_effect=os.path.join,
                                    ):
                                        with patch(
                                            "app.bot.handlers.generation.os.path.getsize",
                                            return_value=1024,
                                        ):
                                            await regenerate_same(cb, mock_state, mock_bot)

    mock_job_svc.create_job.assert_called_once()
    patch_celery.send_task.assert_called_once()
    st_call = patch_celery.send_task.call_args
    assert st_call[0][0] == "app.workers.tasks.generation_v2.generate_image"
    assert st_call.kwargs.get("args") == ["job-new-uuid"]
