"""Product analytics: track funnel, quality, trends, attribution events.
Events are written only to audit_logs (single event log). Telemetry metrics are built from audit.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.audit.service import AuditService
from app.utils.metrics import product_events_track_total

logger = logging.getLogger(__name__)


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
            entry = AuditService(self.db).log(
                actor_type="user",
                actor_id=actor_id,
                action=event_name,
                entity_type=entity_type or "user",
                entity_id=entity_id or user_id,
                payload=payload,
                user_id=user_id,
                session_id=session_id,
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
