"""Product analytics: track funnel, quality, trends, attribution events (single source of truth)."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.product_event import ProductEvent
from app.models.user import User


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
    ) -> ProductEvent:
        """Record one product analytics event. Fills source/campaign from User when not provided."""
        if source is None or campaign_id is None:
            user = self.db.query(User).filter(User.id == user_id).first()
            if user:
                if source is None:
                    source = getattr(user, "traffic_source", None)
                if campaign_id is None:
                    campaign_id = getattr(user, "traffic_campaign", None)

        entry = ProductEvent(
            id=str(uuid4()),
            event_name=event_name,
            user_id=user_id,
            session_id=session_id,
            timestamp=datetime.now(timezone.utc),
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
            entity_type=entity_type,
            entity_id=entity_id,
            properties=properties or {},
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry
