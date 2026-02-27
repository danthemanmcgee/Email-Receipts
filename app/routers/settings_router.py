import re
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db

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


class AppSettingsUpdate(BaseModel):
    drive_root_folder: Optional[str] = None


# ---------------------------------------------------------------------------
# Allowed Senders
# ---------------------------------------------------------------------------

@router.get("/allowed-senders", response_model=List[AllowedSenderResponse])
def list_allowed_senders(db: Session = Depends(get_db)):
    """List all allowed sender email addresses."""
    from app.models.setting import AllowedSender

    return db.query(AllowedSender).order_by(AllowedSender.email).all()


@router.post("/allowed-senders", response_model=AllowedSenderResponse, status_code=201)
def add_allowed_sender(payload: AllowedSenderCreate, db: Session = Depends(get_db)):
    """Add an email address to the allowed-senders list."""
    from app.models.setting import AllowedSender

    email = payload.email  # already normalized by the schema validator

    existing = (
        db.query(AllowedSender).filter(AllowedSender.email == email).first()
    )
    if existing:
        raise HTTPException(
            status_code=409, detail="This email address is already in the allowlist"
        )

    sender = AllowedSender(email=email)
    db.add(sender)
    db.commit()
    db.refresh(sender)
    return sender


@router.delete("/allowed-senders/{sender_id}", status_code=204)
def delete_allowed_sender(sender_id: int, db: Session = Depends(get_db)):
    """Remove an email address from the allowed-senders list."""
    from app.models.setting import AllowedSender

    sender = db.query(AllowedSender).filter(AllowedSender.id == sender_id).first()
    if not sender:
        raise HTTPException(status_code=404, detail="Allowed sender not found")
    db.delete(sender)
    db.commit()


# ---------------------------------------------------------------------------
# App Settings (drive root folder, etc.)
# ---------------------------------------------------------------------------

@router.get("/app", response_model=AppSettingsResponse)
def get_app_settings(db: Session = Depends(get_db)):
    """Return current application settings."""
    from app.services.settings_service import get_drive_root_folder

    return AppSettingsResponse(drive_root_folder=get_drive_root_folder(db))


@router.put("/app", response_model=AppSettingsResponse)
def update_app_settings(payload: AppSettingsUpdate, db: Session = Depends(get_db)):
    """Update application settings."""
    from app.services.settings_service import get_drive_root_folder, set_drive_root_folder

    if payload.drive_root_folder is not None:
        value = payload.drive_root_folder.strip()
        if not value:
            raise HTTPException(
                status_code=422, detail="drive_root_folder must not be empty"
            )
        set_drive_root_folder(db, value)

    return AppSettingsResponse(drive_root_folder=get_drive_root_folder(db))
