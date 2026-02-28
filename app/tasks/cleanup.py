import logging
from datetime import datetime, timedelta

from app.tasks.celery_app import celery_app
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(name="app.tasks.cleanup.run_cleanup")
def run_cleanup():
    """Delete old receipts based on retention policy."""
    from app.database import SessionLocal
    from app.models.receipt import Receipt, ReceiptStatus
    from app.services.gmail_service import build_gmail_service_from_db

    now = datetime.utcnow()
    processed_cutoff = now - timedelta(days=settings.RETENTION_DAYS_PROCESSED)
    review_cutoff = now - timedelta(days=settings.RETENTION_DAYS_REVIEW)

    with SessionLocal() as db:
        deleted_count = 0
        # Processed receipts older than retention
        old_processed = (
            db.query(Receipt)
            .filter(
                Receipt.status == ReceiptStatus.processed,
                Receipt.updated_at < processed_cutoff,
            )
            .all()
        )
        for receipt in old_processed:
            gmail = build_gmail_service_from_db(db, user_id=receipt.user_id)
            _delete_gmail_message(gmail, receipt.gmail_message_id)
            db.delete(receipt)
            deleted_count += 1

        # Needs-review and failed receipts older than retention
        old_review = (
            db.query(Receipt)
            .filter(
                Receipt.status.in_([ReceiptStatus.needs_review, ReceiptStatus.failed]),
                Receipt.updated_at < review_cutoff,
            )
            .all()
        )
        for receipt in old_review:
            gmail = build_gmail_service_from_db(db, user_id=receipt.user_id)
            _delete_gmail_message(gmail, receipt.gmail_message_id)
            db.delete(receipt)
            deleted_count += 1

        db.commit()

    logger.info("Cleanup complete. Deleted %d receipts.", deleted_count)
    return {"status": "ok", "deleted": deleted_count}


def _delete_gmail_message(gmail, message_id: str) -> bool:
    """Trash a Gmail message."""
    if not gmail:
        return False
    try:
        gmail.users().messages().trash(userId="me", id=message_id).execute()
        return True
    except Exception as exc:
        logger.warning("Could not trash Gmail message %s: %s", message_id, exc)
        return False
