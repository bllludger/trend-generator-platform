from sqlalchemy import or_
from sqlalchemy.orm import Session

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

    def list_active_by_theme(self, theme_id: str) -> list[Trend]:
        """Тренды одной тематики (enabled), порядок по order_index. Для бота: постраничный показ внутри темы."""
        return (
            self.db.query(Trend)
            .filter(Trend.theme_id == theme_id, Trend.enabled.is_(True))
            .order_by(Trend.order_index.asc())
            .all()
        )

    def list_theme_ids_with_active_trends(self) -> set[str]:
        """Theme_id тематик, у которых есть хотя бы один включённый тренд. Для бота: показывать только такие тематики."""
        from sqlalchemy import select
        stmt = (
            select(Trend.theme_id)
            .where(Trend.theme_id.isnot(None), Trend.enabled.is_(True))
            .distinct()
        )
        rows = self.db.execute(stmt).scalars().all()
        return set(rows) if rows else set()

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
