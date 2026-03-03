from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.constants import audience_in_target_audiences
from app.models.theme import Theme
from app.models.trend import Trend


class TrendService:
    def __init__(self, db: Session):
        self.db = db

    def list_active(self) -> list[Trend]:
        return (
            self.db.query(Trend)
            .outerjoin(Theme, Trend.theme_id == Theme.id)
            .filter(
                Trend.enabled.is_(True),
                or_(Trend.theme_id.is_(None), Theme.enabled.is_(True)),
            )
            .order_by(Theme.order_index.asc().nulls_last(), Trend.order_index.asc())
            .all()
        )

    def list_all(self) -> list[Trend]:
        return (
            self.db.query(Trend)
            .outerjoin(Theme, Trend.theme_id == Theme.id)
            .order_by(Theme.order_index.asc().nulls_last(), Trend.order_index.asc())
            .all()
        )

    def list_active_by_theme(self, theme_id: str, audience: str | None = None) -> list[Trend]:
        """Тренды одной тематики (enabled), порядок по order_index. Если audience задан — только тренды для этой ЦА."""
        trends = (
            self.db.query(Trend)
            .filter(Trend.theme_id == theme_id, Trend.enabled.is_(True))
            .order_by(Trend.order_index.asc())
            .all()
        )
        if not audience:
            return trends
        return [t for t in trends if audience_in_target_audiences(audience, getattr(t, "target_audiences", None))]

    def list_theme_ids_with_active_trends(self, audience: str | None = None) -> set[str]:
        """Theme_id тематик с хотя бы одним включённым трендом. Если audience задан — темы, у которых есть хотя бы один тренд для этой ЦА (проверяем тренды; тема может быть без ЦА и тогда показывается по трендам)."""
        stmt = (
            select(Trend.theme_id)
            .where(Trend.theme_id.isnot(None), Trend.enabled.is_(True))
            .distinct()
        )
        rows = self.db.execute(stmt).scalars().all()
        theme_ids = set(rows) if rows else set()
        if not audience:
            return theme_ids
        out = set()
        for tid in theme_ids:
            if self.list_active_by_theme(tid, audience):
                out.add(tid)
        return out

    def get(self, trend_id: str) -> Trend | None:
        return self.db.query(Trend).filter(Trend.id == trend_id).one_or_none()

    def create(self, data: dict) -> Trend:
        trend = Trend(**data)
        self.db.add(trend)
        self.db.commit()
        self.db.refresh(trend)
        return trend

    def update(self, trend: Trend, data: dict) -> Trend:
        for key, value in data.items():
            setattr(trend, key, value)
        self.db.add(trend)
        self.db.commit()
        self.db.refresh(trend)
        return trend
