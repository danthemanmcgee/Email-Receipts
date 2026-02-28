import re
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.auth_service import get_current_user

router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AllowedSenderCreate(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        normalized = v.strip().lower()
        if not _EMAIL_RE.match(normalized):
            raise ValueError("Invalid email address format")
        return normalized


class AllowedSenderResponse(BaseModel):
    id: int
    email: str

    model_config = {"from_attributes": True}


class AppSettingsResponse(BaseModel):
    drive_root_folder: str
    drive_root_folder_id: str


class AppSettingsUpdate(BaseModel):
    drive_root_folder: Optional[str] = None
    drive_root_folder_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Allowed Senders
# ---------------------------------------------------------------------------

@router.get("/allowed-senders", response_model=List[AllowedSenderResponse])
def list_allowed_senders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all allowed sender email addresses for the current user."""
    from app.models.setting import AllowedSender

    return (
        db.query(AllowedSender)
        .filter(AllowedSender.user_id == current_user.id)
        .order_by(AllowedSender.email)
        .all()
    )


@router.post("/allowed-senders", response_model=AllowedSenderResponse, status_code=201)
def add_allowed_sender(
    payload: AllowedSenderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add an email address to the current user's allowed-senders list."""
    from app.models.setting import AllowedSender

    email = payload.email  # already normalized by the schema validator

    existing = (
        db.query(AllowedSender)
        .filter(AllowedSender.user_id == current_user.id, AllowedSender.email == email)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409, detail="This email address is already in the allowlist"
        )

    sender = AllowedSender(email=email, user_id=current_user.id)
    db.add(sender)
    db.commit()
    db.refresh(sender)
    return sender


@router.delete("/allowed-senders/{sender_id}", status_code=204)
def delete_allowed_sender(
    sender_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove an email address from the current user's allowed-senders list."""
    from app.models.setting import AllowedSender

    sender = db.query(AllowedSender).filter(
        AllowedSender.id == sender_id, AllowedSender.user_id == current_user.id
    ).first()
    if not sender:
        raise HTTPException(status_code=404, detail="Allowed sender not found")
    db.delete(sender)
    db.commit()


# ---------------------------------------------------------------------------
# App Settings (drive root folder, etc.)
# ---------------------------------------------------------------------------

@router.get("/app", response_model=AppSettingsResponse)
def get_app_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return current application settings for the current user."""
    from app.services.settings_service import get_drive_root_folder, get_drive_root_folder_id

    return AppSettingsResponse(
        drive_root_folder=get_drive_root_folder(db, user_id=current_user.id),
        drive_root_folder_id=get_drive_root_folder_id(db, user_id=current_user.id),
    )


@router.put("/app", response_model=AppSettingsResponse)
def update_app_settings(
    payload: AppSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update application settings for the current user."""
    from app.services.settings_service import (
        get_drive_root_folder,
        get_drive_root_folder_id,
        set_drive_root_folder,
        set_drive_root_folder_id,
    )

    if payload.drive_root_folder is not None:
        value = payload.drive_root_folder.strip()
        if not value:
            raise HTTPException(
                status_code=422, detail="drive_root_folder must not be empty"
            )
        set_drive_root_folder(db, value, user_id=current_user.id)

    if payload.drive_root_folder_id is not None:
        set_drive_root_folder_id(db, payload.drive_root_folder_id.strip(), user_id=current_user.id)

    return AppSettingsResponse(
        drive_root_folder=get_drive_root_folder(db, user_id=current_user.id),
        drive_root_folder_id=get_drive_root_folder_id(db, user_id=current_user.id),
    )


class DriveFolderItem(BaseModel):
    id: str
    name: str


class DriveFoldersResponse(BaseModel):
    folders: List[DriveFolderItem]
    parent_id: str


class DriveTokenResponse(BaseModel):
    access_token: str


@router.get("/drive-token", response_model=DriveTokenResponse)
def get_drive_access_token(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a valid Drive access token for use with the Google Drive Picker.

    The token is refreshed if expired before being returned.
    """
    from app.models.integration import GoogleConnection, ConnectionType
    from app.services.gmail_service import _credentials_from_connection, _refresh_and_persist

    conn = (
        db.query(GoogleConnection)
        .filter(
            GoogleConnection.user_id == current_user.id,
            GoogleConnection.connection_type == ConnectionType.drive,
            GoogleConnection.is_active.is_(True),
        )
        .first()
    )

    if conn is None or not conn.access_token:
        raise HTTPException(status_code=503, detail="Google Drive is not connected")

    creds = _credentials_from_connection(conn)
    if creds:
        _refresh_and_persist(creds, conn, db)

    return DriveTokenResponse(access_token=conn.access_token)


@router.get("/drive-folders", response_model=DriveFoldersResponse)
def list_drive_folders(
    parent_id: str = Query(default="root"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List Google Drive folders under the given parent (defaults to Drive root)."""
    from app.services.gmail_service import build_drive_service_from_db

    service = build_drive_service_from_db(db, user_id=current_user.id)
    if service is None:
        raise HTTPException(status_code=503, detail="Google Drive is not connected")

    try:
        safe_parent = parent_id.replace("'", "\\'")
        query = (
            f"mimeType='application/vnd.google-apps.folder' and "
            f"'{safe_parent}' in parents and trashed=false"
        )
        results = (
            service.files()
            .list(q=query, fields="files(id,name)", orderBy="name")
            .execute()
        )
        folders = results.get("files", [])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Drive API error: {exc}")

    return DriveFoldersResponse(folders=folders, parent_id=parent_id)
