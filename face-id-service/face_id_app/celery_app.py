from celery import Celery

from face_id_app.config import settings


celery_app = Celery(
    "face_id_app",
    broker=settings.resolved_broker(),
    backend=settings.resolved_backend(),
    include=["face_id_app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
)

celery_app.conf.task_routes = {
    "face_id.process": {"queue": "face_id"},
}
