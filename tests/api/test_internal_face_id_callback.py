import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.routes import internal as internal_route
from app.services.face_id.signature import build_face_id_signature


class _Req:
    def __init__(self, body: bytes, headers: dict[str, str]):
        self._body = body
        self.headers = headers

    async def body(self) -> bytes:
        return self._body


def _signed_headers(secret: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    sig = build_face_id_signature(secret, ts, body)
    return {
        "X-FaceId-Timestamp": ts,
        "X-FaceId-Signature": sig,
    }


def _waiting_take_query(waiting_take):
    q = MagicMock()
    q.filter.return_value.order_by.return_value.first.return_value = waiting_take
    return q


@pytest.mark.asyncio
async def test_callback_ready_enqueues_generation(monkeypatch):
    db = MagicMock()
    waiting_take = SimpleNamespace(id="take-1", status="awaiting_face_id", user_id="u1", session_id="s1")
    db.query.return_value = _waiting_take_query(waiting_take)
    monkeypatch.setattr(internal_route, "_pending_takes_count", lambda _db: 0)
    monkeypatch.setattr(internal_route, "_notify_chat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(internal_route, "AuditService", lambda _db: MagicMock())

    asset = SimpleNamespace(
        id="asset-1",
        user_id="u1",
        session_id="s1",
        chat_id="123",
        last_event_id=None,
        reason_code=None,
    )
    asset_svc = MagicMock()
    asset_svc.get.return_value = asset
    monkeypatch.setattr(internal_route, "FaceAssetService", lambda _db: asset_svc)
    send_task = MagicMock()
    monkeypatch.setattr("app.core.celery_app.celery_app.send_task", send_task)

    body = json.dumps(
        {
            "asset_id": "asset-1",
            "event_id": "evt-1",
            "status": "ready",
            "faces_detected": 1,
            "selected_path": "/tmp/processed.jpg",
            "source_path": "/tmp/source.jpg",
            "detector_meta": {"latency_ms": 10},
        }
    ).encode("utf-8")
    req = _Req(body, _signed_headers(internal_route.settings.face_id_callback_secret, body))

    payload = await internal_route.face_id_callback(request=req, db=db)
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert payload["take"] == "take-1"
    assert waiting_take.status == "generating"
    send_task.assert_called_once()
    asset_svc.apply_callback.assert_called_once()


@pytest.mark.asyncio
async def test_callback_duplicate_without_waiting_take_returns_duplicate(monkeypatch):
    db = MagicMock()
    db.query.return_value = _waiting_take_query(None)
    monkeypatch.setattr(internal_route, "_pending_takes_count", lambda _db: 0)
    monkeypatch.setattr(internal_route, "_notify_chat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(internal_route, "AuditService", lambda _db: MagicMock())

    asset = SimpleNamespace(
        id="asset-1",
        user_id="u1",
        session_id="s1",
        chat_id="123",
        last_event_id="evt-dup",
        reason_code=None,
    )
    asset_svc = MagicMock()
    asset_svc.get.return_value = asset
    monkeypatch.setattr(internal_route, "FaceAssetService", lambda _db: asset_svc)
    send_task = MagicMock()
    monkeypatch.setattr("app.core.celery_app.celery_app.send_task", send_task)

    body = json.dumps(
        {
            "asset_id": "asset-1",
            "event_id": "evt-dup",
            "status": "ready",
            "faces_detected": 1,
        }
    ).encode("utf-8")
    req = _Req(body, _signed_headers(internal_route.settings.face_id_callback_secret, body))
    payload = await internal_route.face_id_callback(request=req, db=db)

    assert payload == {"ok": True, "duplicate": True}
    send_task.assert_not_called()
    asset_svc.apply_callback.assert_not_called()


@pytest.mark.asyncio
async def test_callback_duplicate_with_waiting_take_retries_enqueue(monkeypatch):
    db = MagicMock()
    waiting_take = SimpleNamespace(id="take-2", status="awaiting_face_id", user_id="u1", session_id="s1")
    db.query.return_value = _waiting_take_query(waiting_take)
    monkeypatch.setattr(internal_route, "_pending_takes_count", lambda _db: 0)
    monkeypatch.setattr(internal_route, "_notify_chat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(internal_route, "AuditService", lambda _db: MagicMock())

    asset = SimpleNamespace(
        id="asset-2",
        user_id="u1",
        session_id="s1",
        chat_id="123",
        last_event_id="evt-same",
        reason_code=None,
    )
    asset_svc = MagicMock()
    asset_svc.get.return_value = asset
    monkeypatch.setattr(internal_route, "FaceAssetService", lambda _db: asset_svc)
    send_task = MagicMock()
    monkeypatch.setattr("app.core.celery_app.celery_app.send_task", send_task)

    body = json.dumps(
        {
            "asset_id": "asset-2",
            "event_id": "evt-same",
            "status": "ready_fallback",
            "faces_detected": 0,
            "selected_path": "/tmp/original.jpg",
        }
    ).encode("utf-8")
    req = _Req(body, _signed_headers(internal_route.settings.face_id_callback_secret, body))
    payload = await internal_route.face_id_callback(request=req, db=db)

    assert payload["take"] == "take-2"
    assert waiting_take.status == "generating"
    send_task.assert_called_once()
    asset_svc.apply_callback.assert_not_called()


@pytest.mark.asyncio
async def test_callback_ready_raises_503_if_enqueue_fails(monkeypatch):
    db = MagicMock()
    waiting_take = SimpleNamespace(id="take-3", status="awaiting_face_id", user_id="u1", session_id="s1")
    db.query.return_value = _waiting_take_query(waiting_take)
    monkeypatch.setattr(internal_route, "_pending_takes_count", lambda _db: 0)
    monkeypatch.setattr(internal_route, "_notify_chat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(internal_route, "AuditService", lambda _db: MagicMock())

    asset = SimpleNamespace(
        id="asset-3",
        user_id="u1",
        session_id="s1",
        chat_id="123",
        last_event_id=None,
        reason_code=None,
    )
    asset_svc = MagicMock()
    asset_svc.get.return_value = asset
    monkeypatch.setattr(internal_route, "FaceAssetService", lambda _db: asset_svc)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("queue down")

    monkeypatch.setattr("app.core.celery_app.celery_app.send_task", _boom)

    body = json.dumps(
        {
            "asset_id": "asset-3",
            "event_id": "evt-3",
            "status": "ready",
            "faces_detected": 1,
        }
    ).encode("utf-8")
    req = _Req(body, _signed_headers(internal_route.settings.face_id_callback_secret, body))

    with pytest.raises(HTTPException) as exc:
        await internal_route.face_id_callback(request=req, db=db)
    assert exc.value.status_code == 503
    assert waiting_take.status == "awaiting_face_id"
