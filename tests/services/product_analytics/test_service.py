"""Тесты ProductAnalyticsService: helper-контракт и нормализация payload."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _db_with_user(user):
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value.first.return_value = user
    db.query.return_value = q
    return db


class TestProductAnalyticsHelpers:
    def test_track_funnel_step_sets_contract_and_missing_session_flag(self):
        from app.services.product_analytics.service import (
            PRODUCT_ANALYTICS_SCHEMA_VERSION,
            ProductAnalyticsService,
        )

        user = SimpleNamespace(id="user-1", telegram_id=12345, traffic_source=None, traffic_campaign=None)
        db = _db_with_user(user)

        with (
            patch("app.services.product_analytics.service.AuditService") as audit_svc_cls,
            patch("app.services.product_analytics.service.product_events_track_total"),
        ):
            audit_svc_cls.return_value.log.return_value = {"ok": True}
            out = ProductAnalyticsService(db).track_funnel_step(
                "bot_started",
                user.id,
                session_id=None,
                source_component="bot",
            )

        assert out == {"ok": True}
        call_kw = audit_svc_cls.return_value.log.call_args[1]
        payload = call_kw["payload"]
        assert call_kw["action"] == "bot_started"
        assert call_kw["session_id"] is None
        assert payload["schema_version"] == PRODUCT_ANALYTICS_SCHEMA_VERSION
        assert payload["flow"] == "funnel"
        assert payload["source_component"] == "bot"
        assert payload["missing_required_session_id"] is True

    def test_track_button_click_marks_unknown_button_id(self):
        from app.services.product_analytics.service import ProductAnalyticsService

        user = SimpleNamespace(id="user-1", telegram_id=12345, traffic_source=None, traffic_campaign=None)
        db = _db_with_user(user)

        with (
            patch("app.services.product_analytics.service.AuditService") as audit_svc_cls,
            patch("app.services.product_analytics.service.product_events_track_total"),
        ):
            ProductAnalyticsService(db).track_button_click(
                user.id,
                button_id="strange_button",
                session_id="session-1",
                source_component="bot",
            )

        payload = audit_svc_cls.return_value.log.call_args[1]["payload"]
        assert payload["button_id"] == "strange_button"
        assert payload["unknown_button_id"] is True
        assert payload["flow"] == "buttons"

    def test_track_button_click_marks_missing_button_id(self):
        from app.services.product_analytics.service import ProductAnalyticsService

        user = SimpleNamespace(id="user-1", telegram_id=12345, traffic_source=None, traffic_campaign=None)
        db = _db_with_user(user)

        with (
            patch("app.services.product_analytics.service.AuditService") as audit_svc_cls,
            patch("app.services.product_analytics.service.product_events_track_total"),
        ):
            ProductAnalyticsService(db).track_button_click(
                user.id,
                button_id="  ",
                session_id="session-1",
                source_component="bot",
            )

        payload = audit_svc_cls.return_value.log.call_args[1]["payload"]
        assert payload["missing_button_id"] is True
        assert not payload.get("button_id")

    def test_track_payment_event_normalizes_price_fields(self):
        from app.services.product_analytics.service import ProductAnalyticsService

        user = SimpleNamespace(id="user-1", telegram_id=12345, traffic_source=None, traffic_campaign=None)
        db = _db_with_user(user)

        with (
            patch("app.services.product_analytics.service.AuditService") as audit_svc_cls,
            patch("app.services.product_analytics.service.product_events_track_total"),
        ):
            ProductAnalyticsService(db).track_payment_event(
                "pay_success",
                user.id,
                method="bank_transfer",
                session_id="session-1",
                pack_id="neo_pro",
                price_rub=260,
                source_component="service.payments",
            )

        payload = audit_svc_cls.return_value.log.call_args[1]["payload"]
        assert payload["flow"] == "payments"
        assert payload["method"] == "bank_transfer"
        assert payload["price_rub"] == 260.0
        assert payload["price"] > 0
        assert payload["price_stars"] == payload["price"]
        assert payload["stars"] == payload["price"]
        assert not payload.get("invalid_price_payload")

    def test_track_sets_unknown_event_name_for_non_catalog_event(self):
        from app.services.product_analytics.service import ProductAnalyticsService

        user = SimpleNamespace(id="user-1", telegram_id=12345, traffic_source=None, traffic_campaign=None)
        db = _db_with_user(user)

        with (
            patch("app.services.product_analytics.service.AuditService") as audit_svc_cls,
            patch("app.services.product_analytics.service.product_events_track_total"),
        ):
            ProductAnalyticsService(db).track("totally_new_event", user.id, properties={})

        payload = audit_svc_cls.return_value.log.call_args[1]["payload"]
        assert payload["unknown_event_name"] is True
        assert payload["flow"] == "product"
