"""Direct receipt upload router.

Accepts PDF or image files, converts images to PDF, deduplicates by
content hash, uploads to Google Drive, and creates a Receipt record.
Drive must be connected before any upload is accepted.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.receipt import Receipt, ReceiptStatus
from app.models.user import User
from app.schemas.receipt import ReceiptResponse
from app.services.auth_service import get_current_user
from app.services.upload_service import (
    ALLOWED_CONTENT_TYPES,
    IMAGE_CONTENT_TYPES,
    compute_content_hash,
    image_bytes_to_pdf,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=ReceiptResponse)
async def upload_receipt(
    file: UploadFile = File(...),
    card_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a receipt file (PDF or image).

    - Requires Google Drive to be connected.
    - Images are converted to PDF before processing.
    - Duplicates (matched by SHA-256 content hash) reuse the existing
      Drive file and receipt record.
    - Max file size is controlled by ``MAX_ATTACHMENT_SIZE_MB`` in config.
    """
    from app.services.gmail_service import build_drive_service_from_db
    from app.services.drive_service import build_drive_path, upload_pdf_to_drive
    from app.services.extraction_service import extract_from_pdf_bytes
    from app.services.card_service import resolve_card
    from app.services.settings_service import (
        get_drive_root_folder,
        get_drive_root_folder_id,
    )

    settings = get_settings()

    # 1. Drive must be connected
    drive = build_drive_service_from_db(db, user_id=current_user.id)
    if drive is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Google Drive is not connected. "
                "Please connect Drive in Settings before uploading receipts."
            ),
        )

    # 2. Validate content type
    content_type = (file.content_type or "").lower().split(";")[0].strip()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported file type: {content_type!r}. "
                "Allowed types: PDF, JPEG, PNG, GIF, WebP."
            ),
        )

    # 3. Read file bytes and enforce size limit
    max_bytes = settings.MAX_ATTACHMENT_SIZE_MB * 1024 * 1024
    file_bytes = await file.read()
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large ({len(file_bytes) // (1024 * 1024)} MB). "
                f"Maximum allowed size is {settings.MAX_ATTACHMENT_SIZE_MB} MB."
            ),
        )

    # 4. Convert image → PDF when necessary
    if content_type in IMAGE_CONTENT_TYPES:
        try:
            pdf_bytes = image_bytes_to_pdf(file_bytes)
        except Exception as exc:
            logger.error("Image-to-PDF conversion failed: %s", exc)
            raise HTTPException(
                status_code=422,
                detail=f"Image conversion to PDF failed: {exc}",
            )
    else:
        pdf_bytes = file_bytes

    # 5. Content hash + deduplication
    content_hash = compute_content_hash(pdf_bytes)
    existing = (
        db.query(Receipt)
        .filter(
            Receipt.content_hash == content_hash,
            Receipt.user_id == current_user.id,
        )
        .first()
    )
    if existing:
        logger.info(
            "Duplicate upload for user %d — reusing receipt %d",
            current_user.id,
            existing.id,
        )
        return existing

    # 6. Extract receipt metadata from PDF
    extraction_result = extract_from_pdf_bytes(pdf_bytes)

    # 7. Resolve card (explicit selection takes precedence over extraction)
    card = None
    if card_id is not None:
        from app.models.card import PhysicalCard

        card = (
            db.query(PhysicalCard)
            .filter(
                PhysicalCard.id == card_id,
                PhysicalCard.user_id == current_user.id,
            )
            .first()
        )
    if card is None and extraction_result.card_last4:
        card, _ = resolve_card(db, extraction_result.card_last4, user_id=current_user.id)

    # 8. Upload to Google Drive
    synthetic_id = f"upload_{uuid.uuid4().hex}"
    folder_path, filename = build_drive_path(
        card=card,
        purchase_date=extraction_result.purchase_date,
        merchant=extraction_result.merchant,
        amount=extraction_result.amount,
        currency=extraction_result.currency,
        gmail_message_id=synthetic_id,
        root_folder=get_drive_root_folder(db, user_id=current_user.id),
    )
    root_folder_id = get_drive_root_folder_id(db, user_id=current_user.id) or None
    drive_file_id = upload_pdf_to_drive(
        drive, pdf_bytes, folder_path, filename, root_folder_id=root_folder_id
    )

    # 9. Determine status and create Receipt record
    now = datetime.now(timezone.utc)
    if extraction_result.confidence >= settings.CONFIDENCE_THRESHOLD and drive_file_id:
        status = ReceiptStatus.processed
        processed_at = now
    else:
        status = ReceiptStatus.needs_review
        processed_at = None

    receipt = Receipt(
        user_id=current_user.id,
        gmail_message_id=synthetic_id,
        status=status,
        merchant=extraction_result.merchant,
        purchase_date=extraction_result.purchase_date,
        amount=extraction_result.amount,
        currency=extraction_result.currency,
        card_last4_seen=extraction_result.card_last4,
        card_network_or_issuer=extraction_result.card_network_or_issuer,
        source_type="direct_upload",
        confidence=extraction_result.confidence,
        extraction_notes="; ".join(extraction_result.notes),
        physical_card_id=card.id if card else None,
        content_hash=content_hash,
        drive_file_id=drive_file_id,
        drive_path=f"{folder_path}/{filename}" if drive_file_id else None,
        processed_at=processed_at,
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt
