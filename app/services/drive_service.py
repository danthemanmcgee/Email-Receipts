import logging
import re
from datetime import date
from typing import Optional
from app.models.card import PhysicalCard

logger = logging.getLogger(__name__)


def build_drive_path(
    card: Optional[PhysicalCard],
    purchase_date: Optional[date],
    merchant: Optional[str],
    amount: Optional[float],
    currency: Optional[str],
    gmail_message_id: str,
    root_folder: str = "Receipts",
) -> tuple[str, str]:
    """Returns (folder_path, filename)"""
    if card:
        card_folder = sanitize_path_component(card.display_name)
    else:
        card_folder = "Unmapped_Card"

    if purchase_date:
        year = purchase_date.strftime("%Y")
        month = purchase_date.strftime("%Y-%m")
    else:
        from datetime import date as date_cls

        today = date_cls.today()
        year = today.strftime("%Y")
        month = today.strftime("%Y-%m")

    folder_path = f"{root_folder}/{card_folder}/{year}/{month}"

    date_str = purchase_date.strftime("%Y-%m-%d") if purchase_date else "0000-00-00"
    merchant_str = sanitize_path_component(merchant or "Unknown")
    amount_str = f"{amount:.2f}" if amount is not None else "0.00"
    currency_str = (currency or "USD").upper()

    filename = f"{date_str}_{merchant_str}_{amount_str}_{currency_str}_{gmail_message_id}.pdf"

    return folder_path, filename


def sanitize_path_component(s: str) -> str:
    """Remove/replace characters not safe for file/folder names."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:100]


def ensure_drive_folder(service, folder_path: str) -> str:
    """Create nested Drive folders as needed and return the leaf folder ID."""
    parts = [p for p in folder_path.split("/") if p]
    parent_id = "root"

    for part in parts:
        safe_part = part.replace("'", "\\'")
        query = (
            f"name='{safe_part}' and "
            f"mimeType='application/vnd.google-apps.folder' and "
            f"'{parent_id}' in parents and trashed=false"
        )
        results = service.files().list(q=query, fields="files(id)").execute()
        files = results.get("files", [])
        if files:
            parent_id = files[0]["id"]
        else:
            meta = {
                "name": part,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            folder = service.files().create(body=meta, fields="id").execute()
            parent_id = folder["id"]

    return parent_id


def upload_pdf_to_drive(
    service,
    pdf_bytes: bytes,
    folder_path: str,
    filename: str,
) -> Optional[str]:
    """Upload PDF bytes to a Drive folder path. Returns Drive file_id, or None on failure.

    Idempotent within the target folder: if a file with the same name already exists
    in the resolved leaf folder, its existing ID is returned without re-uploading.
    """
    import io

    try:
        from googleapiclient.http import MediaIoBaseUpload

        parent_id = ensure_drive_folder(service, folder_path)

        safe_name = filename.replace("'", "\\'")
        query = f"name='{safe_name}' and '{parent_id}' in parents and trashed=false"
        existing = service.files().list(q=query, fields="files(id)").execute().get("files", [])
        if existing:
            logger.info("Drive file already exists, skipping upload: %s", filename)
            return existing[0]["id"]

        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf")
        meta = {"name": filename, "parents": [parent_id]}
        file_obj = service.files().create(body=meta, media_body=media, fields="id").execute()
        return file_obj["id"]
    except Exception as exc:
        logger.error("Drive upload failed for %s: %s", filename, exc)
        return None
