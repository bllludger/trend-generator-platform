from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.product_analytics.overview_v3 import (
    _build_summary,
    _reconciliation_breakdown,
    build_overview_v3,
)
from app.services.product_analytics.service import PRODUCT_ANALYTICS_SCHEMA_VERSION


def _db_with_audit_rows(rows):
    q_logs = MagicMock()
    q_logs.filter.return_value.order_by.return_value.limit.return_value.all.return_value = rows

    q_payments = MagicMock()
    q_payments.filter.return_value.all.return_value = []

    db = MagicMock()
    db.query.side_effect = [q_logs, q_payments]
    return db


def test_overview_v3_no_data_returns_broken_trust():
    db = _db_with_audit_rows([])

    result = build_overview_v3(
        db=db,
        window="7d",
        source=None,
        campaign=None,
        entry_type=None,
        flow_mode="canonical_only",
        trust_mode="trusted_only",
    )

    assert result["trust"]["status"] == "Broken"
    assert any("Нет данных" in warning for warning in result["trust"]["warnings"])


def test_overview_v3_uses_desc_order_for_capped_query():
    q_logs = MagicMock()
    q_logs.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

    q_payments = MagicMock()
    q_payments.filter.return_value.all.return_value = []

    db = MagicMock()
    db.query.side_effect = [q_logs, q_payments]

    build_overview_v3(
        db=db,
        window="7d",
        source=None,
        campaign=None,
        entry_type=None,
        flow_mode="canonical_only",
        trust_mode="all_data",
    )

    order_arg = q_logs.filter.return_value.order_by.call_args[0][0]
    assert "DESC" in str(order_arg).upper()


def test_overview_v3_24h_trend_contains_current_day_bucket():
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        created_at=now,
        action="entry_opened",
        actor_id=None,
        entity_type=None,
        entity_id=None,
        user_id=None,
        session_id="session-1",
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "schema_version": PRODUCT_ANALYTICS_SCHEMA_VERSION,
        },
    )
    db = _db_with_audit_rows([row])

    result = build_overview_v3(
        db=db,
        window="24h",
        source=None,
        campaign=None,
        entry_type=None,
        flow_mode="canonical_only",
        trust_mode="all_data",
    )

    today = now.date().isoformat()
    flow_today = next((item for item in result["trend_flow"] if item["date"] == today), None)
    assert flow_today is not None
    assert flow_today["started_users"] == 1


def test_overview_v3_first_purchase_uses_historical_earliest_payment():
    now = datetime.now(timezone.utc)
    started_row = SimpleNamespace(
        created_at=now - timedelta(hours=1),
        action="entry_opened",
        actor_id=None,
        entity_type=None,
        entity_id=None,
        user_id=None,
        session_id="session-1",
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "schema_version": PRODUCT_ANALYTICS_SCHEMA_VERSION,
        },
    )
    pay_row = SimpleNamespace(
        created_at=now - timedelta(minutes=30),
        action="pay_success",
        actor_id=None,
        entity_type=None,
        entity_id=None,
        user_id=None,
        session_id="session-1",
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "schema_version": PRODUCT_ANALYTICS_SCHEMA_VERSION,
            "price": 100,
        },
    )
    db = _db_with_audit_rows([started_row, pay_row])

    with patch(
        "app.services.product_analytics.overview_v3._earliest_pay_success_by_user",
        return_value={"user-1": datetime(2000, 1, 1, tzinfo=timezone.utc)},
    ):
        result = build_overview_v3(
            db=db,
            window="7d",
            source=None,
            campaign=None,
            entry_type=None,
            flow_mode="canonical_only",
            trust_mode="all_data",
        )

    assert result["kpis"]["first_purchase_rate"]["numerator"] == 0


def test_reconciliation_breakdown_matches_by_session_first():
    now = datetime.now(timezone.utc)
    pay_events = [
        SimpleNamespace(
            session_key="session-1",
            user_key="user-1",
            pack_id="neo_pro",
            price_stars=100.0,
            created_at=now,
        )
    ]
    payment_rows = [
        SimpleNamespace(
            session_id="session-1",
            user_id="user-1",
            pack_id="neo_pro",
            stars_amount=100,
            amount_kopecks=None,
            created_at=now,
        )
    ]

    out = _reconciliation_breakdown(
        pay_events=pay_events,
        payment_rows=payment_rows,
        star_to_rub=1.3,
    )

    assert out["matched_session"] == 1
    assert out["matched_fallback_exact"] == 0
    assert out["matched_fallback_loose"] == 0


def test_reconciliation_breakdown_falls_back_to_user_pack_amount():
    now = datetime.now(timezone.utc)
    pay_events = [
        SimpleNamespace(
            session_key=None,
            user_key="user-1",
            pack_id="neo_start",
            price_stars=120.0,
            created_at=now,
        )
    ]
    payment_rows = [
        SimpleNamespace(
            session_id=None,
            user_id="user-1",
            pack_id="neo_start",
            stars_amount=120,
            amount_kopecks=None,
            created_at=now + timedelta(minutes=5),
        )
    ]

    out = _reconciliation_breakdown(
        pay_events=pay_events,
        payment_rows=payment_rows,
        star_to_rub=1.3,
    )

    assert out["matched_session"] == 0
    assert out["matched_fallback_exact"] == 1


def test_overview_v3_entry_type_filter_does_not_return_good_trust():
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        created_at=now,
        action="entry_opened",
        actor_id=None,
        entity_type=None,
        entity_id=None,
        user_id=None,
        session_id="session-1",
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "schema_version": PRODUCT_ANALYTICS_SCHEMA_VERSION,
            "entry_type": "start",
        },
    )
    db = _db_with_audit_rows([row])

    result = build_overview_v3(
        db=db,
        window="7d",
        source=None,
        campaign=None,
        entry_type="start",
        flow_mode="canonical_only",
        trust_mode="all_data",
    )

    assert result["trust"]["status"] in {"Caution", "Degraded", "Broken"}
    assert result["trust"]["status"] != "Good"
    assert any("entry_type" in warning for warning in result["trust"]["warnings"])


def test_build_summary_handles_none_preview_reach_without_crash():
    summary = _build_summary(
        preview_reach_pct=None,
        purchase_rate_pct=10.0,
        biggest_drop_step=None,
        biggest_negative_delta=None,
        trust_status="Good",
        preview_delta=None,
        purchase_delta=None,
    )

    assert summary["what_is_happening"] == "Доход до preview есть, но метрика reach пока неустойчива из-за объема выборки."
