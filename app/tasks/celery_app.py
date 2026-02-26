from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "receipt_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.process_receipt", "app.tasks.cleanup"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    beat_schedule={
        "gmail-sync": {
            "task": "app.tasks.process_receipt.sync_gmail",
            "schedule": settings.GMAIL_POLL_INTERVAL_SECONDS,
        },
        "cleanup": {
            "task": "app.tasks.cleanup.run_cleanup",
            "schedule": 86400,
        },
    },
)
