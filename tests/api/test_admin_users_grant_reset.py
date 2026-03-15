"""
Тесты для admin users: grant-pack идемпотентность, reset-limits ответы, _resolve_user.
"""
from unittest.mock import MagicMock, patch

import pytest


class TestResolveUserByIdOrTelegram:
    """_resolve_user_by_id_or_telegram возвращает пользователя по id или telegram_id."""

    def test_returns_user_by_id_first(self):
        from app.api.routes.admin import _resolve_user_by_id_or_telegram

        db = MagicMock()
        user = MagicMock()
        user.id = "user-uuid"
        user.telegram_id = "123"
        db.query.return_value.filter.return_value.first.side_effect = [user]
        result = _resolve_user_by_id_or_telegram(db, "user-uuid")
        assert result is user
        assert db.query.return_value.filter.return_value.first.call_count == 1

    def test_returns_user_by_telegram_id_when_id_miss(self):
        from app.api.routes.admin import _resolve_user_by_id_or_telegram

        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [None, MagicMock()]
        result = _resolve_user_by_id_or_telegram(db, "123456")
        assert result is not None
        assert db.query.return_value.filter.return_value.first.call_count == 2

    def test_returns_none_when_not_found(self):
        from app.api.routes.admin import _resolve_user_by_id_or_telegram

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        result = _resolve_user_by_id_or_telegram(db, "nonexistent")
        assert result is None


class TestResetUserLimitsService:
    """UserService.reset_user_limits возвращает True/False по rowcount."""

    def test_returns_true_when_rows_updated(self):
        from app.services.users.service import UserService

        db = MagicMock()
        result_mock = MagicMock()
        result_mock.rowcount = 1
        db.execute.return_value = result_mock
        user = MagicMock()
        user.id = "user-1"
        svc = UserService(db)
        assert svc.reset_user_limits(user) is True

    def test_returns_false_when_no_rows_updated(self):
        from app.services.users.service import UserService

        db = MagicMock()
        result_mock = MagicMock()
        result_mock.rowcount = 0
        db.execute.return_value = result_mock
        user = MagicMock()
        user.id = "user-1"
        svc = UserService(db)
        assert svc.reset_user_limits(user) is False


class TestAdminGrantIdempotencyStore:
    """Кеш ответа grant-pack для идемпотентности: get/set с моком Redis."""

    def test_get_returns_none_when_key_missing(self):
        from app.services.idempotency import IdempotencyStore

        mock_client = MagicMock()
        mock_client.get.return_value = None
        with patch("app.services.idempotency.redis.Redis.from_url", return_value=mock_client):
            store = IdempotencyStore()
        assert store.get_grant_response("missing-key") is None
        mock_client.get.assert_called_once()

    def test_set_calls_setex_with_key_and_json_value(self):
        from app.services.idempotency import IdempotencyStore

        mock_client = MagicMock()
        with patch("app.services.idempotency.redis.Redis.from_url", return_value=mock_client):
            store = IdempotencyStore()
        response = {"ok": True, "message": "Пакет выдан", "session_id": None, "payment_id": "pay-1"}
        store.set_grant_response("key-123", response)
        mock_client.setex.assert_called_once()
        call_args = mock_client.setex.call_args[0]
        assert call_args[0] == "admin:grant_idempotency:key-123"
        assert '"ok": true' in call_args[2] and "pay-1" in call_args[2]

    def test_get_returns_deserialized_response(self):
        import json
        from app.services.idempotency import IdempotencyStore

        mock_client = MagicMock()
        cached = {"ok": True, "message": "Пакет выдан", "session_id": "s1", "payment_id": "p1"}
        mock_client.get.return_value = json.dumps(cached)
        with patch("app.services.idempotency.redis.Redis.from_url", return_value=mock_client):
            store = IdempotencyStore()
        result = store.get_grant_response("key-456")
        assert result == cached
