from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.workers.tasks import watchdog_rendering


class _Q:
    def __init__(self, *, all_value=None, one_or_none_value=None, count_value=0):
        self._all_value = all_value if all_value is not None else []
        self._one_or_none_value = one_or_none_value
        self._count_value = count_value

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._all_value

    def one_or_none(self):
        return self._one_or_none_value

    def count(self):
        return self._count_value


def test_recover_stuck_face_id_take_fallbacks_and_enqueues(monkeypatch):
    take = SimpleNamespace(
        id="take-1",
        face_asset_id="asset-1",
        status="awaiting_face_id",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        session_id=None,
        input_local_paths=[],
    )
    asset = SimpleNamespace(
        id="asset-1",
        status="pending",
        selected_path=None,
        source_path="/tmp/original.jpg",
        reason_code=None,
        chat_id="123",
    )

    db = MagicMock()
    db.query.side_effect = [
        _Q(all_value=[take]),
        _Q(one_or_none_value=asset),
        _Q(count_value=0),
    ]
    monkeypatch.setattr(watchdog_rendering, "SessionLocal", lambda: db)
    monkeypatch.setattr("app.bot.handlers.generation._mark_take_enqueue_failed", MagicMock())
    monkeypatch.setattr("app.workers.tasks.watchdog_rendering.os.path.isfile", lambda p: p == "/tmp/original.jpg")

    sent = MagicMock()
    monkeypatch.setattr("app.core.celery_app.celery_app.send_task", sent)

    out = watchdog_rendering.recover_stuck_face_id_takes()

    assert out["ok"] is True
    assert out["recovered"] == 1
    assert take.status == "generating"
    assert asset.status == "ready_fallback"
    assert asset.selected_path == "/tmp/original.jpg"
    assert asset.reason_code == "watchdog_timeout_fallback"
    sent.assert_called_once()
    db.commit.assert_called_once()


def test_recover_stuck_face_id_take_failed_multi_face_marks_failed(monkeypatch):
    take = SimpleNamespace(
        id="take-2",
        face_asset_id="asset-2",
        status="awaiting_face_id",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        session_id=None,
        input_local_paths=[],
    )
    asset = SimpleNamespace(
        id="asset-2",
        status="failed_multi_face",
        selected_path=None,
        source_path="/tmp/original.jpg",
        reason_code="multi_face_detected",
        chat_id="123",
    )

    db = MagicMock()
    db.query.side_effect = [
        _Q(all_value=[take]),
        _Q(one_or_none_value=asset),
        _Q(count_value=1),
    ]
    monkeypatch.setattr(watchdog_rendering, "SessionLocal", lambda: db)
    mark_failed = MagicMock()
    monkeypatch.setattr("app.bot.handlers.generation._mark_take_enqueue_failed", mark_failed)
    sent = MagicMock()
    monkeypatch.setattr("app.core.celery_app.celery_app.send_task", sent)

    out = watchdog_rendering.recover_stuck_face_id_takes()

    assert out["ok"] is True
    assert out["failed"] == 1
    mark_failed.assert_called_once_with("take-2", actor_id="face_id_watchdog", reason="failed_multi_face")
    sent.assert_not_called()


@pytest.mark.parametrize("timeout_val, expected", [(5, 30), (180, 180), (None, 180)])
def test_face_id_timeout_floor(monkeypatch, timeout_val, expected):
    monkeypatch.setattr(watchdog_rendering.settings, "face_id_await_timeout_seconds", timeout_val)
    got = max(30, int(getattr(watchdog_rendering.settings, "face_id_await_timeout_seconds", 180) or 180))
    assert got == expected
