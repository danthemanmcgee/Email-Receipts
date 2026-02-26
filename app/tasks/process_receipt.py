import hashlib
import logging
from typing import Optional

from app.tasks.celery_app import celery_app
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(name="app.tasks.process_receipt.sync_gmail", bind=True, max_retries=3)
def sync_gmail(self):
    """Poll Gmail for new receipts and queue individual processing tasks."""
    try:
        from app.services.gmail_service import build_gmail_service, list_new_messages
        from app.database import SessionLocal
        from app.models.receipt import Receipt

        gmail = build_gmail_service(
            settings.GMAIL_CREDENTIALS_FILE, settings.GMAIL_TOKEN_FILE
        )
        if not gmail:
            logger.warning("Gmail service unavailable, skipping sync")
            return {"status": "skipped", "reason": "no_credentials"}

        messages = list_new_messages(gmail)
        logger.info("Found %d new messages", len(messages))

        queued = 0
        with SessionLocal() as db:
            for msg in messages:
                mid = msg["id"]
                exists = db.query(Receipt).filter(Receipt.gmail_message_id == mid).first()
                if not exists:
                    process_receipt_task.delay(mid)
                    queued += 1

        return {"status": "ok", "queued": queued}
    except Exception as exc:
        logger.error("sync_gmail failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="app.tasks.process_receipt.process_receipt_task", bind=True, max_retries=3)
def process_receipt_task(self, gmail_message_id: str):
    """Process a single Gmail message as a receipt."""
    from app.database import SessionLocal
    from app.models.receipt import Receipt, ReceiptStatus, AttachmentLog
    from app.services.gmail_service import (
        build_gmail_service,
        get_message_detail,
        get_attachment_bytes,
        extract_attachments_from_message,
        extract_body_text,
        apply_label,
        LABEL_MAP,
    )
    from app.services.attachment_service import select_best_pdf
    from app.services.extraction_service import extract_from_pdf_bytes, extract_from_text
    from app.services.card_service import resolve_card

    with SessionLocal() as db:
        # Idempotency check
        receipt = db.query(Receipt).filter(
            Receipt.gmail_message_id == gmail_message_id
        ).first()
        if receipt and receipt.status not in (ReceiptStatus.new, ReceiptStatus.failed):
            logger.info("Message %s already processed, skipping", gmail_message_id)
            return {"status": "skipped"}

        if not receipt:
            receipt = Receipt(
                gmail_message_id=gmail_message_id,
                status=ReceiptStatus.processing,
            )
            db.add(receipt)
            db.commit()
            db.refresh(receipt)
        else:
            receipt.status = ReceiptStatus.processing
            db.commit()

        try:
            gmail = build_gmail_service(
                settings.GMAIL_CREDENTIALS_FILE, settings.GMAIL_TOKEN_FILE
            )
            message = get_message_detail(gmail, gmail_message_id) if gmail else None

            if not message:
                receipt.status = ReceiptStatus.failed
                receipt.extraction_notes = "Could not fetch Gmail message"
                db.commit()
                return {"status": "failed", "reason": "no_message"}

            # Populate basic fields
            headers = {
                h["name"]: h["value"]
                for h in message.get("payload", {}).get("headers", [])
            }
            receipt.subject = headers.get("Subject", "")[:500]
            receipt.sender = headers.get("From", "")[:255]
            from datetime import datetime
            date_str = headers.get("Date")
            if date_str:
                try:
                    from email.utils import parsedate_to_datetime
                    receipt.received_at = parsedate_to_datetime(date_str)
                except Exception:
                    pass

            # Handle attachments
            raw_attachments = extract_attachments_from_message(message)
            max_bytes = settings.MAX_ATTACHMENT_SIZE_MB * 1024 * 1024
            filtered = [
                a for a in raw_attachments if a.get("size", 0) <= max_bytes
            ]
            attachment_dicts = [{"filename": a["filename"]} for a in filtered]
            selected, all_scores = select_best_pdf(attachment_dicts)

            # Log attachment decisions
            for score_obj in all_scores:
                log = AttachmentLog(
                    receipt_id=receipt.id,
                    filename=score_obj.filename,
                    score=score_obj.score,
                    decision=score_obj.decision,
                    reason=score_obj.reason[:500],
                )
                db.add(log)

            extraction_result = None
            if selected:
                # Find the matching attachment_id
                att_info = next(
                    (a for a in filtered if a["filename"] == selected.filename), None
                )
                if att_info:
                    pdf_bytes = get_attachment_bytes(
                        gmail, gmail_message_id, att_info["attachment_id"]
                    )
                    if pdf_bytes:
                        receipt.content_hash = hashlib.sha256(pdf_bytes).hexdigest()
                        extraction_result = extract_from_pdf_bytes(pdf_bytes)

            if not extraction_result:
                body_text = extract_body_text(message)
                extraction_result = extract_from_text(body_text)

            # Apply extraction results
            receipt.merchant = extraction_result.merchant
            receipt.purchase_date = extraction_result.purchase_date
            receipt.amount = extraction_result.amount
            receipt.currency = extraction_result.currency
            receipt.card_last4_seen = extraction_result.card_last4
            receipt.card_network_or_issuer = extraction_result.card_network_or_issuer
            receipt.source_type = extraction_result.source_type
            receipt.confidence = extraction_result.confidence
            receipt.extraction_notes = "; ".join(extraction_result.notes)

            # Card resolution
            card, _ = resolve_card(db, receipt.card_last4_seen)
            if card:
                receipt.physical_card_id = card.id

            # Determine status
            if receipt.confidence >= settings.CONFIDENCE_THRESHOLD:
                receipt.status = ReceiptStatus.processed
                if gmail:
                    apply_label(gmail, gmail_message_id, LABEL_MAP["processed"])
            else:
                receipt.status = ReceiptStatus.needs_review
                if gmail:
                    apply_label(gmail, gmail_message_id, LABEL_MAP["needs_review"])

            db.commit()
            return {"status": receipt.status.value, "receipt_id": receipt.id}

        except Exception as exc:
            logger.error("process_receipt_task failed for %s: %s", gmail_message_id, exc)
            receipt.status = ReceiptStatus.failed
            receipt.extraction_notes = str(exc)[:500]
            db.commit()
            raise self.retry(exc=exc, countdown=120)
