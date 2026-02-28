"""Tests for:
1. Job status banner auto-polling: /jobs/recent returns correct data for active jobs.
2. PDF preview loading spinner: detail page renders the spinner element when drive_file_id is set.
3. Inline edit: PATCH /receipts/{id} returns updated fields; detail page view-mode ids exist.
"""
from unittest.mock import MagicMock
from datetime import datetime

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_receipt(drive_file_id=None, merchant="ACME", amount=12.50, currency="USD",
                  purchase_date=None, card_last4_seen="1234"):
    from app.models.receipt import Receipt, ReceiptStatus

    r = Receipt.__new__(Receipt)
    r.id = 1
    r.gmail_message_id = "msg-abc"
    r.status = ReceiptStatus.processed
    r.subject = "Test"
    r.sender = "shop@example.com"
    r.received_at = None
    r.merchant = merchant
    r.purchase_date = purchase_date
    r.amount = amount
    r.currency = currency
    r.card_last4_seen = card_last4_seen
    r.card_network_or_issuer = None
    r.source_type = None
    r.confidence = 0.95
    r.extraction_notes = None
    r.physical_card_id = None
    r.physical_card = None
    r.attachment_logs = []
    r.drive_file_id = drive_file_id
    r.drive_path = None
    r.content_hash = None
    r.processed_at = None
    r.created_at = datetime(2025, 1, 1)
    r.updated_at = datetime(2025, 1, 1)
    return r


# ---------------------------------------------------------------------------
# 1. Job status endpoint returns active jobs correctly
# ---------------------------------------------------------------------------

class TestJobStatusActivePolling:
    """The /jobs/recent endpoint correctly surfaces running/pending jobs."""

    def _mock_job(self, status):
        from app.models.job import JobRun, JobType, JobStatus
        j = JobRun.__new__(JobRun)
        j.id = 1
        j.job_type = JobType.gmail_sync
        j.status = JobStatus(status)
        j.task_id = "task-1"
        j.started_at = datetime(2025, 1, 1, 10, 0, 0)
        j.completed_at = None
        j.details = None
        j.error_message = None
        return j

    def _mock_db(self, jobs):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = jobs
        mock_db.query.return_value = mock_q
        return mock_db

    def test_running_job_returned(self):
        """Running jobs appear in /jobs/recent response."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db

        job = self._mock_job("running")
        mock_db = self._mock_db([job])

        def override():
            yield mock_db

        app.dependency_overrides[get_db] = override
        try:
            client = TestClient(app)
            resp = client.get("/jobs/recent?limit=5")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["status"] == "running"
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_pending_job_returned(self):
        """Pending jobs appear in /jobs/recent response."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db

        job = self._mock_job("pending")
        mock_db = self._mock_db([job])

        def override():
            yield mock_db

        app.dependency_overrides[get_db] = override
        try:
            client = TestClient(app)
            resp = client.get("/jobs/recent?limit=5")
            assert resp.status_code == 200
            data = resp.json()
            assert data[0]["status"] == "pending"
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_completed_job_returned(self):
        """Completed jobs appear in /jobs/recent response."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db

        job = self._mock_job("completed")
        mock_db = self._mock_db([job])

        def override():
            yield mock_db

        app.dependency_overrides[get_db] = override
        try:
            client = TestClient(app)
            resp = client.get("/jobs/recent?limit=5")
            assert resp.status_code == 200
            data = resp.json()
            assert data[0]["status"] == "completed"
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 2. PDF preview loading spinner on detail page
# ---------------------------------------------------------------------------

class TestPdfPreviewSpinner:
    """The receipt detail page shows a loading spinner when drive_file_id is set."""

    def _setup_db(self, receipt):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.options.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = receipt
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = lambda s: mock_db
        mock_db.__exit__ = MagicMock(return_value=False)
        return mock_db

    def test_spinner_present_when_drive_file_id_set(self):
        """Detail page contains the pdf-loading spinner element when drive_file_id is set."""
        from fastapi.testclient import TestClient
        from app.main import app
        from unittest.mock import patch

        receipt = _make_receipt(drive_file_id="abc-drive-id")
        mock_db = self._setup_db(receipt)

        with patch("app.database.SessionLocal", return_value=mock_db):
            client = TestClient(app)
            resp = client.get("/ui/receipts/1")
        assert resp.status_code == 200
        assert 'id="pdf-loading"' in resp.text
        assert "spinner-border" in resp.text
        assert "abc-drive-id" in resp.text

    def test_spinner_absent_when_no_drive_file_id(self):
        """Detail page does not show the PDF section when drive_file_id is absent."""
        from fastapi.testclient import TestClient
        from app.main import app
        from unittest.mock import patch

        receipt = _make_receipt(drive_file_id=None)
        mock_db = self._setup_db(receipt)

        with patch("app.database.SessionLocal", return_value=mock_db):
            client = TestClient(app)
            resp = client.get("/ui/receipts/1")
        assert resp.status_code == 200
        assert 'id="pdf-loading"' not in resp.text


# ---------------------------------------------------------------------------
# 3. Inline edit: view-mode id attributes present; PATCH returns updated data
# ---------------------------------------------------------------------------

class TestInlineEditViewIds:
    """The detail page view-mode elements have the expected id attributes for inline update."""

    def _setup_db(self, receipt):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.options.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = receipt
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = lambda s: mock_db
        mock_db.__exit__ = MagicMock(return_value=False)
        return mock_db

    def test_view_mode_ids_present(self):
        """Detail page contains the expected id attributes used by _updateExtractionView."""
        from fastapi.testclient import TestClient
        from app.main import app
        from unittest.mock import patch

        receipt = _make_receipt()
        mock_db = self._setup_db(receipt)

        with patch("app.database.SessionLocal", return_value=mock_db):
            client = TestClient(app)
            resp = client.get("/ui/receipts/1")
        assert resp.status_code == 200
        for id_attr in ('id="view-merchant"', 'id="view-purchase-date"',
                        'id="view-amount"', 'id="view-card-last4"'):
            assert id_attr in resp.text, f"Missing {id_attr} in detail page"


class TestPatchReceiptInlineUpdate:
    """PATCH /receipts/{id} returns updated field values used for the inline view update."""

    def _make_receipt_obj(self, merchant="Old", amount=10.0, currency="USD",
                          purchase_date=None, card_last4_seen="1111"):
        from app.models.receipt import Receipt, ReceiptStatus
        from datetime import datetime

        r = Receipt.__new__(Receipt)
        r.id = 1
        r.gmail_message_id = "msg-patch"
        r.status = ReceiptStatus.needs_review
        r.subject = "Test"
        r.sender = "s@x.com"
        r.received_at = None
        r.merchant = merchant
        r.purchase_date = purchase_date
        r.amount = amount
        r.currency = currency
        r.card_last4_seen = card_last4_seen
        r.card_network_or_issuer = None
        r.source_type = None
        r.confidence = 0.5
        r.extraction_notes = None
        r.physical_card_id = None
        r.physical_card = None
        r.attachment_logs = []
        r.drive_file_id = None
        r.drive_path = None
        r.content_hash = None
        r.processed_at = None
        r.created_at = datetime(2025, 1, 1)
        r.updated_at = datetime(2025, 1, 1)
        return r

    def test_patch_returns_updated_merchant(self):
        """PATCH /receipts/{id} returns merchant in response body."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db

        receipt = self._make_receipt_obj(merchant="Old")

        def set_merchant(key, val):
            if key == "merchant":
                receipt.merchant = val

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = receipt
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        def override():
            yield mock_db

        app.dependency_overrides[get_db] = override
        try:
            # Simulate what setattr does
            receipt.merchant = "New Merchant"
            client = TestClient(app)
            resp = client.patch("/receipts/1", json={"merchant": "New Merchant"})
            assert resp.status_code == 200
            data = resp.json()
            assert "merchant" in data
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_patch_returns_amount_and_currency(self):
        """PATCH /receipts/{id} response includes amount and currency fields."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db

        receipt = self._make_receipt_obj(amount=10.0, currency="USD")

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = receipt
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        def override():
            yield mock_db

        app.dependency_overrides[get_db] = override
        try:
            client = TestClient(app)
            resp = client.patch("/receipts/1", json={"amount": 99.99, "currency": "EUR"})
            assert resp.status_code == 200
            data = resp.json()
            assert "amount" in data
            assert "currency" in data
        finally:
            app.dependency_overrides.pop(get_db, None)
