"""Overview v3 aggregated telemetry for product commercial core."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.models.audit_log import AuditLog
from app.models.payment import Payment
from app.models.user import User
from app.services.product_analytics.service import PRODUCT_ANALYTICS_SCHEMA_VERSION

WindowValue = Literal["24h", "7d", "30d", "90d", "all"]
FlowMode = Literal["canonical_only", "all_flows"]
TrustMode = Literal["trusted_only", "all_data"]
logger = logging.getLogger(__name__)

WINDOW_TO_DAYS: dict[Literal["24h", "7d", "30d", "90d"], int] = {
    "24h": 1,
    "7d": 7,
    "30d": 30,
    "90d": 90,
}

CANONICAL_STEP_MAP: dict[str, str] = {
    "entry_opened": "started",
    "primary_cta_clicked": "started",
    "bot_started": "started",
    "photo_uploaded": "uploaded",
    "take_preview_ready": "preview_ready",
    "favorite_selected": "favorite_selected",
    "paywall_viewed": "paywall_viewed",
    "pack_selected": "paywall_viewed",
    "pay_initiated": "pay_intent",
    "pay_success": "pay_success",
    "hd_delivered": "value_delivered",
}

ALL_FLOWS_STEP_MAP: dict[str, str] = {
    **CANONICAL_STEP_MAP,
    "start": "started",
    "take_started": "uploaded",
    "take_previews_ready": "preview_ready",
    "choose_best_variant": "favorite_selected",
    "favorites_auto_add": "favorite_selected",
    "paywall_variant_shown": "paywall_viewed",
    "pay_click": "pay_intent",
    "payment_pack": "pay_intent",
    "payment_unlock": "pay_intent",
    "unlock_delivered": "value_delivered",
}

PREVIEW_STARTED_ACTIONS = {
    "take_started",
    "generation_started",
}

PREVIEW_FAILED_ACTIONS = {
    "generation_failed",
}

CORE_STEPS = (
    "started",
    "uploaded",
    "preview_ready",
    "favorite_selected",
    "paywall_viewed",
    "pay_intent",
    "pay_success",
    "value_delivered",
)

TRANSITIONS = (
    ("start_upload", "started", "uploaded", "Start -> Upload"),
    ("upload_preview", "uploaded", "preview_ready", "Upload -> Preview"),
    ("preview_favorite", "preview_ready", "favorite_selected", "Preview -> Favorite"),
    ("favorite_paywall", "favorite_selected", "paywall_viewed", "Favorite -> Paywall"),
    ("paywall_purchase", "paywall_viewed", "pay_success", "Paywall -> Purchase"),
)

SESSION_REQUIRED_STEPS = {
    "uploaded",
    "preview_ready",
    "favorite_selected",
    "paywall_viewed",
    "pay_intent",
    "pay_success",
    "value_delivered",
}

MIN_SAMPLE_CONVERSION = 20
STAR_TO_RUB_FALLBACK = 1.3
OVERVIEW_QUERY_ROW_LIMIT = 500_000
EARLIEST_PAY_QUERY_ROW_LIMIT = 300_000


@dataclass
class EventRow:
    created_at: datetime
    action: str
    actor_id: str | None
    entity_type: str | None
    entity_id: str | None
    user_id: str | None
    session_id: str | None
    payload: dict[str, Any]


@dataclass
class NormalizedEvent:
    created_at: datetime
    action_raw: str
    step: str | None
    user_key: str | None
    session_key: str | None
    journey_key: str | None
    source: str | None
    campaign: str | None
    entry_type: str | None
    is_canonical_action: bool
    pack_id: str | None
    schema_version: int
    has_required_ids: bool
    payment_valid: bool
    price_stars: float
    price_rub: float


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _rate(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return round((num / den) * 100.0, 1)


def _delta_pct(current: float | int | None, previous: float | int | None) -> float | None:
    if current is None or previous is None:
        return None
    prev = float(previous)
    cur = float(current)
    if prev == 0:
        return None if cur != 0 else 0.0
    return round(((cur - prev) / prev) * 100.0, 1)


def _extract_payment_amounts(payload: dict[str, Any], star_to_rub: float) -> tuple[float, float, bool]:
    stars = 0.0
    for key in ("price", "price_stars", "stars"):
        v = _to_float(payload.get(key))
        if v > 0:
            stars = v
            break
    rub = 0.0
    for key in ("price_rub", "amount_rub"):
        v = _to_float(payload.get(key))
        if v > 0:
            rub = v
            break
    if rub <= 0:
        amount_kopecks = _to_float(payload.get("amount_kopecks"))
        if amount_kopecks > 0:
            rub = amount_kopecks / 100.0
    if stars <= 0 and rub > 0:
        stars = rub / star_to_rub
    if rub <= 0 and stars > 0:
        rub = stars * star_to_rub
    return stars, rub, (stars > 0 or rub > 0)


def _parse_schema_version(payload: dict[str, Any]) -> int:
    raw = payload.get("schema_version")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _derive_entry_type(action: str, payload: dict[str, Any], source: str | None) -> str:
    entry_type = str(payload.get("entry_type") or "").strip()
    if entry_type:
        return entry_type
    if payload.get("deep_link_id"):
        return "deep_link"
    if source:
        return "traffic_source"
    if action in ("start", "bot_started", "entry_opened"):
        return "start"
    return "unknown"


def _as_number(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _as_percent_value(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    if val != val:  # NaN guard
        return None
    return val


def _normalize_pack_id(value: Any) -> str | None:
    pack = str(value or "").strip().lower()
    return pack or None


def _build_kpi(
    *,
    value: float | int | None,
    numerator: int | None,
    denominator: int | None,
    delta_vs_prev_pct: float | None,
    trust_label: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "delta_vs_prev_pct": delta_vs_prev_pct,
        "trust_label": trust_label,
        "reason": reason,
    }


def _guard_conversion_value(value: float | None, denominator: int | None) -> tuple[float | None, str | None]:
    if denominator is None:
        return value, None
    if denominator <= 0:
        return None, "No denominator"
    if denominator < MIN_SAMPLE_CONVERSION:
        return None, "Sample size too small"
    if value is None:
        return None, "No denominator"
    if value < 0 or value > 100:
        return None, "Invalid conversion value"
    return value, None


def _metric_trust_label(
    *,
    session_coverage_pct: float,
    payment_validity_pct: float,
    canonical_coverage_pct: float,
    reconciliation_pct: float,
    include_payment: bool,
    denominator: int | None,
) -> str:
    if denominator is not None and denominator < MIN_SAMPLE_CONVERSION:
        return "Broken"
    components = [session_coverage_pct, canonical_coverage_pct]
    if include_payment:
        components.extend([payment_validity_pct, reconciliation_pct])
    min_score = min(components) if components else 0.0
    if min_score >= 95:
        return "Trusted"
    if min_score >= 80:
        return "Partial"
    if min_score >= 50:
        return "Directional"
    return "Broken"


def _trust_status(metrics: dict[str, float]) -> str:
    checks = [
        metrics.get("session_coverage_pct", 0.0),
        metrics.get("payment_validity_pct", 0.0),
        metrics.get("canonical_coverage_pct", 0.0),
        metrics.get("reconciliation_pct", 0.0),
        max(0.0, 100.0 - metrics.get("legacy_share_pct", 100.0)),
    ]
    min_score = min(checks)
    if min_score < 50:
        return "Broken"
    if min_score < 80:
        return "Degraded"
    if min_score < 95:
        return "Caution"
    return "Good"


def _trend_row(date_key: str) -> dict[str, Any]:
    return {
        "date": date_key,
        "started_users": 0,
        "photo_uploaded": 0,
        "preview_ready": 0,
        "favorite_selected": 0,
        "pay_success": 0,
    }


def _window_days(window: WindowValue) -> int:
    if window == "all":
        raise ValueError("Window 'all' uses dynamic calculation.")
    if window not in WINDOW_TO_DAYS:
        raise ValueError(f"Unsupported window: {window}")
    return WINDOW_TO_DAYS[window]


def _chunked(values: list[str], size: int = 1000) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def _load_user_lookups(db: Session, rows: list[EventRow]) -> tuple[dict[str, User], dict[str, User]]:
    user_ids = sorted({r.user_id for r in rows if r.user_id})
    actor_ids = sorted({r.actor_id for r in rows if r.actor_id})
    users_by_id: dict[str, User] = {}
    users_by_tg: dict[str, User] = {}
    for chunk in _chunked(user_ids):
        for u in db.query(User).filter(User.id.in_(chunk)).all():
            users_by_id[u.id] = u
    for chunk in _chunked(actor_ids):
        for u in db.query(User).filter(User.telegram_id.in_(chunk)).all():
            users_by_tg[u.telegram_id] = u
    return users_by_id, users_by_tg


def _normalize_rows(
    *,
    rows: list[EventRow],
    db: Session,
    flow_mode: FlowMode,
) -> list[NormalizedEvent]:
    step_map = CANONICAL_STEP_MAP if flow_mode == "canonical_only" else ALL_FLOWS_STEP_MAP
    users_by_id, users_by_tg = _load_user_lookups(db, rows)
    normalized: list[NormalizedEvent] = []
    star_to_rub = max(float(getattr(app_settings, "star_to_rub", STAR_TO_RUB_FALLBACK) or STAR_TO_RUB_FALLBACK), 0.01)
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        session_key = str(row.session_id or payload.get("session_id") or "").strip() or None
        user_key: str | None = None
        if row.user_id:
            user_key = row.user_id
        elif payload.get("user_id"):
            user_key = str(payload.get("user_id")).strip() or None
        elif row.entity_type == "user" and row.entity_id:
            user_key = row.entity_id
        elif row.actor_id and row.actor_id in users_by_tg:
            user_key = users_by_tg[row.actor_id].id
        elif row.actor_id:
            user_key = f"tg:{row.actor_id}"

        linked_user = None
        if row.user_id and row.user_id in users_by_id:
            linked_user = users_by_id[row.user_id]
        elif row.actor_id and row.actor_id in users_by_tg:
            linked_user = users_by_tg[row.actor_id]

        source = str(payload.get("source") or "").strip() or None
        campaign = str(payload.get("campaign_id") or "").strip() or None
        if linked_user is not None:
            if source is None:
                source = (getattr(linked_user, "traffic_source", None) or "").strip() or None
            if campaign is None:
                campaign = (getattr(linked_user, "traffic_campaign", None) or "").strip() or None

        entry_type = _derive_entry_type(row.action, payload, source)
        stars, rub, payment_valid = _extract_payment_amounts(payload, star_to_rub)
        pack_id = _normalize_pack_id(payload.get("pack_id"))
        schema_version = _parse_schema_version(payload)
        has_required_ids = bool(user_key and session_key)
        step = step_map.get(row.action)
        journey_key = session_key or (f"user:{user_key}" if user_key else None)

        normalized.append(
            NormalizedEvent(
                created_at=_to_utc(row.created_at),
                action_raw=row.action,
                step=step,
                user_key=user_key,
                session_key=session_key,
                journey_key=journey_key,
                source=source,
                campaign=campaign,
                entry_type=entry_type,
                is_canonical_action=row.action in CANONICAL_STEP_MAP,
                pack_id=pack_id,
                schema_version=schema_version,
                has_required_ids=has_required_ids,
                payment_valid=payment_valid,
                price_stars=stars,
                price_rub=rub,
            )
        )
    return normalized


def _filter_normalized(
    *,
    events: list[NormalizedEvent],
    source: str | None,
    campaign: str | None,
    entry_type: str | None,
) -> list[NormalizedEvent]:
    out: list[NormalizedEvent] = []
    source_f = source.strip() if source else None
    campaign_f = campaign.strip() if campaign else None
    entry_f = entry_type.strip() if entry_type else None
    for e in events:
        if source_f and e.source != source_f:
            continue
        if campaign_f and e.campaign != campaign_f:
            continue
        if entry_f and e.entry_type != entry_f:
            continue
        out.append(e)
    return out


def _trusted_only(events: list[NormalizedEvent]) -> list[NormalizedEvent]:
    out: list[NormalizedEvent] = []
    for e in events:
        if not e.has_required_ids:
            continue
        if e.schema_version < PRODUCT_ANALYTICS_SCHEMA_VERSION:
            continue
        if e.step == "pay_success" and not e.payment_valid:
            continue
        out.append(e)
    return out


def _earliest_pay_success_by_user(
    *,
    db: Session,
    candidate_user_keys: set[str],
    flow_mode: FlowMode,
) -> dict[str, datetime]:
    if not candidate_user_keys:
        return {}

    uuid_keys = {k for k in candidate_user_keys if not k.startswith("tg:")}
    tg_keys = {k[3:] for k in candidate_user_keys if k.startswith("tg:")}
    tg_from_users: set[str] = set()
    if uuid_keys:
        for row in db.query(User.telegram_id).filter(User.id.in_(list(uuid_keys))).all():
            if row[0]:
                tg_from_users.add(str(row[0]))
    actor_candidates = set(tg_keys) | tg_from_users

    if not uuid_keys and not actor_candidates:
        return {}

    seen_log_ids: set[str] = set()
    events: list[EventRow] = []

    def _append_row(r: Any) -> None:
        log_id = str(r.log_id)
        if log_id in seen_log_ids:
            return
        seen_log_ids.add(log_id)
        events.append(
            EventRow(
                created_at=r.created_at,
                action=r.action,
                actor_id=r.actor_id,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                user_id=r.user_id,
                session_id=r.session_id,
                payload=r.payload if isinstance(r.payload, dict) else {},
            )
        )

    base_columns = (
        AuditLog.id.label("log_id"),
        AuditLog.created_at,
        AuditLog.action,
        AuditLog.actor_id,
        AuditLog.entity_type,
        AuditLog.entity_id,
        AuditLog.user_id,
        AuditLog.session_id,
        AuditLog.payload,
    )
    for chunk in _chunked(sorted(uuid_keys), size=500):
        if len(events) >= EARLIEST_PAY_QUERY_ROW_LIMIT:
            break
        rows = (
            db.query(*base_columns)
            .filter(
                AuditLog.actor_type == "user",
                AuditLog.action == "pay_success",
                or_(
                    AuditLog.user_id.in_(chunk),
                    and_(AuditLog.entity_type == "user", AuditLog.entity_id.in_(chunk)),
                    AuditLog.payload["user_id"].astext.in_(chunk),
                ),
            )
            .order_by(AuditLog.created_at.asc())
            .all()
        )
        for row in rows:
            _append_row(row)
    for chunk in _chunked(sorted(actor_candidates), size=500):
        if len(events) >= EARLIEST_PAY_QUERY_ROW_LIMIT:
            break
        rows = (
            db.query(*base_columns)
            .filter(
                AuditLog.actor_type == "user",
                AuditLog.action == "pay_success",
                AuditLog.actor_id.in_(chunk),
            )
            .order_by(AuditLog.created_at.asc())
            .all()
        )
        for row in rows:
            _append_row(row)

    if len(events) >= EARLIEST_PAY_QUERY_ROW_LIMIT:
        logger.warning(
            "overview_v3 earliest-pay query truncated: candidates=%s limit=%s",
            len(candidate_user_keys),
            EARLIEST_PAY_QUERY_ROW_LIMIT,
        )

    normalized = _normalize_rows(rows=events, db=db, flow_mode=flow_mode)
    earliest: dict[str, datetime] = {}
    for e in normalized:
        if e.step != "pay_success" or not e.user_key:
            continue
        if e.user_key not in candidate_user_keys:
            continue
        prev = earliest.get(e.user_key)
        if prev is None or e.created_at < prev:
            earliest[e.user_key] = e.created_at
    return earliest


def _step_user_count(events: list[NormalizedEvent], step: str) -> int:
    return len({e.user_key for e in events if e.step == step and e.user_key})


def _step_journey_set(events: list[NormalizedEvent], step: str) -> set[str]:
    return {e.journey_key for e in events if e.step == step and e.journey_key}


def _payment_stars_amount(*, stars_amount: Any, amount_kopecks: Any, star_to_rub: float) -> int | None:
    stars = _to_float(stars_amount)
    if stars <= 0:
        kopecks = _to_float(amount_kopecks)
        if kopecks > 0:
            stars = kopecks / 100.0 / max(star_to_rub, 0.01)
    if stars <= 0:
        return None
    return int(round(stars))


def _counter_match_and_consume(left: Counter[Any], right: Counter[Any]) -> int:
    matched = 0
    for key in set(left.keys()).intersection(right.keys()):
        overlap = min(int(left.get(key, 0)), int(right.get(key, 0)))
        if overlap <= 0:
            continue
        matched += overlap
        left[key] -= overlap
        right[key] -= overlap
        if left[key] <= 0:
            left.pop(key, None)
        if right[key] <= 0:
            right.pop(key, None)
    return matched


def _reconciliation_breakdown(
    *,
    pay_events: list[NormalizedEvent],
    payment_rows: list[Any],
    star_to_rub: float,
) -> dict[str, int]:
    audit_count = len(pay_events)
    payment_count = len(payment_rows)
    if audit_count == 0 and payment_count == 0:
        return {
            "audit_count": 0,
            "payment_count": 0,
            "matched_session": 0,
            "matched_fallback_exact": 0,
            "matched_fallback_loose": 0,
        }

    matched_audit_idx: set[int] = set()
    matched_payment_idx: set[int] = set()

    audit_by_session: dict[str, list[int]] = defaultdict(list)
    payment_by_session: dict[str, list[int]] = defaultdict(list)
    for i, event in enumerate(pay_events):
        if event.session_key:
            audit_by_session[event.session_key].append(i)
    for i, row in enumerate(payment_rows):
        session_id = str(row.session_id or "").strip() or None
        if session_id:
            payment_by_session[session_id].append(i)

    matched_session = 0
    for session_key in set(audit_by_session.keys()).intersection(payment_by_session.keys()):
        audit_idxs = audit_by_session[session_key]
        payment_idxs = payment_by_session[session_key]
        overlap = min(len(audit_idxs), len(payment_idxs))
        if overlap <= 0:
            continue
        for idx in audit_idxs[:overlap]:
            matched_audit_idx.add(idx)
        for idx in payment_idxs[:overlap]:
            matched_payment_idx.add(idx)
        matched_session += overlap

    unmatched_audit = [e for i, e in enumerate(pay_events) if i not in matched_audit_idx]
    unmatched_payments = [r for i, r in enumerate(payment_rows) if i not in matched_payment_idx]

    audit_exact = Counter()
    pay_exact = Counter()
    for event in unmatched_audit:
        if not event.user_key or event.user_key.startswith("tg:"):
            continue
        key = (
            event.user_key,
            event.pack_id or "__unknown_pack__",
            int(round(event.price_stars)) if event.price_stars > 0 else None,
            event.created_at.date().isoformat(),
        )
        audit_exact[key] += 1
    for row in unmatched_payments:
        user_id = str(row.user_id or "").strip()
        if not user_id:
            continue
        key = (
            user_id,
            _normalize_pack_id(row.pack_id) or "__unknown_pack__",
            _payment_stars_amount(
                stars_amount=row.stars_amount,
                amount_kopecks=row.amount_kopecks,
                star_to_rub=star_to_rub,
            ),
            _to_utc(row.created_at).date().isoformat(),
        )
        pay_exact[key] += 1
    matched_fallback_exact = _counter_match_and_consume(audit_exact, pay_exact)

    audit_loose = Counter()
    pay_loose = Counter()
    for (user_id, pack_id, stars, _date), count in audit_exact.items():
        if stars is None and pack_id == "__unknown_pack__":
            continue
        audit_loose[(user_id, pack_id, stars)] += int(count)
    for (user_id, pack_id, stars, _date), count in pay_exact.items():
        if stars is None and pack_id == "__unknown_pack__":
            continue
        pay_loose[(user_id, pack_id, stars)] += int(count)
    matched_fallback_loose = _counter_match_and_consume(audit_loose, pay_loose)

    return {
        "audit_count": audit_count,
        "payment_count": payment_count,
        "matched_session": matched_session,
        "matched_fallback_exact": matched_fallback_exact,
        "matched_fallback_loose": matched_fallback_loose,
    }


def _trust_metrics(
    *,
    base_events_current: list[NormalizedEvent],
    db: Session,
    since: datetime,
    until: datetime,
    source: str | None,
    campaign: str | None,
    entry_type: str | None,
) -> tuple[dict[str, Any], dict[str, float]]:
    core_events = [e for e in base_events_current if e.step in CORE_STEPS]
    no_data = len(core_events) == 0
    session_required = [e for e in core_events if e.step in SESSION_REQUIRED_STEPS]
    with_session = sum(1 for e in session_required if e.session_key)
    session_coverage = round((with_session / len(session_required) * 100.0), 1) if session_required else 100.0

    pay_events = [e for e in core_events if e.step == "pay_success"]
    pay_valid = sum(1 for e in pay_events if e.payment_valid)
    payment_validity = round((pay_valid / len(pay_events) * 100.0), 1) if pay_events else 100.0

    canonical_core = sum(1 for e in core_events if e.is_canonical_action)
    canonical_coverage = round((canonical_core / len(core_events) * 100.0), 1) if core_events else 100.0
    legacy_share = round(100.0 - canonical_coverage, 1)

    star_to_rub = max(float(getattr(app_settings, "star_to_rub", STAR_TO_RUB_FALLBACK) or STAR_TO_RUB_FALLBACK), 0.01)
    payments_q = db.query(
        Payment.created_at.label("created_at"),
        Payment.user_id.label("user_id"),
        Payment.session_id.label("session_id"),
        Payment.pack_id.label("pack_id"),
        Payment.stars_amount.label("stars_amount"),
        Payment.amount_kopecks.label("amount_kopecks"),
    ).filter(
        Payment.status == "completed",
        Payment.created_at >= since,
        Payment.created_at < until,
    )
    if source or campaign:
        payments_q = payments_q.join(User, User.id == Payment.user_id)
        if source:
            payments_q = payments_q.filter(User.traffic_source == source)
        if campaign:
            payments_q = payments_q.filter(User.traffic_campaign == campaign)
    payment_rows = payments_q.all()
    recon = _reconciliation_breakdown(
        pay_events=pay_events,
        payment_rows=payment_rows,
        star_to_rub=star_to_rub,
    )
    reconciled_events = recon["matched_session"] + recon["matched_fallback_exact"] + recon["matched_fallback_loose"]
    reconciliation_den = max(recon["audit_count"], recon["payment_count"])
    if reconciliation_den <= 0:
        reconciliation = 100.0
        reconciliation_session_pct = 100.0
        reconciliation_fallback_pct = 0.0
    else:
        reconciliation = round((reconciled_events / reconciliation_den) * 100.0, 1)
        reconciliation_session_pct = round((recon["matched_session"] / reconciliation_den) * 100.0, 1)
        reconciliation_fallback_pct = round(
            ((recon["matched_fallback_exact"] + recon["matched_fallback_loose"]) / reconciliation_den) * 100.0,
            1,
        )

    score_map = {
        "session_coverage_pct": session_coverage,
        "payment_validity_pct": payment_validity,
        "canonical_coverage_pct": canonical_coverage,
        "reconciliation_pct": reconciliation,
        "legacy_share_pct": legacy_share,
    }
    warnings: list[str] = []
    if no_data:
        warnings.append("Нет данных для выбранного окна/фильтров.")
    if session_coverage < 95:
        warnings.append("Низкая полнота session_id в ключевых шагах.")
    if payment_validity < 95:
        warnings.append("Часть pay_success без валидной цены.")
    if canonical_coverage < 95:
        warnings.append("Высокая доля legacy-событий в ядре воронки.")
    if reconciliation < 95:
        warnings.append("Audit <> Payments расходятся после strict+fallback reconciliation.")
    if reconciliation_fallback_pct > 10:
        warnings.append("Заметная доля reconciliation собрана fallback-эвристикой.")
    if entry_type:
        warnings.append("Для entry_type reconciliation directional (payments не хранят entry_type).")
    if legacy_share > 50:
        warnings.append("Legacy share > 50%, метрики частично directional.")

    if no_data:
        score_map = {
            "session_coverage_pct": 0.0,
            "payment_validity_pct": 0.0,
            "canonical_coverage_pct": 0.0,
            "reconciliation_pct": 0.0,
            "legacy_share_pct": 0.0,
        }
        reconciliation_session_pct = 0.0
        reconciliation_fallback_pct = 0.0
    status = "Broken" if no_data else _trust_status(score_map)
    if entry_type and status == "Good":
        status = "Caution"
    trust = {
        "status": status,
        "session_coverage_pct": score_map["session_coverage_pct"],
        "payment_validity_pct": score_map["payment_validity_pct"],
        "canonical_coverage_pct": score_map["canonical_coverage_pct"],
        "reconciliation_pct": score_map["reconciliation_pct"],
        "reconciliation_session_pct": reconciliation_session_pct,
        "reconciliation_fallback_pct": reconciliation_fallback_pct,
        "reconciliation_matched_events": reconciled_events,
        "audit_pay_success_events": recon["audit_count"],
        "payments_completed_events": recon["payment_count"],
        "legacy_share_pct": score_map["legacy_share_pct"],
        "warnings": warnings,
    }
    return trust, score_map


def _time_to_preview(events: list[NormalizedEvent]) -> tuple[list[float], dict[str, list[float]]]:
    by_journey: dict[str, dict[str, datetime | None]] = {}
    for e in sorted(events, key=lambda x: x.created_at):
        if not e.journey_key:
            continue
        state = by_journey.setdefault(e.journey_key, {"start": None, "preview": None})
        if e.step in ("started", "uploaded") and state["start"] is None:
            state["start"] = e.created_at
        if e.step == "preview_ready" and state["preview"] is None:
            state["preview"] = e.created_at
    durations: list[float] = []
    durations_by_day: dict[str, list[float]] = {}
    for state in by_journey.values():
        start_ts = state["start"]
        preview_ts = state["preview"]
        if start_ts is None or preview_ts is None:
            continue
        sec = (preview_ts - start_ts).total_seconds()
        if sec < 0:
            continue
        durations.append(sec)
        day_key = preview_ts.date().isoformat()
        durations_by_day.setdefault(day_key, []).append(sec)
    return durations, durations_by_day


def _build_trends(
    *,
    events_current: list[NormalizedEvent],
    since: datetime,
    until: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    by_date_users: dict[str, dict[str, set[str]]] = {}
    revenue_by_date: dict[str, dict[str, Any]] = {}
    day = since.date()
    while day <= until.date():
        key = day.isoformat()
        by_date_users[key] = {k: set() for k in ("started", "uploaded", "preview_ready", "favorite_selected", "pay_success")}
        revenue_by_date[key] = {"orders": 0, "paid_users": set(), "revenue_rub": 0.0}
        day = day + timedelta(days=1)

    for e in events_current:
        key = e.created_at.date().isoformat()
        if key not in by_date_users:
            continue
        if e.step == "started" and e.user_key:
            by_date_users[key]["started"].add(e.user_key)
        if e.step == "uploaded" and e.user_key:
            by_date_users[key]["uploaded"].add(e.user_key)
        if e.step == "preview_ready" and e.user_key:
            by_date_users[key]["preview_ready"].add(e.user_key)
        if e.step == "favorite_selected" and e.user_key:
            by_date_users[key]["favorite_selected"].add(e.user_key)
        if e.step == "pay_success" and e.user_key:
            by_date_users[key]["pay_success"].add(e.user_key)
            if e.payment_valid:
                revenue_by_date[key]["orders"] += 1
                revenue_by_date[key]["paid_users"].add(e.user_key)
                revenue_by_date[key]["revenue_rub"] += e.price_rub

    trend_flow: list[dict[str, Any]] = []
    trend_revenue: list[dict[str, Any]] = []
    totals = {"started_users": 0, "pay_success_orders": 0}
    for key in sorted(by_date_users.keys()):
        started = len(by_date_users[key]["started"])
        uploaded = len(by_date_users[key]["uploaded"])
        preview = len(by_date_users[key]["preview_ready"])
        favorite = len(by_date_users[key]["favorite_selected"])
        pay_users = len(by_date_users[key]["pay_success"])
        flow_row = _trend_row(key)
        flow_row.update(
            {
                "started_users": started,
                "photo_uploaded": uploaded,
                "preview_ready": preview,
                "favorite_selected": favorite,
                "pay_success": pay_users,
            }
        )
        trend_flow.append(flow_row)
        revenue = revenue_by_date[key]
        rev = round(float(revenue["revenue_rub"]), 2)
        trend_revenue.append(
            {
                "date": key,
                "orders": int(revenue["orders"]),
                "paid_users": len(revenue["paid_users"]),
                "revenue": rev,
                "revenue_per_started_user": round(rev / started, 2) if started > 0 else None,
            }
        )
        totals["started_users"] += started
        totals["pay_success_orders"] += int(revenue["orders"])
    return trend_flow, trend_revenue, totals


def _bottlenecks(current: list[NormalizedEvent], previous: list[NormalizedEvent]) -> tuple[list[dict[str, Any]], str | None, str | None]:
    rows: list[dict[str, Any]] = []
    biggest_drop_step: str | None = None
    lowest_conv: float | None = None
    biggest_negative_delta: str | None = None
    lowest_delta: float | None = None
    for key, from_step, to_step, label in TRANSITIONS:
        from_set_cur = _step_journey_set(current, from_step)
        to_set_cur = _step_journey_set(current, to_step)
        numerator_cur = len(from_set_cur.intersection(to_set_cur))
        denom_cur = len(from_set_cur)
        conv_cur = _rate(numerator_cur, denom_cur)
        conv_cur_value, conv_cur_reason = _guard_conversion_value(conv_cur, denom_cur)

        from_set_prev = _step_journey_set(previous, from_step)
        to_set_prev = _step_journey_set(previous, to_step)
        numerator_prev = len(from_set_prev.intersection(to_set_prev))
        denom_prev = len(from_set_prev)
        conv_prev = _rate(numerator_prev, denom_prev)
        conv_prev_value, _ = _guard_conversion_value(conv_prev, denom_prev)
        delta = _delta_pct(conv_cur_value, conv_prev_value)

        if conv_cur_value is None:
            state = "Broken"
        elif conv_cur_value >= 70:
            state = "OK"
        elif conv_cur_value >= 40:
            state = "Watch"
        else:
            state = "Broken"

        rows.append(
            {
                "key": key,
                "label": label,
                "conversion_pct": conv_cur_value,
                "numerator": numerator_cur,
                "denominator": denom_cur,
                "delta_vs_prev_pct": delta,
                "state": state,
                "reason": conv_cur_reason,
            }
        )
        if conv_cur_value is not None and (lowest_conv is None or conv_cur_value < lowest_conv):
            lowest_conv = conv_cur_value
            biggest_drop_step = label
        if delta is not None and (lowest_delta is None or delta < lowest_delta):
            lowest_delta = delta
            biggest_negative_delta = label
    return rows, biggest_drop_step, biggest_negative_delta


def _build_summary(
    *,
    preview_reach_pct: float | None,
    purchase_rate_pct: float | None,
    biggest_drop_step: str | None,
    biggest_negative_delta: str | None,
    trust_status: str,
    preview_delta: float | None,
    purchase_delta: float | None,
) -> dict[str, str]:
    preview_reach_value = _as_percent_value(preview_reach_pct)
    purchase_rate_value = _as_percent_value(purchase_rate_pct)

    if preview_reach_value is None and purchase_rate_value is None:
        what = "Вход в flow есть, но из-за качества данных метрика reach пока неустойчива."
    elif purchase_rate_value is not None and purchase_rate_value < 2:
        what = "Доход до preview есть, но конверсия в покупку очень низкая."
    elif preview_reach_value is None:
        what = "Доход до preview есть, но метрика reach пока неустойчива из-за объема выборки."
    elif preview_reach_value >= 50:
        what = "Текущий поток в целом доходит до meaningful preview."
    else:
        what = "Большая часть входящего потока теряется до first meaningful preview."

    if trust_status in ("Broken", "Degraded"):
        main_problem = "Главная проблема сейчас — качество и согласованность событий телеметрии."
    elif biggest_drop_step:
        main_problem = f"Основной bottleneck: {biggest_drop_step}."
    else:
        main_problem = "Основной bottleneck пока не выявлен из-за недостатка данных."

    if preview_delta is None and purchase_delta is None:
        change = "Изменения к прошлому периоду пока невалидны из-за малого объема выборки."
    else:
        parts: list[str] = []
        if preview_delta is not None:
            parts.append(f"Preview reach {'вырос' if preview_delta >= 0 else 'снизился'} на {abs(preview_delta)}%.")
        if purchase_delta is not None:
            parts.append(f"Purchase rate {'вырос' if purchase_delta >= 0 else 'снизился'} на {abs(purchase_delta)}%.")
        if biggest_negative_delta:
            parts.append(f"Самое негативное изменение: {biggest_negative_delta}.")
        change = " ".join(parts)

    return {
        "what_is_happening": what,
        "main_problem": main_problem,
        "change_vs_prev": change,
    }


def build_overview_v3(
    *,
    db: Session,
    window: WindowValue,
    source: str | None,
    campaign: str | None,
    entry_type: str | None,
    flow_mode: FlowMode,
    trust_mode: TrustMode,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    step_map = CANONICAL_STEP_MAP if flow_mode == "canonical_only" else ALL_FLOWS_STEP_MAP
    tracked_actions = set(step_map.keys()) | PREVIEW_STARTED_ACTIONS | PREVIEW_FAILED_ACTIONS

    if window == "all":
        min_created_at = (
            db.query(func.min(AuditLog.created_at))
            .filter(
                AuditLog.actor_type == "user",
                AuditLog.action.in_(tracked_actions),
            )
            .scalar()
        )
        if min_created_at is not None:
            since = _to_utc(min_created_at)
            window_days = max(1, (now.date() - since.date()).days + 1)
        else:
            window_days = 1
            since = now - timedelta(days=1)
    else:
        window_days = _window_days(window)
        since = now - timedelta(days=window_days)

    prev_since = since - timedelta(days=window_days)

    query_rows = (
        db.query(
            AuditLog.created_at,
            AuditLog.action,
            AuditLog.actor_id,
            AuditLog.entity_type,
            AuditLog.entity_id,
            AuditLog.user_id,
            AuditLog.session_id,
            AuditLog.payload,
        )
        .filter(
            AuditLog.actor_type == "user",
            AuditLog.created_at >= prev_since,
            AuditLog.created_at < now,
            AuditLog.action.in_(tracked_actions),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(OVERVIEW_QUERY_ROW_LIMIT + 1)
        .all()
    )
    truncated = len(query_rows) > OVERVIEW_QUERY_ROW_LIMIT
    if truncated:
        query_rows = query_rows[:OVERVIEW_QUERY_ROW_LIMIT]
    rows = [
        EventRow(
            created_at=r.created_at,
            action=r.action,
            actor_id=r.actor_id,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            user_id=r.user_id,
            session_id=r.session_id,
            payload=r.payload if isinstance(r.payload, dict) else {},
        )
        for r in reversed(query_rows)
    ]

    normalized = _normalize_rows(rows=rows, db=db, flow_mode=flow_mode)
    normalized = _filter_normalized(events=normalized, source=source, campaign=campaign, entry_type=entry_type)

    current_all = [e for e in normalized if since <= e.created_at < now]
    previous_all = [e for e in normalized if prev_since <= e.created_at < since]
    trust_section, trust_scores = _trust_metrics(
        base_events_current=current_all,
        db=db,
        since=since,
        until=now,
        source=source,
        campaign=campaign,
        entry_type=entry_type,
    )

    if trust_mode == "trusted_only":
        current = _trusted_only(current_all)
        previous = _trusted_only(previous_all)
    else:
        current = current_all
        previous = previous_all

    started_users_set_cur = {e.user_key for e in current if e.step == "started" and e.user_key}
    started_users_set_prev = {e.user_key for e in previous if e.step == "started" and e.user_key}
    uploaded_users_set_cur = {e.user_key for e in current if e.step == "uploaded" and e.user_key}
    uploaded_users_set_prev = {e.user_key for e in previous if e.step == "uploaded" and e.user_key}
    preview_users_set_cur = {e.user_key for e in current if e.step == "preview_ready" and e.user_key}
    preview_users_set_prev = {e.user_key for e in previous if e.step == "preview_ready" and e.user_key}

    started_users_cur = len(started_users_set_cur)
    started_users_prev = len(started_users_set_prev)
    uploaded_users_cur = len(started_users_set_cur.intersection(uploaded_users_set_cur))
    uploaded_users_prev = len(started_users_set_prev.intersection(uploaded_users_set_prev))
    preview_users_cur = len(started_users_set_cur.intersection(preview_users_set_cur))
    preview_users_prev = len(started_users_set_prev.intersection(preview_users_set_prev))

    preview_sessions_cur = _step_journey_set(current, "preview_ready")
    preview_sessions_prev = _step_journey_set(previous, "preview_ready")
    favorite_sessions_cur = _step_journey_set(current, "favorite_selected")
    favorite_sessions_prev = _step_journey_set(previous, "favorite_selected")
    paywall_sessions_cur = _step_journey_set(current, "paywall_viewed")
    paywall_sessions_prev = _step_journey_set(previous, "paywall_viewed")
    pay_success_sessions_cur = _step_journey_set(current, "pay_success")
    pay_success_sessions_prev = _step_journey_set(previous, "pay_success")
    value_sessions_cur = _step_journey_set(current, "value_delivered")

    upload_rate_cur = _rate(uploaded_users_cur, started_users_cur)
    upload_rate_prev = _rate(uploaded_users_prev, started_users_prev)
    preview_reach_cur = _rate(preview_users_cur, started_users_cur)
    preview_reach_prev = _rate(preview_users_prev, started_users_prev)

    favorite_rate_cur = _rate(len(favorite_sessions_cur.intersection(preview_sessions_cur)), len(preview_sessions_cur))
    favorite_rate_prev = _rate(len(favorite_sessions_prev.intersection(preview_sessions_prev)), len(preview_sessions_prev))

    paywall_denom_cur = len(favorite_sessions_cur) if len(favorite_sessions_cur) > 0 else len(preview_sessions_cur)
    paywall_num_cur = len(paywall_sessions_cur.intersection(favorite_sessions_cur if len(favorite_sessions_cur) > 0 else preview_sessions_cur))
    paywall_rate_cur = _rate(paywall_num_cur, paywall_denom_cur)
    paywall_denom_prev = len(favorite_sessions_prev) if len(favorite_sessions_prev) > 0 else len(preview_sessions_prev)
    paywall_num_prev = len(paywall_sessions_prev.intersection(favorite_sessions_prev if len(favorite_sessions_prev) > 0 else preview_sessions_prev))
    paywall_rate_prev = _rate(paywall_num_prev, paywall_denom_prev)

    pay_users_cur = {e.user_key for e in current if e.step == "pay_success" and e.user_key}
    pay_users_prev = {e.user_key for e in previous if e.step == "pay_success" and e.user_key}
    earliest_pay_by_user = _earliest_pay_success_by_user(
        db=db,
        candidate_user_keys=pay_users_cur | pay_users_prev,
        flow_mode=flow_mode,
    )
    first_time_payers_cur = len(
        [
            u
            for u in pay_users_cur
            if u in started_users_set_cur
            and u in earliest_pay_by_user
            and since <= earliest_pay_by_user[u] < now
        ]
    )
    first_time_payers_prev = len(
        [
            u
            for u in pay_users_prev
            if u in started_users_set_prev
            and u in earliest_pay_by_user
            and prev_since <= earliest_pay_by_user[u] < since
        ]
    )
    first_purchase_rate_cur = _rate(first_time_payers_cur, started_users_cur)
    first_purchase_rate_prev = _rate(first_time_payers_prev, started_users_prev)

    revenue_cur = round(sum(e.price_rub for e in current if e.step == "pay_success" and e.payment_valid), 2)
    revenue_prev = round(sum(e.price_rub for e in previous if e.step == "pay_success" and e.payment_valid), 2)
    revenue_per_started_cur = round(revenue_cur / started_users_cur, 2) if started_users_cur > 0 else None
    revenue_per_started_prev = round(revenue_prev / started_users_prev, 2) if started_users_prev > 0 else None

    durations_cur, durations_by_day = _time_to_preview(current)
    durations_prev, _ = _time_to_preview(previous)
    median_time_cur = _median(durations_cur)
    median_time_prev = _median(durations_prev)
    p95_time_cur = _percentile(durations_cur, 95)
    p95_time_prev = _percentile(durations_prev, 95)

    preview_started_cur = {
        e.journey_key
        for e in current
        if e.journey_key and (e.action_raw in PREVIEW_STARTED_ACTIONS or e.step == "uploaded")
    }
    preview_started_prev = {
        e.journey_key
        for e in previous
        if e.journey_key and (e.action_raw in PREVIEW_STARTED_ACTIONS or e.step == "uploaded")
    }
    preview_failed_cur = {e.journey_key for e in current if e.journey_key and e.action_raw in PREVIEW_FAILED_ACTIONS}
    preview_failed_prev = {e.journey_key for e in previous if e.journey_key and e.action_raw in PREVIEW_FAILED_ACTIONS}
    preview_success_rate_cur = _rate(len(preview_sessions_cur.intersection(preview_started_cur)), len(preview_started_cur))
    preview_success_rate_prev = _rate(len(preview_sessions_prev.intersection(preview_started_prev)), len(preview_started_prev))
    all_failed_rate_cur = _rate(len(preview_failed_cur.intersection(preview_started_cur)), len(preview_started_cur))
    all_failed_rate_prev = _rate(len(preview_failed_prev.intersection(preview_started_prev)), len(preview_started_prev))
    value_delivery_rate_cur = _rate(len(value_sessions_cur.intersection(pay_success_sessions_cur)), len(pay_success_sessions_cur))
    value_delivery_rate_prev = _rate(
        len(_step_journey_set(previous, "value_delivered").intersection(pay_success_sessions_prev)),
        len(pay_success_sessions_prev),
    )
    preview_success_cur_value, preview_success_reason = _guard_conversion_value(
        preview_success_rate_cur,
        len(preview_started_cur),
    )
    all_failed_cur_value, all_failed_reason = _guard_conversion_value(
        all_failed_rate_cur,
        len(preview_started_cur),
    )
    value_delivery_cur_value, value_delivery_reason = _guard_conversion_value(
        value_delivery_rate_cur,
        len(pay_success_sessions_cur),
    )

    upload_rate_cur_value, upload_rate_reason = _guard_conversion_value(upload_rate_cur, started_users_cur)
    preview_reach_cur_value, preview_reach_reason = _guard_conversion_value(preview_reach_cur, started_users_cur)
    favorite_rate_cur_value, favorite_rate_reason = _guard_conversion_value(favorite_rate_cur, len(preview_sessions_cur))
    paywall_rate_cur_value, paywall_rate_reason = _guard_conversion_value(paywall_rate_cur, paywall_denom_cur)
    first_purchase_cur_value, first_purchase_reason = _guard_conversion_value(first_purchase_rate_cur, started_users_cur)

    kpis = {
        "started_users": _build_kpi(
            value=started_users_cur,
            numerator=started_users_cur,
            denominator=None,
            delta_vs_prev_pct=_delta_pct(started_users_cur, started_users_prev),
            trust_label=_metric_trust_label(
                session_coverage_pct=trust_scores["session_coverage_pct"],
                payment_validity_pct=trust_scores["payment_validity_pct"],
                canonical_coverage_pct=trust_scores["canonical_coverage_pct"],
                reconciliation_pct=trust_scores["reconciliation_pct"],
                include_payment=False,
                denominator=started_users_cur,
            ),
        ),
        "upload_rate": _build_kpi(
            value=upload_rate_cur_value,
            numerator=uploaded_users_cur,
            denominator=started_users_cur,
            delta_vs_prev_pct=_delta_pct(upload_rate_cur, upload_rate_prev),
            trust_label=_metric_trust_label(
                session_coverage_pct=trust_scores["session_coverage_pct"],
                payment_validity_pct=trust_scores["payment_validity_pct"],
                canonical_coverage_pct=trust_scores["canonical_coverage_pct"],
                reconciliation_pct=trust_scores["reconciliation_pct"],
                include_payment=False,
                denominator=started_users_cur,
            ),
            reason=upload_rate_reason,
        ),
        "preview_reach_rate": _build_kpi(
            value=preview_reach_cur_value,
            numerator=preview_users_cur,
            denominator=started_users_cur,
            delta_vs_prev_pct=_delta_pct(preview_reach_cur, preview_reach_prev),
            trust_label=_metric_trust_label(
                session_coverage_pct=trust_scores["session_coverage_pct"],
                payment_validity_pct=trust_scores["payment_validity_pct"],
                canonical_coverage_pct=trust_scores["canonical_coverage_pct"],
                reconciliation_pct=trust_scores["reconciliation_pct"],
                include_payment=False,
                denominator=started_users_cur,
            ),
            reason=preview_reach_reason,
        ),
        "median_time_to_preview_sec": _build_kpi(
            value=_as_number(median_time_cur),
            numerator=len(durations_cur),
            denominator=len(preview_started_cur),
            delta_vs_prev_pct=_delta_pct(median_time_cur, median_time_prev),
            trust_label=_metric_trust_label(
                session_coverage_pct=trust_scores["session_coverage_pct"],
                payment_validity_pct=trust_scores["payment_validity_pct"],
                canonical_coverage_pct=trust_scores["canonical_coverage_pct"],
                reconciliation_pct=trust_scores["reconciliation_pct"],
                include_payment=False,
                denominator=len(durations_cur),
            ),
        ),
        "favorite_selection_rate": _build_kpi(
            value=favorite_rate_cur_value,
            numerator=len(favorite_sessions_cur.intersection(preview_sessions_cur)),
            denominator=len(preview_sessions_cur),
            delta_vs_prev_pct=_delta_pct(favorite_rate_cur, favorite_rate_prev),
            trust_label=_metric_trust_label(
                session_coverage_pct=trust_scores["session_coverage_pct"],
                payment_validity_pct=trust_scores["payment_validity_pct"],
                canonical_coverage_pct=trust_scores["canonical_coverage_pct"],
                reconciliation_pct=trust_scores["reconciliation_pct"],
                include_payment=False,
                denominator=len(preview_sessions_cur),
            ),
            reason=favorite_rate_reason,
        ),
        "paywall_reach_rate": _build_kpi(
            value=paywall_rate_cur_value,
            numerator=paywall_num_cur,
            denominator=paywall_denom_cur,
            delta_vs_prev_pct=_delta_pct(paywall_rate_cur, paywall_rate_prev),
            trust_label=_metric_trust_label(
                session_coverage_pct=trust_scores["session_coverage_pct"],
                payment_validity_pct=trust_scores["payment_validity_pct"],
                canonical_coverage_pct=trust_scores["canonical_coverage_pct"],
                reconciliation_pct=trust_scores["reconciliation_pct"],
                include_payment=False,
                denominator=paywall_denom_cur,
            ),
            reason=paywall_rate_reason
            or ("Fallback denominator preview_ready used" if len(favorite_sessions_cur) == 0 and len(preview_sessions_cur) > 0 else None),
        ),
        "first_purchase_rate": _build_kpi(
            value=first_purchase_cur_value,
            numerator=first_time_payers_cur,
            denominator=started_users_cur,
            delta_vs_prev_pct=_delta_pct(first_purchase_rate_cur, first_purchase_rate_prev),
            trust_label=_metric_trust_label(
                session_coverage_pct=trust_scores["session_coverage_pct"],
                payment_validity_pct=trust_scores["payment_validity_pct"],
                canonical_coverage_pct=trust_scores["canonical_coverage_pct"],
                reconciliation_pct=trust_scores["reconciliation_pct"],
                include_payment=True,
                denominator=started_users_cur,
            ),
            reason=first_purchase_reason,
        ),
        "revenue_per_started_user": _build_kpi(
            value=revenue_per_started_cur,
            numerator=int(round(revenue_cur)),
            denominator=started_users_cur,
            delta_vs_prev_pct=_delta_pct(revenue_per_started_cur, revenue_per_started_prev),
            trust_label=_metric_trust_label(
                session_coverage_pct=trust_scores["session_coverage_pct"],
                payment_validity_pct=trust_scores["payment_validity_pct"],
                canonical_coverage_pct=trust_scores["canonical_coverage_pct"],
                reconciliation_pct=trust_scores["reconciliation_pct"],
                include_payment=True,
                denominator=started_users_cur,
            ),
            reason="Sample size too small" if started_users_cur < MIN_SAMPLE_CONVERSION else None,
        ),
    }

    trend_flow, trend_revenue, _totals = _build_trends(events_current=current, since=since, until=now)
    bottlenecks, biggest_drop_step, biggest_negative_delta = _bottlenecks(current, previous)

    latency_by_day = []
    for day_key in sorted(durations_by_day.keys()):
        vals = durations_by_day[day_key]
        latency_by_day.append(
            {
                "date": day_key,
                "median_time_to_preview_sec": _as_number(_median(vals)),
                "p95_time_to_preview_sec": _as_number(_percentile(vals, 95)),
            }
        )

    experience_health = {
        "preview_success_rate": _build_kpi(
            value=preview_success_cur_value,
            numerator=len(preview_sessions_cur.intersection(preview_started_cur)),
            denominator=len(preview_started_cur),
            delta_vs_prev_pct=_delta_pct(preview_success_rate_cur, preview_success_rate_prev),
            trust_label=_metric_trust_label(
                session_coverage_pct=trust_scores["session_coverage_pct"],
                payment_validity_pct=trust_scores["payment_validity_pct"],
                canonical_coverage_pct=trust_scores["canonical_coverage_pct"],
                reconciliation_pct=trust_scores["reconciliation_pct"],
                include_payment=False,
                denominator=len(preview_started_cur),
            ),
            reason=preview_success_reason,
        ),
        "all_variants_failed_rate": _build_kpi(
            value=all_failed_cur_value,
            numerator=len(preview_failed_cur.intersection(preview_started_cur)),
            denominator=len(preview_started_cur),
            delta_vs_prev_pct=_delta_pct(all_failed_rate_cur, all_failed_rate_prev),
            trust_label=_metric_trust_label(
                session_coverage_pct=trust_scores["session_coverage_pct"],
                payment_validity_pct=trust_scores["payment_validity_pct"],
                canonical_coverage_pct=trust_scores["canonical_coverage_pct"],
                reconciliation_pct=trust_scores["reconciliation_pct"],
                include_payment=False,
                denominator=len(preview_started_cur),
            ),
            reason=all_failed_reason,
        ),
        "median_time_to_first_preview_sec": _build_kpi(
            value=_as_number(median_time_cur),
            numerator=len(durations_cur),
            denominator=len(preview_started_cur),
            delta_vs_prev_pct=_delta_pct(median_time_cur, median_time_prev),
            trust_label=_metric_trust_label(
                session_coverage_pct=trust_scores["session_coverage_pct"],
                payment_validity_pct=trust_scores["payment_validity_pct"],
                canonical_coverage_pct=trust_scores["canonical_coverage_pct"],
                reconciliation_pct=trust_scores["reconciliation_pct"],
                include_payment=False,
                denominator=len(durations_cur),
            ),
        ),
        "p95_time_to_first_preview_sec": _build_kpi(
            value=_as_number(p95_time_cur),
            numerator=len(durations_cur),
            denominator=len(preview_started_cur),
            delta_vs_prev_pct=_delta_pct(p95_time_cur, p95_time_prev),
            trust_label=_metric_trust_label(
                session_coverage_pct=trust_scores["session_coverage_pct"],
                payment_validity_pct=trust_scores["payment_validity_pct"],
                canonical_coverage_pct=trust_scores["canonical_coverage_pct"],
                reconciliation_pct=trust_scores["reconciliation_pct"],
                include_payment=False,
                denominator=len(durations_cur),
            ),
        ),
        "value_delivery_success_rate": _build_kpi(
            value=value_delivery_cur_value,
            numerator=len(value_sessions_cur.intersection(pay_success_sessions_cur)),
            denominator=len(pay_success_sessions_cur),
            delta_vs_prev_pct=_delta_pct(value_delivery_rate_cur, value_delivery_rate_prev),
            trust_label=_metric_trust_label(
                session_coverage_pct=trust_scores["session_coverage_pct"],
                payment_validity_pct=trust_scores["payment_validity_pct"],
                canonical_coverage_pct=trust_scores["canonical_coverage_pct"],
                reconciliation_pct=trust_scores["reconciliation_pct"],
                include_payment=True,
                denominator=len(pay_success_sessions_cur),
            ),
            reason=value_delivery_reason,
        ),
        "latency_trend": latency_by_day,
    }

    summary = _build_summary(
        preview_reach_pct=preview_reach_cur_value,
        purchase_rate_pct=first_purchase_cur_value,
        biggest_drop_step=biggest_drop_step,
        biggest_negative_delta=biggest_negative_delta,
        trust_status=trust_section["status"],
        preview_delta=_delta_pct(preview_reach_cur, preview_reach_prev),
        purchase_delta=_delta_pct(first_purchase_rate_cur, first_purchase_rate_prev),
    )

    if truncated:
        warnings = list(trust_section.get("warnings", []))
        warnings.append("Срез обрезан по лимиту rows, часть данных не попала в расчет.")
        trust_section["warnings"] = warnings

    return {
        "window": window,
        "window_days": window_days,
        "source": source,
        "campaign": campaign,
        "entry_type": entry_type,
        "flow_mode": flow_mode,
        "trust_mode": trust_mode,
        "last_updated_at": now.isoformat(),
        "trust": trust_section,
        "kpis": kpis,
        "trend_flow": trend_flow,
        "trend_revenue": trend_revenue,
        "bottlenecks": {
            "steps": bottlenecks,
            "biggest_drop_step": biggest_drop_step,
            "biggest_negative_delta": biggest_negative_delta,
        },
        "experience_health": experience_health,
        "summary": summary,
    }
