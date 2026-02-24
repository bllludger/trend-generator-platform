from fastapi import APIRouter, Depends, Response
import redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db


router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Liveness probe - always returns 200 if app is running."""
    return {"status": "ok"}


@router.get("/ready")
def readiness(response: Response, db: Session = Depends(get_db)) -> dict:
    """Readiness probe - returns 503 if dependencies are unavailable."""
    try:
        # Check database
        db.execute(text("SELECT 1"))
        
        # Check Redis
        redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        redis_client.ping()
        
        return {"status": "ready"}
    except Exception as e:
        response.status_code = 503
        return {"status": "not_ready", "error": str(e)}
