import logging

import redis
from fastapi import FastAPI, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from face_id_app.celery_app import celery_app
from face_id_app.config import settings
from face_id_app.schemas import ProcessRequest, ProcessResponse

logger = logging.getLogger(__name__)
app = FastAPI(title="Face ID Service")


@app.post("/v1/process", status_code=status.HTTP_202_ACCEPTED, response_model=ProcessResponse)
def process_endpoint(payload: ProcessRequest) -> ProcessResponse:
    celery_app.send_task(
        "face_id.process",
        kwargs={"payload": payload.model_dump(mode="python")},
        queue="face_id",
    )
    return ProcessResponse(asset_id=payload.asset_id, status="queued")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready(response: Response) -> dict[str, str]:
    try:
        client = redis.Redis.from_url(settings.resolved_broker(), decode_responses=True)
        client.ping()
        return {"status": "ready"}
    except Exception as exc:
        logger.exception("face_id_ready_failed")
        response.status_code = 503
        return {"status": "not_ready", "error": str(exc)}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
