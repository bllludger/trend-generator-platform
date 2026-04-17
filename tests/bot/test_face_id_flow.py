from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.handlers.photo_upload import _prepare_face_asset_for_trend_flow


def _session_ctx(mock_db):
    @contextmanager
    def _cm():
        yield mock_db

    return _cm


@pytest.mark.asyncio
async def test_prepare_face_asset_when_disabled_marks_ready_fallback():
    mock_db = MagicMock()
    asset = SimpleNamespace(id="asset-1")
    settings_svc = MagicMock()
    settings_svc.as_dict.return_value = {"enabled": False}
    asset_svc = MagicMock()
    asset_svc.create_pending.return_value = asset

    with patch("app.bot.handlers.photo_upload.get_db_session", _session_ctx(mock_db)):
        with patch("app.bot.handlers.photo_upload.FaceIdSettingsService", return_value=settings_svc):
            with patch("app.bot.handlers.photo_upload.FaceAssetService", return_value=asset_svc):
                with patch("app.bot.handlers.photo_upload.enqueue_face_id_processing", new=AsyncMock(return_value=True)):
                    out = await _prepare_face_asset_for_trend_flow(
                        user_id="u1",
                        session_id="s1",
                        chat_id=123,
                        source_path="/tmp/source.jpg",
                    )

    assert out == "asset-1"
    asset_svc.apply_callback.assert_called_once()
    assert asset_svc.apply_callback.call_args.kwargs["status"] == "ready_fallback"
    assert asset_svc.apply_callback.call_args.kwargs["detector_meta"]["reason"] == "face_id_disabled"


@pytest.mark.asyncio
async def test_prepare_face_asset_when_enqueue_ok_keeps_pending():
    mock_db = MagicMock()
    asset = SimpleNamespace(id="asset-2")
    settings_svc = MagicMock()
    settings_svc.as_dict.return_value = {"enabled": True, "min_detection_confidence": 0.7}
    asset_svc = MagicMock()
    asset_svc.create_pending.return_value = asset

    with patch("app.bot.handlers.photo_upload.get_db_session", _session_ctx(mock_db)):
        with patch("app.bot.handlers.photo_upload.FaceIdSettingsService", return_value=settings_svc):
            with patch("app.bot.handlers.photo_upload.FaceAssetService", return_value=asset_svc):
                enqueue = AsyncMock(return_value=True)
                with patch("app.bot.handlers.photo_upload.enqueue_face_id_processing", new=enqueue):
                    out = await _prepare_face_asset_for_trend_flow(
                        user_id="u1",
                        session_id="s1",
                        chat_id=123,
                        source_path="/tmp/source.jpg",
                    )

    assert out == "asset-2"
    enqueue.assert_awaited_once()
    asset_svc.apply_callback.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_face_asset_when_enqueue_unavailable_fallbacks():
    mock_db = MagicMock()
    asset = SimpleNamespace(id="asset-3")
    settings_svc = MagicMock()
    settings_svc.as_dict.return_value = {"enabled": True}
    asset_svc = MagicMock()
    asset_svc.create_pending.return_value = asset

    with patch("app.bot.handlers.photo_upload.get_db_session", _session_ctx(mock_db)):
        with patch("app.bot.handlers.photo_upload.FaceIdSettingsService", return_value=settings_svc):
            with patch("app.bot.handlers.photo_upload.FaceAssetService", return_value=asset_svc):
                with patch("app.bot.handlers.photo_upload.enqueue_face_id_processing", new=AsyncMock(return_value=False)):
                    out = await _prepare_face_asset_for_trend_flow(
                        user_id="u1",
                        session_id="s1",
                        chat_id=123,
                        source_path="/tmp/source.jpg",
                    )

    assert out == "asset-3"
    asset_svc.apply_callback.assert_called_once()
    assert asset_svc.apply_callback.call_args.kwargs["status"] == "ready_fallback"
    assert asset_svc.apply_callback.call_args.kwargs["detector_meta"]["reason"] == "enqueue_unavailable"
