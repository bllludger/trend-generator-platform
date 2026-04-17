import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "face-id-service"))
sys.modules.setdefault("mediapipe", MagicMock())
sys.modules.setdefault("numpy", MagicMock())

from face_id_app import tasks as worker_tasks  # noqa: E402


def _payload(**overrides):
    base = {
        "asset_id": "asset-1",
        "source_path": "/data/generated_images/u1/source.jpg",
        "flow": "trend",
        "user_id": "u1",
        "chat_id": "123",
        "request_id": "req-1",
        "callback_url": "http://api/internal/face-id/callback",
        "callback_secret_id": "v1",
        "detector_config": {},
    }
    base.update(overrides)
    return base


def test_process_face_id_rejects_path_outside_storage(monkeypatch):
    monkeypatch.setattr(worker_tasks, "_ensure_metrics_server", lambda: None)
    monkeypatch.setattr(worker_tasks.settings, "storage_base_path", "/data/generated_images")
    with pytest.raises(ValueError, match="outside storage_base_path"):
        worker_tasks.process_face_id.run(payload=_payload(source_path="/etc/passwd"))


def test_process_face_id_rejects_callback_url_host(monkeypatch):
    monkeypatch.setattr(worker_tasks, "_ensure_metrics_server", lambda: None)
    monkeypatch.setattr(worker_tasks.settings, "storage_base_path", "/data/generated_images")
    monkeypatch.setattr(worker_tasks.settings, "callback_allowed_hosts", "api,localhost")
    with pytest.raises(ValueError, match="host is not allowed"):
        worker_tasks.process_face_id.run(payload=_payload(callback_url="http://evil.example/cb"))


def test_process_face_id_posts_callback_with_resolved_secret(monkeypatch):
    monkeypatch.setattr(worker_tasks, "_ensure_metrics_server", lambda: None)
    monkeypatch.setattr(worker_tasks.settings, "storage_base_path", "/data/generated_images")
    monkeypatch.setattr(worker_tasks.settings, "callback_allowed_hosts", "api,localhost")
    monkeypatch.setattr(worker_tasks.settings, "callback_timeout_seconds", 2.0)
    monkeypatch.setattr(worker_tasks.settings, "callback_max_retries", 2)
    monkeypatch.setattr(worker_tasks.settings, "callback_backoff_seconds", 1.0)
    monkeypatch.setattr(
        worker_tasks.settings.__class__,
        "resolve_callback_secret",
        lambda self, sid: f"secret-for-{sid}",
    )

    monkeypatch.setattr(
        worker_tasks,
        "process_asset",
        lambda payload: {
            "asset_id": payload["asset_id"],
            "status": "ready",
            "faces_detected": 1,
            "selected_path": "/data/generated_images/face_id/asset-1.jpg",
            "source_path": payload["source_path"],
            "detector_meta": {"latency_ms": 11, "model_version": "test-v1"},
        },
    )

    callback_spy = MagicMock()
    monkeypatch.setattr(worker_tasks, "post_callback_with_retry", callback_spy)

    out = worker_tasks.process_face_id.run(payload=_payload())

    assert out["status"] == "ready"
    assert out["faces_detected"] == 1
    callback_spy.assert_called_once()
    kwargs = callback_spy.call_args.kwargs
    assert kwargs["callback_secret"] == "secret-for-v1"
    assert kwargs["callback_url"] == "http://api/internal/face-id/callback"
    assert kwargs["payload"]["asset_id"] == "asset-1"
    assert kwargs["payload"]["status"] == "ready"


def test_process_face_id_wraps_detector_error_and_reports_failed(monkeypatch):
    monkeypatch.setattr(worker_tasks, "_ensure_metrics_server", lambda: None)
    monkeypatch.setattr(worker_tasks.settings, "storage_base_path", "/data/generated_images")
    monkeypatch.setattr(worker_tasks.settings, "callback_allowed_hosts", "api,localhost")
    monkeypatch.setattr(
        worker_tasks.settings.__class__,
        "resolve_callback_secret",
        lambda self, _sid: "secret",
    )

    def _boom(_payload):
        raise RuntimeError("detector crashed")

    monkeypatch.setattr(worker_tasks, "process_asset", _boom)
    callback_spy = MagicMock()
    monkeypatch.setattr(worker_tasks, "post_callback_with_retry", callback_spy)

    out = worker_tasks.process_face_id.run(payload=_payload())

    assert out["status"] == "failed_error"
    meta = out.get("detector_meta") or {}
    assert "RuntimeError: detector crashed" in str(meta.get("error") or "")
    callback_spy.assert_called_once()
