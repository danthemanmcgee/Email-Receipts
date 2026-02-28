import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

DRIVE_ROOT_FOLDER_KEY = "drive_root_folder"
DRIVE_ROOT_FOLDER_ID_KEY = "drive_root_folder_id"


def _extract_email(from_header: str) -> str:
    """Extract the bare email address from a 'Name <email>' or bare 'email' header."""
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1).strip().lower()
    return from_header.strip().lower()


def get_allowed_senders(db, user_id: Optional[int] = None) -> list:
    """Return allowed sender emails (lowercase) for the given user."""
    from app.models.setting import AllowedSender

    q = db.query(AllowedSender)
    if user_id is not None:
        q = q.filter(AllowedSender.user_id == user_id)
    return [row.email.lower() for row in q.all()]


def is_sender_allowed(db, from_header: str, user_id: Optional[int] = None) -> bool:
    """Return True if the sender is in the allowlist, or if the allowlist is empty (allow all).

    The ``from_header`` value may be a full RFC 5322 address like ``Name <email@example.com>``
    or a bare email address.
    """
    allowed = get_allowed_senders(db, user_id=user_id)
    if not allowed:
        return True
    email = _extract_email(from_header)
    return email in allowed


def get_drive_root_folder(db, user_id: Optional[int] = None) -> str:
    """Return the configured Drive root folder for the given user, falling back to the env setting."""
    from app.models.setting import AppSetting
    from app.config import get_settings

    q = db.query(AppSetting).filter(AppSetting.key == DRIVE_ROOT_FOLDER_KEY)
    if user_id is not None:
        q = q.filter(AppSetting.user_id == user_id)
    setting = q.first()
    if setting and setting.value:
        return setting.value
    return get_settings().DRIVE_ROOT_FOLDER


def set_drive_root_folder(db, value: str, user_id: Optional[int] = None) -> None:
    """Persist the Drive root folder setting for the given user."""
    from app.models.setting import AppSetting

    q = db.query(AppSetting).filter(AppSetting.key == DRIVE_ROOT_FOLDER_KEY)
    if user_id is not None:
        q = q.filter(AppSetting.user_id == user_id)
    setting = q.first()
    if setting:
        setting.value = value
    else:
        setting = AppSetting(key=DRIVE_ROOT_FOLDER_KEY, value=value, user_id=user_id)
        db.add(setting)
    db.commit()


def get_drive_root_folder_id(db, user_id: Optional[int] = None) -> str:
    """Return the stored Drive root folder ID for the given user, or empty string if not set."""
    from app.models.setting import AppSetting

    q = db.query(AppSetting).filter(AppSetting.key == DRIVE_ROOT_FOLDER_ID_KEY)
    if user_id is not None:
        q = q.filter(AppSetting.user_id == user_id)
    setting = q.first()
    if setting and setting.value:
        return setting.value
    return ""


def set_drive_root_folder_id(db, folder_id: str, user_id: Optional[int] = None) -> None:
    """Persist the Drive root folder ID for the given user."""
    from app.models.setting import AppSetting

    q = db.query(AppSetting).filter(AppSetting.key == DRIVE_ROOT_FOLDER_ID_KEY)
    if user_id is not None:
        q = q.filter(AppSetting.user_id == user_id)
    setting = q.first()
    if setting:
        setting.value = folder_id
    else:
        setting = AppSetting(key=DRIVE_ROOT_FOLDER_ID_KEY, value=folder_id, user_id=user_id)
        db.add(setting)
    db.commit()
