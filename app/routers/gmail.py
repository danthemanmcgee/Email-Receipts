from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db

router = APIRouter()


@router.post("/sync")
def trigger_gmail_sync(db: Session = Depends(get_db)):
    """Trigger Gmail sync - queues celery task."""
    try:
        from app.tasks.process_receipt import sync_gmail
        task = sync_gmail.delay()
        return {"status": "queued", "task_id": task.id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
