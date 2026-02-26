"""
Celery application: broker and result backend from settings.
Tasks are in app.workers.tasks (broadcast, etc.) and app.referral.tasks.
"""
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

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
        "process-pending-referral-bonuses": {
            "task": "app.referral.tasks.process_pending_bonuses",
            "schedule": crontab(minute="*/30"),
        },
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
