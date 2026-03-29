"""
Celery application: broker and result backend from settings.
Tasks are in app.workers.tasks (broadcast, etc.) and app.referral.tasks.
"""
import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from app.core.config import settings


@worker_process_init.connect
def _start_worker_metrics_server(**kwargs: object) -> None:
    """Expose /metrics in each worker process for Prometheus (generation_*, telegram_*, etc.)."""
    try:
        from app.utils.metrics_server import start_metrics_http_server
        port = int(os.environ.get("WORKER_METRICS_PORT", "9091"))
        start_metrics_http_server(port=port)
    except Exception:
        pass


celery_app = Celery(
    "app",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.tasks.broadcast",
        "app.workers.tasks.generation_v2",
        "app.workers.tasks.generate_take",
        "app.workers.tasks.deliver_hd",
        "app.workers.tasks.watchdog_rendering",
        "app.workers.tasks.delete_user_data",
        "app.workers.tasks.merge_photos",
        "app.workers.tasks.send_user_message",
        "app.workers.tasks.deliver_unlock",
        "app.workers.tasks.deliver_trial_bundle",
        "app.referral.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_time_limit=3600,
    result_expires=86400,
    beat_schedule={
        "reset-stuck-rendering": {
            "task": "app.workers.tasks.watchdog_rendering.reset_stuck_rendering",
            "schedule": crontab(minute="*/5"),
        },
        "detect-collection-drops": {
            "task": "app.workers.tasks.watchdog_rendering.detect_collection_drops",
            "schedule": crontab(hour="*/6"),
        },
    },
)

celery_app.conf.task_routes = {
    "app.workers.tasks.generate_take.generate_take": {"queue": "generation"},
}

celery_app.autodiscover_tasks(["app.workers.tasks", "app.referral"])
