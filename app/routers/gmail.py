from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db

router = APIRouter()


@router.post("/sync")
def trigger_gmail_sync(db: Session = Depends(get_db)):
    """Trigger Gmail sync — queues celery task.

    Returns 503 with an actionable error if no Gmail connection is configured.
    """
    from app.models.integration import GoogleConnection, ConnectionType

    gmail_conn = (
        db.query(GoogleConnection)
        .filter(
            GoogleConnection.connection_type == ConnectionType.gmail,
            GoogleConnection.is_active.is_(True),
        )
        .first()
    )

    if not gmail_conn:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "gmail_not_connected",
                "message": "No Gmail connection found. "
                           "Please connect your Gmail account at /auth/google/gmail/start",
                "connect_url": "/auth/google/gmail/start",
            },
        )

    try:
        from app.tasks.process_receipt import sync_gmail
        task = sync_gmail.delay()
        return {"status": "queued", "task_id": task.id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
