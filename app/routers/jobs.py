from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.services.auth_service import get_current_user

router = APIRouter()


class JobRunResponse(BaseModel):
    id: int
    job_type: str
    status: str
    task_id: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    details: Optional[str] = None
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


@router.get("/recent", response_model=List[JobRunResponse])
def list_recent_jobs(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the most recent job runs for the current user (newest first)."""
    from app.models.job import JobRun
    return (
        db.query(JobRun)
        .filter(JobRun.user_id == current_user.id)
        .order_by(JobRun.started_at.desc())
        .limit(limit)
        .all()
    )


@router.post("/cleanup")
def trigger_cleanup(current_user: User = Depends(get_current_user)):
    """Trigger cleanup job."""
    try:
        from app.tasks.cleanup import run_cleanup
        task = run_cleanup.delay()
        return {"status": "queued", "task_id": task.id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
