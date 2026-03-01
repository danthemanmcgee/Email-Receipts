"""Tests for the UX improvements:
1. Receipt preview section: fallback shown when drive_file_id is missing.
2. Attachment decisions: only the latest scoring run is shown by default.
3. Job status: process_receipt_task updates job_run to completed/failed.
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_receipt(drive_file_id=None, drive_path=None, attachment_logs=None):
    from app.models.receipt import Receipt, ReceiptStatus

    r = Receipt.__new__(Receipt)
    r.id = 1
    r.gmail_message_id = "msg-test"
    r.status = ReceiptStatus.processed
    r.subject = "Test"
    r.sender = "shop@example.com"
    r.received_at = None
    r.merchant = "ACME"
    r.purchase_date = None
    r.amount = 9.99
    r.currency = "USD"
    r.card_last4_seen = "1234"
    r.card_network_or_issuer = None
    r.source_type = None
    r.confidence = 0.95
    r.extraction_notes = None
    r.physical_card_id = None
    r.physical_card = None
    r.attachment_logs = attachment_logs or []
    r.drive_file_id = drive_file_id
    r.drive_path = drive_path
    r.content_hash = None
    r.processed_at = None
    r.created_at = datetime(2025, 1, 1)
    r.updated_at = datetime(2025, 1, 1)
    return r


def _make_attachment_log(filename="receipt.pdf", score=100, decision="selected",
                         reason="Exact match", created_at=None):
    from app.models.receipt import AttachmentLog

    log = AttachmentLog.__new__(AttachmentLog)
    log.id = 1
    log.receipt_id = 1
    log.filename = filename
    log.score = score
    log.decision = decision
    log.reason = reason
    log.created_at = created_at or datetime(2025, 1, 1, 12, 0, 0)
    return log


def _setup_db(receipt):
    mock_db = MagicMock()
    mock_q = MagicMock()
    mock_q.options.return_value = mock_q
    mock_q.filter.return_value = mock_q
    mock_q.first.return_value = receipt
    # second query call is for cards list
    mock_q.all.return_value = []
    mock_db.query.return_value = mock_q
    mock_db.__enter__ = lambda s: mock_db
    mock_db.__exit__ = MagicMock(return_value=False)
    return mock_db


# ---------------------------------------------------------------------------
# 1. _latest_attachment_logs helper
# ---------------------------------------------------------------------------

class TestLatestAttachmentLogs:
    """Unit tests for the _latest_attachment_logs helper in app.main."""

    def test_empty_returns_empty(self):
        from app.main import _latest_attachment_logs
        assert _latest_attachment_logs([]) == []

    def test_single_log_returned(self):
        from app.main import _latest_attachment_logs
        log = _make_attachment_log()
        result = _latest_attachment_logs([log])
        assert result == [log]

    def test_all_recent_logs_returned(self):
        """Logs within 60 s of the max are all included."""
        from app.main import _latest_attachment_logs
        base = datetime(2025, 1, 1, 12, 0, 0)
        logs = [
            _make_attachment_log(filename="a.pdf", created_at=base),
            _make_attachment_log(filename="b.pdf", created_at=base + timedelta(seconds=1)),
        ]
        result = _latest_attachment_logs(logs)
        assert len(result) == 2

    def test_only_latest_run_returned(self):
        """Logs from an older run (>60 s before max) are excluded."""
        from app.main import _latest_attachment_logs
        old_time = datetime(2025, 1, 1, 10, 0, 0)
        new_time = datetime(2025, 1, 1, 12, 0, 0)
        old_log = _make_attachment_log(filename="old.pdf", created_at=old_time)
        new_log = _make_attachment_log(filename="new.pdf", created_at=new_time)
        result = _latest_attachment_logs([old_log, new_log])
        assert new_log in result
        assert old_log not in result

    def test_multiple_logs_same_run(self):
        """All logs from the same run are returned together."""
        from app.main import _latest_attachment_logs
        base = datetime(2025, 1, 1, 12, 0, 0)
        logs = [
            _make_attachment_log(filename="receipt.pdf", created_at=base),
            _make_attachment_log(filename="invoice.pdf", decision="ignored", created_at=base + timedelta(seconds=2)),
            _make_attachment_log(filename="statement.pdf", decision="ignored", created_at=base + timedelta(seconds=3)),
        ]
        result = _latest_attachment_logs(logs)
        assert len(result) == 3

    def test_old_run_excluded_new_run_included(self):
        """Only the newest run's logs are returned when two runs exist."""
        from app.main import _latest_attachment_logs
        run1_time = datetime(2025, 1, 1, 10, 0, 0)
        run2_time = datetime(2025, 1, 2, 10, 0, 0)  # next day
        logs = [
            _make_attachment_log(filename="r1a.pdf", created_at=run1_time),
            _make_attachment_log(filename="r1b.pdf", created_at=run1_time + timedelta(seconds=1)),
            _make_attachment_log(filename="r2a.pdf", created_at=run2_time),
            _make_attachment_log(filename="r2b.pdf", created_at=run2_time + timedelta(seconds=1)),
        ]
        result = _latest_attachment_logs(logs)
        filenames = [l.filename for l in result]
        assert "r2a.pdf" in filenames
        assert "r2b.pdf" in filenames
        assert "r1a.pdf" not in filenames
        assert "r1b.pdf" not in filenames


# ---------------------------------------------------------------------------
# 2. Receipt detail page HTML: preview fallback
# ---------------------------------------------------------------------------

class TestReceiptDetailPreviewFallback:
    """The receipt detail page shows appropriate content based on drive_file_id."""

    def test_open_in_drive_button_shown_when_drive_file_id_set(self):
        """'Open in Drive' link is rendered when drive_file_id is present."""
        from fastapi.testclient import TestClient
        from app.main import app

        receipt = _make_receipt(drive_file_id="drive-xyz")
        mock_db = _setup_db(receipt)

        with patch("app.database.SessionLocal", return_value=mock_db):
            client = TestClient(app)
            resp = client.get("/ui/receipts/1")

        assert resp.status_code == 200
        assert "Open in Drive" in resp.text
        assert "drive-xyz" in resp.text

    def test_fallback_section_shown_when_no_drive_file_id(self):
        """A fallback section is shown when drive_file_id is missing."""
        from fastapi.testclient import TestClient
        from app.main import app

        receipt = _make_receipt(drive_file_id=None)
        mock_db = _setup_db(receipt)

        with patch("app.database.SessionLocal", return_value=mock_db):
            client = TestClient(app)
            resp = client.get("/ui/receipts/1")

        assert resp.status_code == 200
        # Should show fallback section (PDF card but without live iframe)
        assert "Receipt PDF" in resp.text
        assert 'id="pdf-loading"' not in resp.text

    def test_fallback_shows_drive_path_when_available(self):
        """Fallback section shows drive_path when it is set but drive_file_id is not."""
        from fastapi.testclient import TestClient
        from app.main import app

        receipt = _make_receipt(drive_file_id=None, drive_path="Receipts/2025/receipt.pdf")
        mock_db = _setup_db(receipt)

        with patch("app.database.SessionLocal", return_value=mock_db):
            client = TestClient(app)
            resp = client.get("/ui/receipts/1")

        assert resp.status_code == 200
        assert "Receipts/2025/receipt.pdf" in resp.text

    def test_fallback_shows_reprocess_cta(self):
        """Fallback section contains a Reprocess button."""
        from fastapi.testclient import TestClient
        from app.main import app

        receipt = _make_receipt(drive_file_id=None)
        mock_db = _setup_db(receipt)

        with patch("app.database.SessionLocal", return_value=mock_db):
            client = TestClient(app)
            resp = client.get("/ui/receipts/1")

        assert resp.status_code == 200
        assert "Reprocess" in resp.text

    def test_iframe_onerror_handler_present_when_drive_file_id_set(self):
        """The iframe has an onerror handler to show a fallback on load failure."""
        from fastapi.testclient import TestClient
        from app.main import app

        receipt = _make_receipt(drive_file_id="drive-abc")
        mock_db = _setup_db(receipt)

        with patch("app.database.SessionLocal", return_value=mock_db):
            client = TestClient(app)
            resp = client.get("/ui/receipts/1")

        assert resp.status_code == 200
        assert "onerror" in resp.text
        assert "pdf-error" in resp.text


# ---------------------------------------------------------------------------
# 3. Attachment decisions: only latest run shown; "Show all runs" for history
# ---------------------------------------------------------------------------

class TestAttachmentDecisionsLatestRun:
    """The detail page shows only the latest scoring run's logs by default."""

    def test_single_run_no_history_toggle(self):
        """When there is only one scoring run, the history toggle is not shown."""
        from fastapi.testclient import TestClient
        from app.main import app

        logs = [
            _make_attachment_log(filename="receipt.pdf", created_at=datetime(2025, 1, 1, 10, 0, 0)),
            _make_attachment_log(filename="invoice.pdf", decision="ignored", created_at=datetime(2025, 1, 1, 10, 0, 1)),
        ]
        receipt = _make_receipt(attachment_logs=logs)
        mock_db = _setup_db(receipt)

        with patch("app.database.SessionLocal", return_value=mock_db):
            client = TestClient(app)
            resp = client.get("/ui/receipts/1")

        assert resp.status_code == 200
        assert "receipt.pdf" in resp.text
        assert "invoice.pdf" in resp.text
        # No prior runs → history toggle not shown
        assert "Show all runs" not in resp.text

    def test_multiple_runs_history_toggle_shown(self):
        """When there are prior scoring runs, a 'Show all runs' toggle appears."""
        from fastapi.testclient import TestClient
        from app.main import app

        old_time = datetime(2025, 1, 1, 10, 0, 0)
        new_time = datetime(2025, 1, 2, 10, 0, 0)
        logs = [
            _make_attachment_log(filename="old.pdf", created_at=old_time),
            _make_attachment_log(filename="new.pdf", created_at=new_time),
        ]
        receipt = _make_receipt(attachment_logs=logs)
        mock_db = _setup_db(receipt)

        with patch("app.database.SessionLocal", return_value=mock_db):
            client = TestClient(app)
            resp = client.get("/ui/receipts/1")

        assert resp.status_code == 200
        # Latest run log is shown
        assert "new.pdf" in resp.text
        # History toggle is present because there are prior runs
        assert "Show all runs" in resp.text

    def test_latest_run_badge_shown(self):
        """A 'Latest run' badge is shown in the attachment decisions header."""
        from fastapi.testclient import TestClient
        from app.main import app

        logs = [_make_attachment_log()]
        receipt = _make_receipt(attachment_logs=logs)
        mock_db = _setup_db(receipt)

        with patch("app.database.SessionLocal", return_value=mock_db):
            client = TestClient(app)
            resp = client.get("/ui/receipts/1")

        assert resp.status_code == 200
        assert "Latest run" in resp.text


# ---------------------------------------------------------------------------
# 4. process_receipt_task updates job_run when job_run_id is provided
# ---------------------------------------------------------------------------

class TestProcessReceiptTaskJobRunUpdate:
    """process_receipt_task updates the JobRun to completed/failed when job_run_id is given."""

    def test_job_run_updated_to_completed_on_skip(self):
        """When a receipt is already processed (skip path), the job run is marked completed."""
        from app.tasks.process_receipt import process_receipt_task
        from app.models.receipt import Receipt, ReceiptStatus
        from app.models.job import JobRun, JobStatus

        receipt = Receipt.__new__(Receipt)
        receipt.id = 1
        receipt.gmail_message_id = "msg-done"
        receipt.status = ReceiptStatus.processed

        job_run = JobRun.__new__(JobRun)
        job_run.id = 42
        job_run.status = JobStatus.running
        job_run.completed_at = None
        job_run.details = None
        job_run.error_message = None

        mock_db = MagicMock()
        # First query is for Receipt, second for JobRun (inside _complete_job_run)
        mock_db.query.return_value.filter.return_value.first.side_effect = [receipt, job_run]
        mock_db.__enter__ = lambda s: mock_db
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("app.database.SessionLocal", return_value=mock_db):
            result = process_receipt_task.run("msg-done", user_id=1, job_run_id=42)

        assert result["status"] == "skipped"
        assert job_run.status == JobStatus.completed
        assert job_run.completed_at is not None

    def test_job_run_not_required(self):
        """When job_run_id is None, the task still completes without error on skip path."""
        from app.tasks.process_receipt import process_receipt_task
        from app.models.receipt import Receipt, ReceiptStatus

        receipt = Receipt.__new__(Receipt)
        receipt.id = 1
        receipt.gmail_message_id = "msg-done2"
        receipt.status = ReceiptStatus.processed

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = receipt
        mock_db.__enter__ = lambda s: mock_db
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("app.database.SessionLocal", return_value=mock_db):
            result = process_receipt_task.run("msg-done2", user_id=1, job_run_id=None)

        assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# 5. reprocess endpoint passes job_run_id to the task
# ---------------------------------------------------------------------------

class TestReprocessEndpointPassesJobRunId:
    """The /receipts/{id}/reprocess endpoint passes job_run_id to process_receipt_task."""

    def test_reprocess_passes_job_run_id(self):
        """process_receipt_task.delay is called with the job_run_id kwarg."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db
        from app.services.auth_service import get_current_user
        from app.models.receipt import Receipt, ReceiptStatus
        from app.models.job import JobRun, JobStatus, JobType
        from app.models.user import User

        receipt = Receipt.__new__(Receipt)
        receipt.id = 1
        receipt.gmail_message_id = "msg-reprocess"
        receipt.status = ReceiptStatus.needs_review
        receipt.user_id = 1

        job_run = JobRun.__new__(JobRun)
        job_run.id = 99
        job_run.status = JobStatus.running
        job_run.job_type = JobType.reprocess_receipt
        job_run.details = None
        job_run.task_id = None

        mock_db = MagicMock()
        # query(Receipt).filter(...).first() → receipt
        # query(JobRun) add → job_run (via db.refresh)
        mock_db.query.return_value.filter.return_value.first.return_value = receipt
        mock_db.refresh.side_effect = lambda obj: setattr(obj, "id", 99) if isinstance(obj, JobRun) else None
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()

        mock_user = MagicMock(spec=User)
        mock_user.id = 1

        def override():
            yield mock_db

        captured = {}

        def mock_delay(gmail_message_id, user_id=None, job_run_id=None):
            captured["job_run_id"] = job_run_id
            task = MagicMock()
            task.id = "task-abc"
            return task

        app.dependency_overrides[get_db] = override
        app.dependency_overrides[get_current_user] = lambda: mock_user
        try:
            with patch("app.tasks.process_receipt.process_receipt_task") as mock_task:
                mock_task.delay.side_effect = mock_delay
                client = TestClient(app, raise_server_exceptions=True)
                resp = client.post("/receipts/1/reprocess")
            assert resp.status_code == 200
            # Ensure job_run_id was passed (not None)
            assert captured.get("job_run_id") is not None
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_current_user, None)
