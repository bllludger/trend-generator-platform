from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.trends import TrendOut
from app.services.trends.service import TrendService


router = APIRouter(prefix="/trends", tags=["trends"])


@router.get("", response_model=list[TrendOut])
def list_trends(db: Session = Depends(get_db)) -> list[TrendOut]:
    service = TrendService(db)
    trends = service.list_active()
    return [
        TrendOut(
            id=trend.id,
            name=trend.name,
            emoji=trend.emoji,
            description=trend.description,
            max_images=trend.max_images,
            enabled=trend.enabled,
            order_index=trend.order_index,
        )
        for trend in trends
    ]
