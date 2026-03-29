"""Тесты quality/shadow API для telemetry endpoints admin."""

from types import SimpleNamespace
from unittest.mock import MagicMock


class TestTelemetryHealth:
    def test_health_degraded_when_quality_is_low(self):
        from app.api.routes.admin import telemetry_health

        q_total = MagicMock()
        q_total.filter.return_value.scalar.return_value = 8
        q_funnel = MagicMock()
        q_funnel.filter.return_value.scalar.return_value = 3
        q_funnel_missing = MagicMock()
        q_funnel_missing.filter.return_value.scalar.return_value = 1
        q_buttons = MagicMock()
        q_buttons.filter.return_value.group_by.return_value.all.return_value = [
            SimpleNamespace(button_id="", count=1),
            SimpleNamespace(button_id="unknown_btn", count=1),
        ]
        q_pay = MagicMock()
        q_pay.filter.return_value.all.return_value = [
            ({"schema_version": 2, "price": 0},),
            ({"schema_version": 2, "price": 10},),
        ]
        q_schema = MagicMock()
        q_schema.filter.return_value.group_by.return_value.all.return_value = [
            SimpleNamespace(action="bot_started", schema_version="2", count=2),
            SimpleNamespace(action="photo_uploaded", schema_version="2", count=1),
            SimpleNamespace(action="button_click", schema_version="2", count=2),
            SimpleNamespace(action="pay_success", schema_version="2", count=2),
            SimpleNamespace(action="mystery_event", schema_version="2", count=1),
            SimpleNamespace(action="bot_started", schema_version="", count=1),
        ]
        db = MagicMock()
        db.query.side_effect = [q_total, q_funnel, q_funnel_missing, q_buttons, q_pay, q_schema]

        result = telemetry_health(db=db, window_days=7)

        assert result["status"] == "degraded"
        assert result["data_quality"]["funnel_session_coverage_pct"] == 66.7
        assert result["data_quality"]["button_id_coverage_pct"] == 0.0
        assert result["data_quality"]["pay_success_valid_price_pct"] == 50.0
        assert result["data_quality"]["unknown_events"] == 1
        assert any("session_id" in warning for warning in result["quality_warnings"])
        assert any("button_id" in warning for warning in result["quality_warnings"])
        assert any("валидной цены" in warning for warning in result["quality_warnings"])

    def test_health_ok_when_payload_is_complete(self):
        from app.api.routes.admin import telemetry_health

        q_total = MagicMock()
        q_total.filter.return_value.scalar.return_value = 4
        q_funnel = MagicMock()
        q_funnel.filter.return_value.scalar.return_value = 2
        q_funnel_missing = MagicMock()
        q_funnel_missing.filter.return_value.scalar.return_value = 0
        q_buttons = MagicMock()
        q_buttons.filter.return_value.group_by.return_value.all.return_value = [
            SimpleNamespace(button_id="menu_create_photo", count=1),
        ]
        q_pay = MagicMock()
        q_pay.filter.return_value.all.return_value = [
            ({"schema_version": 2, "price": 20},),
        ]
        q_schema = MagicMock()
        q_schema.filter.return_value.group_by.return_value.all.return_value = [
            SimpleNamespace(action="bot_started", schema_version="2", count=1),
            SimpleNamespace(action="photo_uploaded", schema_version="2", count=1),
            SimpleNamespace(action="button_click", schema_version="2", count=1),
            SimpleNamespace(action="pay_success", schema_version="2", count=1),
        ]
        db = MagicMock()
        db.query.side_effect = [q_total, q_funnel, q_funnel_missing, q_buttons, q_pay, q_schema]

        result = telemetry_health(db=db, window_days=7)

        assert result["status"] == "ok"
        assert result["quality_warnings"] == []
        assert result["data_quality"]["funnel_session_coverage_pct"] == 100.0
        assert result["data_quality"]["button_id_coverage_pct"] == 100.0
        assert result["data_quality"]["pay_success_valid_price_pct"] == 100.0


class TestTelemetryFunnelAndButtons:
    def test_product_funnel_returns_shadow_and_diff(self):
        from app.api.routes.admin import telemetry_product_funnel

        db = MagicMock()

        q_legacy = MagicMock()
        q_legacy.filter.return_value.group_by.return_value.all.return_value = [
            ("bot_started", 10),
            ("photo_uploaded", 8),
        ]
        q_shadow = MagicMock()
        q_shadow.filter.return_value.group_by.return_value.all.return_value = [
            ("bot_started", 9),
            ("photo_uploaded", 7),
        ]
        q_events = MagicMock()
        q_events.filter.return_value.all.return_value = [
            ("bot_started", "s1"),
            ("bot_started", None),
            ("photo_uploaded", "s2"),
            ("photo_uploaded", None),
        ]
        db.query.side_effect = [q_legacy, q_shadow, q_events]

        result = telemetry_product_funnel(db=db, window_days=7)

        assert result["funnel_counts"]["bot_started"] == 10
        assert result["shadow_funnel_counts"]["bot_started"] == 9
        assert result["diff_funnel_counts"]["bot_started"] == -1
        assert result["data_quality"]["missing_session_events"] == 2
        assert result["data_quality"]["funnel_session_coverage_pct"] == 50.0
        assert result["quality_warnings"]

    def test_button_clicks_returns_unknown_group_and_coverage(self):
        from app.api.routes.admin import telemetry_button_clicks

        db = MagicMock()
        rows = [
            SimpleNamespace(button_id="menu_create_photo", count=5),
            SimpleNamespace(button_id="strange", count=2),
            SimpleNamespace(button_id="", count=1),
        ]
        db.query.return_value.filter.return_value.group_by.return_value.all.return_value = rows

        result = telemetry_button_clicks(db=db, window_days=7)

        assert result["by_button_id"]["menu_create_photo"] == 5
        assert result["by_button_id"]["strange"] == 2
        assert result["unknown_by_button_id"]["strange"] == 2
        assert result["data_quality"]["missing_button_id_events"] == 1
        assert result["data_quality"]["button_id_coverage_pct"] == 62.5
        assert any("неизвестными" in warning for warning in result["quality_warnings"])
