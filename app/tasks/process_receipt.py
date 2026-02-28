import hashlib
import logging
from typing import Optional

from app.tasks.celery_app import celery_app
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(name="app.tasks.process_receipt.sync_gmail", bind=True, max_retries=3)
def sync_gmail(self, job_run_id: int = None, user_id: int = None):
    """Poll Gmail for new receipts and queue individual processing tasks."""
    try:
        from app.services.gmail_service import build_gmail_service_from_db, list_new_messages
        from app.database import SessionLocal
        from app.models.receipt import Receipt, GmailReceiptLink
        from app.models.job import JobRun, JobStatus
        from datetime import datetime as dt

        with SessionLocal() as db:
            # Update job run to running
            if job_run_id:
                job_run = db.query(JobRun).filter(JobRun.id == job_run_id).first()
                if job_run:
                    job_run.status = JobStatus.running
                    db.commit()

            gmail = build_gmail_service_from_db(db, user_id=user_id)
            if not gmail:
                logger.warning("Gmail service unavailable, skipping sync")
                if job_run_id:
                    job_run = db.query(JobRun).filter(JobRun.id == job_run_id).first()
                    if job_run:
                        job_run.status = JobStatus.failed
                        job_run.error_message = "Gmail service unavailable — no credentials"
                        job_run.completed_at = dt.utcnow()
                        db.commit()
                return {"status": "skipped", "reason": "no_credentials"}

            messages = list_new_messages(gmail)
            logger.info("Found %d new messages", len(messages))

            queued = 0
            for msg in messages:
                mid = msg["id"]
                exists = db.query(Receipt).filter(Receipt.gmail_message_id == mid).first()
                if not exists:
                    # Also skip messages already tracked in gmail_receipt_links
                    # (e.g. a duplicate that was processed and linked in a prior run)
                    link_exists = (
                        db.query(GmailReceiptLink)
                        .filter(GmailReceiptLink.gmail_message_id == mid)
                        .first()
                    )
                    if not link_exists:
                        process_receipt_task.delay(mid, user_id=user_id)
                        queued += 1

            if job_run_id:
                job_run = db.query(JobRun).filter(JobRun.id == job_run_id).first()
                if job_run:
                    job_run.status = JobStatus.completed
                    job_run.details = f"Found {len(messages)} messages, queued {queued} for processing"
                    job_run.completed_at = dt.utcnow()
                    db.commit()

        return {"status": "ok", "queued": queued}
    except Exception as exc:
        logger.error("sync_gmail failed: %s", exc)
        try:
            from app.database import SessionLocal
            from app.models.job import JobRun, JobStatus
            from datetime import datetime as dt
            if job_run_id:
                with SessionLocal() as db:
                    job_run = db.query(JobRun).filter(JobRun.id == job_run_id).first()
                    if job_run:
                        job_run.status = JobStatus.failed
                        job_run.error_message = str(exc)
                        job_run.completed_at = dt.utcnow()
                        db.commit()
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="app.tasks.process_receipt.process_receipt_task", bind=True, max_retries=3)
def process_receipt_task(self, gmail_message_id: str, user_id: int = None):
    """Process a single Gmail message as a receipt."""
    from app.database import SessionLocal
    from app.models.receipt import Receipt, ReceiptStatus, AttachmentLog, GmailReceiptLink
    from app.services.gmail_service import (
        build_gmail_service,
        build_gmail_service_from_db,
        get_message_detail,
        get_attachment_bytes,
        extract_attachments_from_message,
        extract_body_text,
        apply_label,
        archive_message,
        LABEL_MAP,
    )
    from app.services.attachment_service import select_best_pdf
    from app.services.extraction_service import extract_from_pdf_bytes, extract_from_text
    from app.services.card_service import resolve_card

    with SessionLocal() as db:
        # Idempotency check — receipt already processed
        receipt = db.query(Receipt).filter(
            Receipt.gmail_message_id == gmail_message_id
        ).first()
        if receipt and receipt.status not in (ReceiptStatus.new, ReceiptStatus.failed):
            logger.info("Message %s already processed, skipping", gmail_message_id)
            return {"status": "skipped"}

        # Idempotency check — message already linked to a canonical receipt
        existing_link = (
            db.query(GmailReceiptLink)
            .filter(GmailReceiptLink.gmail_message_id == gmail_message_id)
            .first()
        )
        if existing_link:
            logger.info(
                "Message %s already linked to receipt %d, skipping",
                gmail_message_id,
                existing_link.receipt_id,
            )
            return {"status": "skipped"}

        if not receipt:
            receipt = Receipt(
                gmail_message_id=gmail_message_id,
                status=ReceiptStatus.processing,
                user_id=user_id,
            )
            db.add(receipt)
            db.commit()
            db.refresh(receipt)
        else:
            receipt.status = ReceiptStatus.processing
            db.commit()

        try:
            gmail = build_gmail_service_from_db(db, user_id=user_id)
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

            # Sender allowlist check: if the list is non-empty and the sender
            # is not on it, archive the message and skip processing.
            from app.services.settings_service import is_sender_allowed
            if not is_sender_allowed(db, receipt.sender or "", user_id=user_id):
                logger.info(
                    "Message %s from '%s' is not in the allowed-senders list; archiving.",
                    gmail_message_id,
                    receipt.sender,
                )
                if gmail:
                    archive_message(gmail, gmail_message_id)
                db.delete(receipt)
                db.commit()
                return {"status": "archived", "reason": "sender_not_allowed"}

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
            pdf_bytes_cache = None
            if selected:
                # Find the matching attachment_id
                att_info = next(
                    (a for a in filtered if a["filename"] == selected.filename), None
                )
                if att_info:
                    pdf_bytes_cache = get_attachment_bytes(
                        gmail, gmail_message_id, att_info["attachment_id"]
                    )
                    if pdf_bytes_cache:
                        content_hash = hashlib.sha256(pdf_bytes_cache).hexdigest()
                        receipt.content_hash = content_hash

                        # Deduplication: check if an identical document already
                        # exists for this user (different Receipt, same hash).
                        canonical = (
                            db.query(Receipt)
                            .filter(
                                Receipt.content_hash == content_hash,
                                Receipt.user_id == user_id,
                                Receipt.id != receipt.id,
                            )
                            .first()
                        )
                        if canonical:
                            logger.info(
                                "Duplicate content_hash %s for message %s — "
                                "reusing drive_file_id %s from receipt %d",
                                content_hash,
                                gmail_message_id,
                                canonical.drive_file_id,
                                canonical.id,
                            )
                            # Remove the placeholder receipt and record the link
                            # to the canonical document instead.
                            db.delete(receipt)
                            link = GmailReceiptLink(
                                receipt_id=canonical.id,
                                gmail_message_id=gmail_message_id,
                                user_id=user_id,
                            )
                            db.add(link)
                            db.commit()
                            if gmail:
                                apply_label(gmail, gmail_message_id, LABEL_MAP["processed"])
                            return {
                                "status": "duplicate",
                                "receipt_id": canonical.id,
                                "drive_file_id": canonical.drive_file_id,
                            }

                        extraction_result = extract_from_pdf_bytes(pdf_bytes_cache)

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
            card, _ = resolve_card(db, receipt.card_last4_seen, user_id=user_id)
            if card:
                receipt.physical_card_id = card.id

            # Drive upload
            from app.services.gmail_service import build_drive_service_from_db
            from app.services.drive_service import build_drive_path, upload_pdf_to_drive

            drive = build_drive_service_from_db(db, user_id=user_id)
            if drive is None:
                # Drive not connected: flag for review so user can upload manually
                notes = receipt.extraction_notes or ""
                receipt.extraction_notes = (notes + "; drive_not_connected").lstrip("; ")
                receipt.status = ReceiptStatus.needs_review
                if gmail:
                    apply_label(gmail, gmail_message_id, LABEL_MAP["needs_review"])
                db.commit()
                return {"status": receipt.status.value, "receipt_id": receipt.id, "reason": "drive_not_connected"}

            if receipt.content_hash and selected:
                from app.services.settings_service import get_drive_root_folder, get_drive_root_folder_id
                folder_path, filename = build_drive_path(
                    card=card,
                    purchase_date=receipt.purchase_date,
                    merchant=receipt.merchant,
                    amount=receipt.amount,
                    currency=receipt.currency,
                    gmail_message_id=gmail_message_id,
                    root_folder=get_drive_root_folder(db, user_id=user_id),
                )
                if pdf_bytes_cache:
                    root_folder_id = get_drive_root_folder_id(db, user_id=user_id) or None
                    file_id = upload_pdf_to_drive(drive, pdf_bytes_cache, folder_path, filename, root_folder_id=root_folder_id)
                    if file_id:
                        receipt.drive_file_id = file_id
                        receipt.drive_path = f"{folder_path}/{filename}"

            # Determine final status
            if receipt.confidence >= settings.CONFIDENCE_THRESHOLD:
                receipt.status = ReceiptStatus.processed
                receipt.processed_at = datetime.utcnow()
                if gmail:
                    apply_label(gmail, gmail_message_id, LABEL_MAP["processed"])
            else:
                receipt.status = ReceiptStatus.needs_review
                if gmail:
                    apply_label(gmail, gmail_message_id, LABEL_MAP["needs_review"])

            # Record the canonical gmail → receipt link
            link = GmailReceiptLink(
                receipt_id=receipt.id,
                gmail_message_id=gmail_message_id,
                user_id=user_id,
            )
            db.add(link)

            db.commit()
            return {"status": receipt.status.value, "receipt_id": receipt.id}

        except Exception as exc:
            logger.error("process_receipt_task failed for %s: %s", gmail_message_id, exc)
            receipt.status = ReceiptStatus.failed
            receipt.extraction_notes = str(exc)[:500]
            db.commit()
            raise self.retry(exc=exc, countdown=120)
