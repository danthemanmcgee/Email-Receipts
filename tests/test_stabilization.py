"""Regression tests for the three stabilization fixes:
1. /ui/receipts renders without DetachedInstanceError (eager-load physical_card).
2. Drive upload with an invalid/inaccessible root folder ID fails gracefully.
3. Gmail label creation is idempotent (409 conflict is handled).
"""
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_receipt(physical_card=None, status="processed"):
    """Build a minimal Receipt-like object (no DB session required)."""
    from app.models.receipt import Receipt, ReceiptStatus

    r = Receipt.__new__(Receipt)
    r.id = 1
    r.gmail_message_id = "msg-abc123"
    r.status = ReceiptStatus(status)
    r.subject = "Test receipt"
    r.sender = "shop@example.com"
    r.received_at = None
    r.merchant = "ACME"
    r.purchase_date = None
    r.amount = 12.50
    r.currency = "USD"
    r.card_last4_seen = "1234"
    r.card_network_or_issuer = None
    r.source_type = None
    r.confidence = 0.95
    r.extraction_notes = None
    r.physical_card_id = physical_card.id if physical_card else None
    r.physical_card = physical_card
    r.attachment_logs = []
    r.drive_file_id = None
    r.drive_path = None
    r.content_hash = None
    r.processed_at = None
    r.created_at = None
    r.updated_at = None
    return r


def _make_card(display_name="Chase Visa", last4="1234"):
    from app.models.card import PhysicalCard

    c = PhysicalCard.__new__(PhysicalCard)
    c.id = 1
    c.display_name = display_name
    c.last4 = last4
    return c


# ---------------------------------------------------------------------------
# 1. /ui/receipts endpoint renders without DetachedInstanceError
# ---------------------------------------------------------------------------

class TestUiReceiptsEndpoint:
    """Verify /ui/receipts returns HTTP 200 and renders correctly."""

    def _make_mock_db(self, receipts):
        """Build a mock DB context manager returning *receipts* from query."""
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.count.return_value = len(receipts)
        mock_q.filter.return_value = mock_q
        mock_q.options.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.offset.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = receipts
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = lambda s: mock_db
        mock_db.__exit__ = MagicMock(return_value=False)
        return mock_db

    def test_receipts_page_returns_200_with_no_receipts(self):
        from fastapi.testclient import TestClient
        from app.main import app

        mock_db = self._make_mock_db([])
        with patch("app.database.SessionLocal", return_value=mock_db):
            response = TestClient(app, raise_server_exceptions=True).get("/ui/receipts")
        assert response.status_code == 200
        assert "No receipts found" in response.text

    def test_receipts_page_returns_200_with_receipt_with_card(self):
        from fastapi.testclient import TestClient
        from app.main import app

        card = _make_card()
        receipt = _make_receipt(physical_card=card)
        mock_db = self._make_mock_db([receipt])
        with patch("app.database.SessionLocal", return_value=mock_db):
            response = TestClient(app, raise_server_exceptions=True).get("/ui/receipts")
        assert response.status_code == 200
        assert "Chase Visa" in response.text

    def test_receipts_page_returns_200_with_receipt_without_card(self):
        from fastapi.testclient import TestClient
        from app.main import app

        receipt = _make_receipt(physical_card=None)
        mock_db = self._make_mock_db([receipt])
        with patch("app.database.SessionLocal", return_value=mock_db):
            response = TestClient(app, raise_server_exceptions=True).get("/ui/receipts")
        assert response.status_code == 200
        # Card column should show the em-dash placeholder
        assert "—" in response.text

    def test_receipts_page_uses_selectinload_for_physical_card(self):
        """Verify the route calls .options() so the relationship is eager-loaded."""
        from fastapi.testclient import TestClient
        from app.main import app

        mock_db = self._make_mock_db([])
        with patch("app.database.SessionLocal", return_value=mock_db):
            TestClient(app).get("/ui/receipts")

        # .options() must have been called (eager loading)
        mock_db.query.return_value.options.assert_called()


# ---------------------------------------------------------------------------
# 2. Drive upload with invalid folder ID fails gracefully
# ---------------------------------------------------------------------------

class TestDriveFolderValidation:
    def _make_failing_service(self, status_code=404, message="File not found"):
        """Return a mock Drive service whose files().get() raises an HttpError-like."""
        svc = MagicMock()
        exc = Exception(f"<HttpError {status_code} when requesting ...>: {message!r}")
        svc.files.return_value.get.return_value.execute.side_effect = exc
        return svc

    def test_validate_drive_folder_id_returns_false_on_404(self):
        from app.services.drive_service import validate_drive_folder_id

        svc = self._make_failing_service(404)
        valid, reason = validate_drive_folder_id(svc, "bad-folder-id")
        assert valid is False
        assert reason  # non-empty diagnostic message

    def test_validate_drive_folder_id_returns_true_for_valid_folder(self):
        from app.services.drive_service import validate_drive_folder_id

        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = {
            "id": "folder123",
            "name": "Receipts",
            "mimeType": "application/vnd.google-apps.folder",
        }
        valid, reason = validate_drive_folder_id(svc, "folder123")
        assert valid is True
        assert reason == "ok"

    def test_validate_drive_folder_id_returns_false_for_non_folder(self):
        from app.services.drive_service import validate_drive_folder_id

        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = {
            "id": "file123",
            "name": "receipt.pdf",
            "mimeType": "application/pdf",
        }
        valid, reason = validate_drive_folder_id(svc, "file123")
        assert valid is False
        assert "not a folder" in reason

    def test_upload_pdf_returns_none_for_invalid_root_folder_id(self):
        from app.services.drive_service import upload_pdf_to_drive

        svc = self._make_failing_service(404)
        result = upload_pdf_to_drive(
            svc,
            pdf_bytes=b"%PDF-fake",
            folder_path="Receipts/Chase/2024/2024-01",
            filename="test.pdf",
            root_folder_id="bad-folder-id",
        )
        assert result is None

    def test_upload_pdf_logs_error_for_invalid_root_folder(self, caplog):
        import logging
        from app.services.drive_service import upload_pdf_to_drive

        svc = self._make_failing_service(404)
        with caplog.at_level(logging.ERROR, logger="app.services.drive_service"):
            upload_pdf_to_drive(
                svc,
                pdf_bytes=b"%PDF-fake",
                folder_path="Receipts/Chase/2024/2024-01",
                filename="test.pdf",
                root_folder_id="bad-folder-id",
            )
        assert any("not accessible" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 3. Gmail label creation is idempotent (409 conflict handling)
# ---------------------------------------------------------------------------

class TestGmailLabelIdempotency:
    def _make_service(self, existing_labels=None, create_side_effect=None):
        """Build a mock Gmail service."""
        svc = MagicMock()
        labels_list = existing_labels or []
        svc.users.return_value.labels.return_value.list.return_value.execute.return_value = {
            "labels": labels_list
        }
        if create_side_effect is not None:
            svc.users.return_value.labels.return_value.create.return_value.execute.side_effect = (
                create_side_effect
            )
        else:
            svc.users.return_value.labels.return_value.create.return_value.execute.return_value = {
                "id": "new-label-id",
                "name": "receipt/processed",
            }
        svc.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}
        return svc

    def test_apply_label_creates_new_label_when_not_present(self):
        from app.services.gmail_service import apply_label

        svc = self._make_service(existing_labels=[])
        result = apply_label(svc, "msg-001", "receipt/processed")
        assert result is True
        svc.users.return_value.labels.return_value.create.assert_called_once()

    def test_apply_label_reuses_existing_label_without_creating(self):
        from app.services.gmail_service import apply_label

        svc = self._make_service(
            existing_labels=[{"id": "existing-id", "name": "receipt/processed"}]
        )
        result = apply_label(svc, "msg-001", "receipt/processed")
        assert result is True
        svc.users.return_value.labels.return_value.create.assert_not_called()

    def test_apply_label_handles_409_conflict_and_succeeds(self):
        """When create() raises a 409-like error, apply_label re-fetches and succeeds."""
        from app.services.gmail_service import apply_label

        # Simulate: label not found on first list, 409 on create, then found on re-list
        conflict_exc = Exception("<HttpError 409 when requesting ...>: Label name exists")

        list_responses = [
            # First call: label not present
            {"labels": []},
            # Second call (after 409): label now present
            {"labels": [{"id": "label-after-409", "name": "receipt/processed"}]},
        ]
        list_iter = iter(list_responses)

        svc = MagicMock()
        svc.users.return_value.labels.return_value.list.return_value.execute.side_effect = (
            lambda: next(list_iter)
        )
        svc.users.return_value.labels.return_value.create.return_value.execute.side_effect = (
            conflict_exc
        )
        svc.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}

        result = apply_label(svc, "msg-001", "receipt/processed")
        assert result is True
        # modify() should have been called with the label ID obtained after re-fetch
        modify_call = svc.users.return_value.messages.return_value.modify.call_args
        assert "label-after-409" in modify_call.kwargs.get("body", {}).get("addLabelIds", [])

    def test_apply_label_handles_409_via_resp_status_attribute(self):
        """Handle HttpError objects that expose .resp.status == 409."""
        from app.services.gmail_service import apply_label

        # Build an exception with a .resp.status attribute
        exc = Exception("conflict")
        exc.resp = MagicMock()
        exc.resp.status = 409

        list_responses = [
            {"labels": []},
            {"labels": [{"id": "lbl-via-resp", "name": "receipt/needs-review"}]},
        ]
        list_iter = iter(list_responses)

        svc = MagicMock()
        svc.users.return_value.labels.return_value.list.return_value.execute.side_effect = (
            lambda: next(list_iter)
        )
        svc.users.return_value.labels.return_value.create.return_value.execute.side_effect = exc
        svc.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}

        result = apply_label(svc, "msg-002", "receipt/needs-review")
        assert result is True

    def test_apply_label_propagates_non_409_errors(self):
        """A non-409 create error should propagate and cause apply_label to return False."""
        from app.services.gmail_service import apply_label

        server_error = Exception("<HttpError 500 when requesting ...>: Internal error")

        svc = MagicMock()
        svc.users.return_value.labels.return_value.list.return_value.execute.return_value = {
            "labels": []
        }
        svc.users.return_value.labels.return_value.create.return_value.execute.side_effect = (
            server_error
        )

        result = apply_label(svc, "msg-003", "receipt/processed")
        assert result is False
