from fastapi import Depends, FastAPI, Header, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.services.cleanup.service import CleanupService


app = FastAPI(title="Cleanup Service")


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    if settings.admin_api_key and x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.post("/cleanup/run", dependencies=[Depends(require_admin)])
def run_cleanup(
    db: Session = Depends(get_db),
    older_than_hours: int = settings.cleanup_temp_ttl_hours,
) -> dict:
    """
    Удаляет только временные входные файлы старых завершённых Job (input_local_paths).
    Результаты генераций, примеры трендов и чеки не удаляются.
    """
    service = CleanupService(db)
    return service.cleanup_temp_files(older_than_hours)


@app.get("/health")
def health() -> dict:
    """Liveness probe - always returns 200 if app is running."""
    return {"status": "ok"}


@app.get("/ready")
def readiness(response: Response, db: Session = Depends(get_db)) -> dict:
    """Readiness probe - returns 503 if dependencies are unavailable."""
    try:
        from sqlalchemy import text
        import redis
        
        # Check database
        db.execute(text("SELECT 1"))
        
        # Check Redis
        redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        redis_client.ping()
        
        return {"status": "ready"}
    except Exception as e:
        response.status_code = 503
        return {"status": "not_ready", "error": str(e)}
