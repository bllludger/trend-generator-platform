"""Product analytics: track funnel, quality, trends, attribution events.
Events are written only to audit_logs (single event log). Telemetry metrics are built from audit.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.audit.service import AuditService
from app.utils.metrics import product_events_track_total

logger = logging.getLogger(__name__)


PRODUCT_ANALYTICS_SCHEMA_VERSION = 2

FUNNEL_EVENT_NAMES = (
    "bot_started",
    "photo_uploaded",
    "take_preview_ready",
    "favorite_selected",
    "paywall_viewed",
    "pack_selected",
    "pay_initiated",
    "pay_success",
    "hd_delivered",
)

PAYMENT_EVENT_NAMES = ("pay_initiated", "pay_success")

# Canonical set for health metrics and unknown-event detection.
# Keep this list broad to avoid false positives from existing production flows.
KNOWN_PRODUCT_EVENT_NAMES = {
    *FUNNEL_EVENT_NAMES,
    "button_click",
    "collection_started",
    "collection_complete",
    "payment_methods_shown",
    "payment_method_selected",
    "yoomoney_checkout_created",
    "trend_preview_ready",
    "trend_viewed",
    "trend_favorite_selected",
    "generation_started",
    "generation_completed",
    "generation_failed",
    "input_photo_analyzed",
    "traffic_attribution",
    "traffic_start",
    "consent_accepted",
    "generation_feedback",
    "generation_likeness_feedback",
    "generation_negative_reason",
    "bank_receipt_uploaded",
    "custom_prompt_submitted",
    "format_selected",
    "photo_merge_started",
    "photo_merge_count_selected",
    "photo_merge_photo_uploaded",
    "regenerate_clicked",
    "rescue_photo_uploaded",
    "rescue_reason_face",
    "rescue_reason_style",
    "rescue_reject_set",
    "rescue_reroll_started",
    "start",
    "take_started",
    "theme_selected",
    "trend_take_started",
    "choose_best_variant",
    "favorites_auto_add",
    "pay_click",
    "pay_failed",
    "yoomoney_payment_succeeded",
    "unlock_delivered",
    "unlock_delivery_failed",
    "unlock_with_tokens",
    "trial_to_studio_upgrade_success",
    "take_previews_ready",
    "copy_flow_reference_analyzed",
    "trial_slot_used",
    "trial_reroll_used",
    "trial_selection_queued",
    "trial_referral_reward_earned",
    "trial_referral_reward_claimed",
    "trial_bundle_pay_initiated",
    "trial_bundle_pay_success",
}

# Button IDs known to the telemetry UI. Prefixes support dynamic IDs (pack_*, bank_pack_*, etc.).
KNOWN_BUTTON_IDS = {
    "help",
    "trends",
    "cancel",
    "menu_profile",
    "referral_status",
    "referral_back_profile",
    "menu_create_photo",
    "menu_copy_style",
    "menu_merge_photos",
    "menu_shop",
    "nav_themes",
    "nav_trends",
    "nav_menu",
    "nav_profile",
    "profile_payment",
    "profile_support",
    "regenerate",
    "shop_open",
    "shop_open_tariff_better",
    "shop_how_buy_stars",
    "deletemydata",
    "paysupport",
    "terms",
    "success_menu",
    "success_more",
    "error_menu",
    "error_retry",
    "error_choose_trend",
    "bank_transfer",
    "bank_transfer_cancel",
    "bank_transfer_retry",
    "take_more",
    "open_favorites",
    "favorites_clear_all",
    "remove_fav",
    "select_hd",
    "deselect_hd",
    "hd_problem",
    "unlock_resend",
    "unlock_check",
    "pack_check",
    "session_status",
    "pay_other",
    "pay_yoomoney",
    "pay_yoomoney_link",
    "pay_stars",
}
KNOWN_BUTTON_PREFIXES = (
    "pack_",
    "bank_pack_",
    "variant_",
    "remove_fav_",
    "select_hd_",
    "deselect_hd_",
    "hd_problem_",
)

_DEDUP_SCAN_LIMIT = 20


def is_known_product_event(event_name: str) -> bool:
    return event_name in KNOWN_PRODUCT_EVENT_NAMES


def is_known_button_id(button_id: str) -> bool:
    b = (button_id or "").strip()
    if not b:
        return False
    if b in KNOWN_BUTTON_IDS:
        return True
    return any(b.startswith(prefix) for prefix in KNOWN_BUTTON_PREFIXES)


def _infer_flow(event_name: str) -> str:
    if event_name in FUNNEL_EVENT_NAMES:
        return "funnel"
    if event_name == "button_click":
        return "buttons"
    if event_name in PAYMENT_EVENT_NAMES:
        return "payments"
    if event_name.startswith("generation_") or event_name.startswith("take_"):
        return "generation"
    return "product"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _payload_for_audit(
    *,
    properties: dict[str, Any] | None,
    trend_id: str | None,
    pack_id: str | None,
    source: str | None,
    campaign_id: str | None,
    creative_id: str | None,
    deep_link_id: str | None,
    device_type: str | None,
    country: str | None,
    take_id: str | None,
    job_id: str | None,
) -> dict[str, Any]:
    out = dict(properties or {})
    if trend_id is not None:
        out["trend_id"] = trend_id
    if pack_id is not None:
        out["pack_id"] = pack_id
    if source is not None:
        out["source"] = source
    if campaign_id is not None:
        out["campaign_id"] = campaign_id
    if creative_id is not None:
        out["creative_id"] = creative_id
    if deep_link_id is not None:
        out["deep_link_id"] = deep_link_id
    if device_type is not None:
        out["device_type"] = device_type
    if country is not None:
        out["country"] = country
    if take_id is not None:
        out["take_id"] = take_id
    if job_id is not None:
        out["job_id"] = job_id
    return out


class ProductAnalyticsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _dedupe_window_seconds(self, event_name: str) -> int:
        if event_name == "button_click":
            return 2
        if event_name in PAYMENT_EVENT_NAMES:
            return 300
        if event_name in FUNNEL_EVENT_NAMES:
            return 30
        return 10

    def _event_signature(
        self,
        *,
        event_name: str,
        user_id: str,
        session_id: str | None,
        payload: dict[str, Any],
    ) -> str:
        signature_payload: dict[str, Any] = {
            "event_name": event_name,
            "user_id": user_id,
            "session_id": session_id or "",
        }
        # Keep only stable, high-signal fields for dedupe; ignore volatile timestamps.
        stable_keys = (
            "button_id",
            "trend_id",
            "pack_id",
            "take_id",
            "job_id",
            "method",
            "price",
            "price_rub",
            "currency",
            "flow",
            "source_component",
            "entry_type",
        )
        for key in stable_keys:
            value = payload.get(key)
            if value is not None:
                signature_payload[key] = value
        digest_source = json.dumps(signature_payload, ensure_ascii=True, sort_keys=True, default=str)
        return hashlib.sha1(digest_source.encode("utf-8")).hexdigest()

    def _is_recent_duplicate(
        self,
        *,
        event_name: str,
        user_id: str,
        signature: str,
    ) -> bool:
        since = datetime.now(timezone.utc) - timedelta(seconds=self._dedupe_window_seconds(event_name))
        rows = (
            self.db.query(AuditLog)
            .filter(
                AuditLog.actor_type == "user",
                AuditLog.user_id == user_id,
                AuditLog.action == event_name,
                AuditLog.created_at >= since,
            )
            .order_by(AuditLog.created_at.desc())
            .limit(_DEDUP_SCAN_LIMIT)
            .all()
        )
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            if str(payload.get("_event_signature") or "") == signature:
                return True
        return False

    def track_funnel_step(
        self,
        event_name: str,
        user_id: str,
        *,
        session_id: str | None,
        source_component: str = "bot",
        trend_id: str | None = None,
        pack_id: str | None = None,
        take_id: str | None = None,
        job_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> AuditLog | None:
        payload = dict(properties or {})
        effective_session_id = _clean_optional_str(session_id or payload.get("session_id"))
        if not effective_session_id:
            payload["missing_required_session_id"] = True
        return self.track(
            event_name,
            user_id,
            session_id=effective_session_id,
            trend_id=trend_id,
            pack_id=pack_id,
            take_id=take_id,
            job_id=job_id,
            entity_type=entity_type,
            entity_id=entity_id,
            properties=payload,
            flow="funnel",
            source_component=source_component,
            schema_version=PRODUCT_ANALYTICS_SCHEMA_VERSION,
        )

    def track_button_click(
        self,
        user_id: str,
        *,
        button_id: str,
        session_id: str | None = None,
        source_component: str = "bot",
        trend_id: str | None = None,
        pack_id: str | None = None,
        take_id: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> AuditLog | None:
        payload = dict(properties or {})
        bid = (button_id or "").strip()
        if bid:
            payload["button_id"] = bid
            if not is_known_button_id(bid):
                payload["unknown_button_id"] = True
        else:
            payload["missing_button_id"] = True
        return self.track(
            "button_click",
            user_id,
            session_id=session_id,
            trend_id=trend_id,
            pack_id=pack_id,
            take_id=take_id,
            properties=payload,
            flow="buttons",
            source_component=source_component,
            schema_version=PRODUCT_ANALYTICS_SCHEMA_VERSION,
        )

    def track_payment_event(
        self,
        event_name: str,
        user_id: str,
        *,
        method: str,
        session_id: str | None = None,
        pack_id: str | None = None,
        currency: str | None = None,
        price: float | int | None = None,
        price_rub: float | int | None = None,
        source_component: str = "bot",
        properties: dict[str, Any] | None = None,
    ) -> AuditLog | None:
        payload = dict(properties or {})
        effective_session_id = _clean_optional_str(session_id or payload.get("session_id"))
        if method:
            payload["method"] = method
        price_value = _to_float(price)
        price_rub_value = _to_float(price_rub)
        rate = max(float(getattr(app_settings, "star_to_rub", 1.3) or 1.3), 0.01)
        if (price_value is None or price_value <= 0) and price_rub_value and price_rub_value > 0:
            price_value = round(price_rub_value / rate, 2)
        if (price_rub_value is None or price_rub_value <= 0) and price_value and price_value > 0:
            price_rub_value = round(price_value * rate, 2)
        if price_value is not None:
            payload["price"] = price_value
            payload["price_stars"] = price_value
            payload["stars"] = price_value
        if price_rub_value is not None:
            payload["price_rub"] = price_rub_value
        if currency:
            payload["currency"] = currency
        if not effective_session_id:
            payload["missing_required_session_id"] = True
        if not ((price_value or 0) > 0 or (price_rub_value or 0) > 0):
            payload["invalid_price_payload"] = True
        return self.track(
            event_name,
            user_id,
            session_id=effective_session_id,
            pack_id=pack_id,
            properties=payload,
            flow="payments",
            source_component=source_component,
            schema_version=PRODUCT_ANALYTICS_SCHEMA_VERSION,
        )

    def track(
        self,
        event_name: str,
        user_id: str,
        *,
        session_id: str | None = None,
        trend_id: str | None = None,
        pack_id: str | None = None,
        source: str | None = None,
        campaign_id: str | None = None,
        creative_id: str | None = None,
        deep_link_id: str | None = None,
        device_type: str | None = None,
        country: str | None = None,
        take_id: str | None = None,
        job_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        properties: dict[str, Any] | None = None,
        flow: str | None = None,
        source_component: str | None = None,
        schema_version: int | None = None,
    ) -> AuditLog | None:
        """Record one product analytics event to audit_logs (single event log). Fills source/campaign from User when not provided.
        On DB error logs and returns None so the main flow is not broken.
        """
        user = None
        if source is None or campaign_id is None:
            user = self.db.query(User).filter(User.id == user_id).first()
            if user:
                if source is None:
                    source = getattr(user, "traffic_source", None)
                if campaign_id is None:
                    campaign_id = getattr(user, "traffic_campaign", None)
        try:
            actor_user = user or self.db.query(User).filter(User.id == user_id).first()
            actor_id = str(actor_user.telegram_id) if actor_user else None
            payload = _payload_for_audit(
                properties=properties,
                trend_id=trend_id,
                pack_id=pack_id,
                source=source,
                campaign_id=campaign_id,
                creative_id=creative_id,
                deep_link_id=deep_link_id,
                device_type=device_type,
                country=country,
                take_id=take_id,
                job_id=job_id,
            )
            effective_session_id = _clean_optional_str(session_id or payload.get("session_id"))
            payload["user_id"] = user_id
            if effective_session_id:
                payload["session_id"] = effective_session_id
            try:
                schema_num = int(schema_version or PRODUCT_ANALYTICS_SCHEMA_VERSION)
            except (TypeError, ValueError):
                schema_num = PRODUCT_ANALYTICS_SCHEMA_VERSION
            payload["schema_version"] = schema_num
            payload["flow"] = flow or _infer_flow(event_name)
            payload["source_component"] = source_component or "bot"
            if event_name in FUNNEL_EVENT_NAMES and not effective_session_id:
                payload["missing_required_session_id"] = True
            if event_name == "button_click":
                button_id = str(payload.get("button_id") or "").strip()
                if not button_id:
                    payload["missing_button_id"] = True
                else:
                    payload["button_id"] = button_id
                    if not is_known_button_id(button_id):
                        payload["unknown_button_id"] = True
            if not is_known_product_event(event_name):
                payload["unknown_event_name"] = True
            signature = self._event_signature(
                event_name=event_name,
                user_id=user_id,
                session_id=effective_session_id,
                payload=payload,
            )
            payload["_event_signature"] = signature
            if self._is_recent_duplicate(event_name=event_name, user_id=user_id, signature=signature):
                product_events_track_total.labels(event_name=event_name, status="duplicate_skip").inc()
                return None
            entry = AuditService(self.db).log(
                actor_type="user",
                actor_id=actor_id,
                action=event_name,
                entity_type=entity_type or "user",
                entity_id=entity_id or user_id,
                payload=payload,
                user_id=user_id,
                session_id=effective_session_id,
            )
            product_events_track_total.labels(event_name=event_name, status="ok").inc()
            return entry
        except Exception as e:
            product_events_track_total.labels(event_name=event_name, status="db_error").inc()
            logger.warning(
                "product_analytics track (audit) failed: event=%s user_id=%s take_id=%s job_id=%s error=%s",
                event_name,
                user_id,
                take_id,
                job_id,
                e,
                exc_info=True,
            )
            return None
