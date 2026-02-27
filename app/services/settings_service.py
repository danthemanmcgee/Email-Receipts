import re
import logging

logger = logging.getLogger(__name__)

DRIVE_ROOT_FOLDER_KEY = "drive_root_folder"


def _extract_email(from_header: str) -> str:
    """Extract the bare email address from a 'Name <email>' or bare 'email' header."""
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1).strip().lower()
    return from_header.strip().lower()


def get_allowed_senders(db) -> list:
    """Return all allowed sender emails (lowercase) from the DB."""
    from app.models.setting import AllowedSender

    return [row.email.lower() for row in db.query(AllowedSender).all()]


def is_sender_allowed(db, from_header: str) -> bool:
    """Return True if the sender is in the allowlist, or if the allowlist is empty (allow all).

    The ``from_header`` value may be a full RFC 5322 address like ``Name <email@example.com>``
    or a bare email address.
    """
    allowed = get_allowed_senders(db)
    if not allowed:
        return True
    email = _extract_email(from_header)
    return email in allowed


def get_drive_root_folder(db) -> str:
    """Return the configured Drive root folder from the DB, falling back to the env setting."""
    from app.models.setting import AppSetting
    from app.config import get_settings

    setting = (
        db.query(AppSetting).filter(AppSetting.key == DRIVE_ROOT_FOLDER_KEY).first()
    )
    if setting and setting.value:
        return setting.value
    return get_settings().DRIVE_ROOT_FOLDER


def set_drive_root_folder(db, value: str) -> None:
    """Persist the Drive root folder setting to the DB."""
    from app.models.setting import AppSetting

    setting = (
        db.query(AppSetting).filter(AppSetting.key == DRIVE_ROOT_FOLDER_KEY).first()
    )
    if setting:
        setting.value = value
    else:
        setting = AppSetting(key=DRIVE_ROOT_FOLDER_KEY, value=value)
        db.add(setting)
    db.commit()
