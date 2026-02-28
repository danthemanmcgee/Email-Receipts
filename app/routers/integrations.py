from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.user import User
from app.services.auth_service import get_current_user

router = APIRouter()


@router.get("/google/status")
def google_integration_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the connection status for both gmail and drive Google accounts."""
    from app.models.integration import GoogleConnection, ConnectionType
    from app.models.receipt import Receipt

    gmail_conn = (
        db.query(GoogleConnection)
        .filter(
            GoogleConnection.connection_type == ConnectionType.gmail,
            GoogleConnection.is_active.is_(True),
        )
        .first()
    )
    drive_conn = (
        db.query(GoogleConnection)
        .filter(
            GoogleConnection.connection_type == ConnectionType.drive,
            GoogleConnection.is_active.is_(True),
        )
        .first()
    )

    last_sync_at = db.query(func.max(Receipt.created_at)).scalar()
    last_upload_at = (
        db.query(func.max(Receipt.updated_at))
        .filter(Receipt.drive_file_id.isnot(None))
        .scalar()
    )

    return {
        "gmail_connected": gmail_conn is not None,
        "gmail_account_email": gmail_conn.google_account_email if gmail_conn else None,
        "drive_connected": drive_conn is not None,
        "drive_account_email": drive_conn.google_account_email if drive_conn else None,
        "last_sync_at": last_sync_at.isoformat() if last_sync_at else None,
        "last_upload_at": last_upload_at.isoformat() if last_upload_at else None,
    }
