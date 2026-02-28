"""Tests for forwarded email body cleanup and extraction improvements."""
import pytest
from app.services.extraction_service import clean_forwarded_body, extract_from_text


class TestCleanForwardedBody:
    """Tests for the clean_forwarded_body function."""

    def test_plain_text_unchanged(self):
        """Text without forward headers passes through unchanged."""
        text = "Thank you for your order! Total: $29.99"
        assert clean_forwarded_body(text) == text

    def test_strips_forwarded_message_delimiter(self):
        """Classic '--- Forwarded message ---' delimiter is removed and content extracted."""
        text = (
            "FYI\n\n"
            "---------- Forwarded message ----------\n"
            "From: receipts@store.com\n"
            "Date: Mon, 1 Jan 2024 10:00:00 -0000\n"
            "Subject: Your order receipt\n"
            "To: me@example.com\n"
            "\n"
            "Thank you for shopping at ACME! Total: $49.99"
        )
        result = clean_forwarded_body(text)
        assert "Forwarded message" not in result
        assert "From: receipts@store.com" not in result
        assert "Total: $49.99" in result

    def test_strips_original_message_delimiter(self):
        """'--- Original Message ---' delimiter is handled."""
        text = (
            "See below.\n\n"
            "-----Original Message-----\n"
            "From: shop@example.com\n"
            "Subject: Receipt #12345\n"
            "\n"
            "Your purchase was $15.00 on Visa ending in 4321"
        )
        result = clean_forwarded_body(text)
        assert "Original Message" not in result
        assert "$15.00" in result
        assert "4321" in result

    def test_strips_signature_block(self):
        """Signature blocks starting with '--' are stripped."""
        text = (
            "Merchant: Coffee Shop\n"
            "Total: $5.50\n"
            "\n"
            "--\n"
            "John Doe\n"
            "Senior Engineer"
        )
        result = clean_forwarded_body(text)
        assert "Coffee Shop" in result
        assert "$5.50" in result
        assert "John Doe" not in result

    def test_strips_disclaimer_block(self):
        """Disclaimer/confidentiality blocks are stripped."""
        text = (
            "Order total: $120.00\n"
            "Card: Visa ending 1234\n"
            "\n"
            "Confidentiality Notice: This email is intended only for the recipient."
        )
        result = clean_forwarded_body(text)
        assert "$120.00" in result
        assert "Confidentiality Notice" not in result

    def test_strips_reply_chain_marker(self):
        """'On ... wrote:' reply chain markers and subsequent text are stripped."""
        text = (
            "Amount: $75.00\n"
            "Merchant: TechStore\n"
            "\n"
            "On Mon, Jan 1, 2024 at 10:00 AM User <user@example.com> wrote:\n"
            "> Some old message that should be removed\n"
        )
        result = clean_forwarded_body(text)
        assert "$75.00" in result
        assert "TechStore" in result
        assert "wrote:" not in result

    def test_empty_string_returns_empty(self):
        assert clean_forwarded_body("") == ""

    def test_none_like_empty_passthrough(self):
        """None-like empty string is handled gracefully."""
        assert clean_forwarded_body("") == ""

    def test_extraction_improves_on_forwarded_email(self):
        """extract_from_text removes boilerplate and extracts receipt data correctly."""
        forwarded_email = (
            "See the receipt below.\n\n"
            "---------- Forwarded message ----------\n"
            "From: noreply@acme.com\n"
            "Date: Wed, 15 Jan 2025 09:00:00 -0500\n"
            "Subject: Your ACME receipt\n"
            "To: customer@example.com\n"
            "\n"
            "Thank you for shopping at ACME Corp!\n"
            "Order Date: 2025-01-15\n"
            "Order Total: $89.99 USD\n"
            "Card ending in 5678\n"
        )
        result = extract_from_text(forwarded_email, source_type="email_body")
        assert result.amount == 89.99
        assert result.card_last4 == "5678"

    def test_extraction_handles_no_forwarded_header(self):
        """Direct email text is still extracted correctly."""
        text = "Total charged: $15.50\nCard ending in 9999\nDate: 2025-01-10"
        result = extract_from_text(text, source_type="email_body")
        assert result.amount == 15.50
        assert result.card_last4 == "9999"

    def test_begin_forwarded_message_variant(self):
        """'Begin forwarded message' (Apple Mail format) is handled."""
        text = (
            "Forwarded from my phone.\n\n"
            "Begin forwarded message:\n\n"
            "From: billing@service.com\n"
            "Subject: Invoice #99\n"
            "\n"
            "Invoice total: $200.00\n"
        )
        result = clean_forwarded_body(text)
        assert "Begin forwarded message" not in result
        assert "$200.00" in result


class TestProcessedAtTimestamp:
    """Tests for processed_at timestamp being set on receipts."""

    def test_receipt_has_processed_at_field(self):
        """Receipt model has processed_at field."""
        from app.models.receipt import Receipt
        r = Receipt.__new__(Receipt)
        r.processed_at = None
        assert r.processed_at is None

    def test_processed_at_in_receipt_response_schema(self):
        """ReceiptResponse schema includes processed_at field."""
        from app.schemas.receipt import ReceiptResponse
        import inspect
        fields = ReceiptResponse.model_fields
        assert "processed_at" in fields

    def test_processed_at_is_optional_in_schema(self):
        """processed_at is optional (nullable) in the schema."""
        from app.schemas.receipt import ReceiptResponse
        field = ReceiptResponse.model_fields["processed_at"]
        # Optional fields have a default of None
        assert field.default is None or field.is_required() is False


class TestCardManagementEndpoints:
    """Tests for the new card PUT/DELETE and alias DELETE endpoints."""

    def _mock_db(self, card=None, alias=None):
        from unittest.mock import MagicMock
        db = MagicMock()
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = card or alias
        db.query.return_value = q
        db.commit = MagicMock()
        db.refresh = MagicMock()
        db.delete = MagicMock()
        return db

    def test_update_card_endpoint_exists(self):
        """PUT /cards/{card_id} endpoint is registered."""
        from unittest.mock import MagicMock
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db
        from app.services.auth_service import get_current_user
        from app.models.card import PhysicalCard
        from app.models.user import User

        card = PhysicalCard.__new__(PhysicalCard)
        card.id = 1
        card.display_name = "Updated Name"
        card.last4 = "1234"
        card.network = "Visa"
        from datetime import datetime
        card.created_at = datetime(2025, 1, 1)
        card.aliases = []

        mock_db = self._mock_db(card=card)

        mock_user = MagicMock(spec=User)
        mock_user.id = 1

        def override_get_db():
            yield mock_db

        def override_user():
            return mock_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_user
        try:
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.put("/cards/1", json={"display_name": "Updated Name"})
            assert resp.status_code in (200, 409), f"Unexpected status: {resp.status_code}"
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_current_user, None)

    def test_delete_card_endpoint_returns_204(self):
        """DELETE /cards/{card_id} returns 204 when card exists."""
        from unittest.mock import MagicMock
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db
        from app.services.auth_service import get_current_user
        from app.models.card import PhysicalCard
        from app.models.user import User

        card = PhysicalCard.__new__(PhysicalCard)
        card.id = 1
        card.display_name = "Chase"
        card.last4 = "1234"
        card.network = None
        card.aliases = []

        mock_db = self._mock_db(card=card)

        mock_user = MagicMock(spec=User)
        mock_user.id = 1

        def override_get_db():
            yield mock_db

        def override_user():
            return mock_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_user
        try:
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.delete("/cards/1")
            assert resp.status_code == 204
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_current_user, None)

    def test_delete_card_returns_404_when_not_found(self):
        """DELETE /cards/{card_id} returns 404 when card is not found."""
        from unittest.mock import MagicMock
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db
        from app.services.auth_service import get_current_user
        from app.models.user import User

        mock_db = self._mock_db(card=None)

        mock_user = MagicMock(spec=User)
        mock_user.id = 1

        def override_get_db():
            yield mock_db

        def override_user():
            return mock_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_user
        try:
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.delete("/cards/999")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_current_user, None)

    def test_delete_alias_endpoint_returns_204(self):
        """DELETE /cards/{card_id}/aliases/{alias_id} returns 204 when alias exists."""
        from unittest.mock import MagicMock
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db
        from app.services.auth_service import get_current_user
        from app.models.card import CardAlias
        from app.models.user import User

        alias = CardAlias.__new__(CardAlias)
        alias.id = 1
        alias.physical_card_id = 1
        alias.alias_last4 = "9876"
        alias.alias_pattern = None
        alias.notes = None

        mock_db = self._mock_db(alias=alias)

        mock_user = MagicMock(spec=User)
        mock_user.id = 1

        def override_get_db():
            yield mock_db

        def override_user():
            return mock_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_user
        try:
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.delete("/cards/1/aliases/1")
            assert resp.status_code == 204
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_current_user, None)


class TestJobStatusEndpoint:
    """Tests for the /jobs/recent endpoint."""

    def test_jobs_recent_endpoint_exists(self):
        """GET /jobs/recent returns 200."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db
        from app.services.auth_service import get_current_user
        from unittest.mock import MagicMock
        from app.models.job import JobRun, JobType, JobStatus
        from datetime import datetime

        job = JobRun.__new__(JobRun)
        job.id = 1
        job.job_type = JobType.gmail_sync
        job.status = JobStatus.completed
        job.task_id = "abc-123"
        job.started_at = datetime(2025, 1, 1, 10, 0, 0)
        job.completed_at = datetime(2025, 1, 1, 10, 0, 5)
        job.details = "queued 3"
        job.error_message = None

        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = [job]
        mock_db.query.return_value = mock_q

        mock_user = MagicMock()
        mock_user.id = 1

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: mock_user
        try:
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/jobs/recent")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["job_type"] == "gmail_sync"
            assert data[0]["status"] == "completed"
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_current_user, None)


class TestReceiptPatchEndpoint:
    """Tests for the PATCH /receipts/{id} endpoint."""

    def _make_receipt(self):
        from app.models.receipt import Receipt, ReceiptStatus
        from datetime import datetime
        r = Receipt.__new__(Receipt)
        r.id = 1
        r.gmail_message_id = "msg-test"
        r.status = ReceiptStatus.needs_review
        r.subject = "Test"
        r.sender = "shop@example.com"
        r.received_at = None
        r.merchant = "Old Merchant"
        r.purchase_date = None
        r.amount = 10.00
        r.currency = "USD"
        r.card_last4_seen = "1234"
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

    def test_patch_receipt_endpoint_exists(self):
        """PATCH /receipts/{id} is a registered route."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db
        from app.services.auth_service import get_current_user
        from app.models.user import User
        from unittest.mock import MagicMock

        receipt = self._make_receipt()

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = receipt
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        mock_user = MagicMock(spec=User)
        mock_user.id = 1

        def override_get_db():
            yield mock_db

        def override_user():
            return mock_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_user
        try:
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.patch(
                "/receipts/1",
                json={"merchant": "New Merchant"},
                headers={"Content-Type": "application/json"},
            )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_current_user, None)
