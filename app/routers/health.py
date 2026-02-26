from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check():
    """Check service health including DB and Redis connectivity."""
    db_ok = False
    redis_ok = False

    try:
        from app.database import engine
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    try:
        from app.config import get_settings
        import redis as redis_lib
        settings = get_settings()
        r = redis_lib.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        r.ping()
        redis_ok = True
    except Exception:
        pass

    return {"status": "ok", "db": db_ok, "redis": redis_ok}
