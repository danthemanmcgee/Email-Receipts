from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/cleanup")
def trigger_cleanup():
    """Trigger cleanup job."""
    try:
        from app.tasks.cleanup import run_cleanup
        task = run_cleanup.delay()
        return {"status": "queued", "task_id": task.id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
