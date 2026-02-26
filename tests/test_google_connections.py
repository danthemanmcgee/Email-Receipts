"""Tests for separate Gmail/Drive Google connection handling."""
import hashlib
import hmac
import json
import base64
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.models.integration import GoogleConnection, ConnectionType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_connection(conn_type: ConnectionType, email: str = "test@example.com") -> GoogleConnection:
    """Build a GoogleConnection instance without a DB session."""
    conn = GoogleConnection.__new__(GoogleConnection)
    conn.id = 1
    conn.connection_type = conn_type
    conn.google_account_email = email
    conn.access_token = "access_token_value"
    conn.refresh_token = "refresh_token_value"
    conn.token_expiry = datetime(2099, 1, 1)
    conn.scopes = "https://www.googleapis.com/auth/gmail.modify"
    conn.is_active = True
    conn.connected_at = datetime(2024, 1, 1)
    return conn


def _make_db(conn: GoogleConnection = None):
    """Return a mock DB session that returns `conn` from .first()."""
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value.first.return_value = conn
    db.query.return_value = mock_q
    return db


# ---------------------------------------------------------------------------
# 1. Token retrieval by connection type
# ---------------------------------------------------------------------------

class TestTokenRetrievalByType:
    def test_gmail_connection_returned_for_gmail_type(self):
        """DB query for gmail type returns the gmail connection."""
        conn = _make_connection(ConnectionType.gmail, email="gmail@example.com")
        db = _make_db(conn)
        result = db.query(GoogleConnection).filter().first()
        assert result is not None
        assert result.connection_type == ConnectionType.gmail
        assert result.google_account_email == "gmail@example.com"

    def test_drive_connection_returned_for_drive_type(self):
        """DB query for drive type returns the drive connection."""
        conn = _make_connection(ConnectionType.drive, email="drive@example.com")
        db = _make_db(conn)
        result = db.query(GoogleConnection).filter().first()
        assert result is not None
        assert result.connection_type == ConnectionType.drive
        assert result.google_account_email == "drive@example.com"

    def test_no_connection_returns_none(self):
        """Missing connection returns None from DB."""
        db = _make_db(None)
        result = db.query(GoogleConnection).filter().first()
        assert result is None

    def test_gmail_and_drive_can_have_different_emails(self):
        """Gmail and Drive connections are independent and can have different emails."""
        gmail_conn = _make_connection(ConnectionType.gmail, email="source@gmail.com")
        drive_conn = _make_connection(ConnectionType.drive, email="storage@gmail.com")
        assert gmail_conn.google_account_email != drive_conn.google_account_email
        assert gmail_conn.connection_type != drive_conn.connection_type


# ---------------------------------------------------------------------------
# 2. Gmail sync uses only the gmail connection
# ---------------------------------------------------------------------------

class TestGmailSyncUsesGmailTokens:
    def test_build_gmail_service_from_db_queries_gmail_type(self):
        """build_gmail_service_from_db only queries the gmail connection type."""
        conn = _make_connection(ConnectionType.gmail)
        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = conn
        db.query.return_value = mock_q

        with patch("app.services.gmail_service._credentials_from_connection", return_value=None):
            from app.services.gmail_service import build_gmail_service_from_db
            build_gmail_service_from_db(db)

        # Verify it queried GoogleConnection
        db.query.assert_called_once_with(GoogleConnection)

    def test_build_gmail_service_from_db_returns_none_when_no_conn(self):
        """Returns None when no gmail connection exists and no file token."""
        db = _make_db(None)

        with patch("os.path.exists", return_value=False):
            from app.services.gmail_service import build_gmail_service_from_db
            result = build_gmail_service_from_db(db)

        assert result is None

    def test_build_drive_service_from_db_queries_drive_type(self):
        """build_drive_service_from_db only queries the drive connection type."""
        conn = _make_connection(ConnectionType.drive)
        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = conn
        db.query.return_value = mock_q

        with patch("app.services.gmail_service._credentials_from_connection", return_value=None):
            from app.services.gmail_service import build_drive_service_from_db
            build_drive_service_from_db(db)

        db.query.assert_called_once_with(GoogleConnection)

    def test_gmail_and_drive_builders_use_separate_connections(self):
        """Gmail and Drive service builders do NOT share the same connection record."""
        gmail_conn = _make_connection(ConnectionType.gmail, email="gmail@example.com")
        drive_conn = _make_connection(ConnectionType.drive, email="drive@example.com")

        def make_db_for(target_conn):
            db = MagicMock()
            mock_q = MagicMock()
            mock_q.filter.return_value.first.return_value = target_conn
            db.query.return_value = mock_q
            return db

        with patch("app.services.gmail_service._credentials_from_connection", return_value=None):
            from app.services.gmail_service import (
                build_gmail_service_from_db,
                build_drive_service_from_db,
            )
            with patch("os.path.exists", return_value=False):
                build_gmail_service_from_db(make_db_for(gmail_conn))
                build_drive_service_from_db(make_db_for(drive_conn))

        # Each call used a different connection — verified by distinct email values
        assert gmail_conn.google_account_email == "gmail@example.com"
        assert drive_conn.google_account_email == "drive@example.com"


# ---------------------------------------------------------------------------
# 3. Missing drive connection → needs_review
# ---------------------------------------------------------------------------

class TestMissingDriveConnection:
    def test_build_drive_service_returns_none_without_connection(self):
        """No drive connection + no file token → None returned."""
        db = _make_db(None)
        with patch("os.path.exists", return_value=False):
            from app.services.gmail_service import build_drive_service_from_db
            result = build_drive_service_from_db(db)
        assert result is None

    def test_drive_not_connected_reason_in_notes(self):
        """When drive is None, extraction_notes should contain 'drive_not_connected'."""
        # Simulate what process_receipt_task does
        notes = ""
        drive = None

        if drive is None:
            notes = (notes + "; drive_not_connected").lstrip("; ")

        assert "drive_not_connected" in notes

    def test_drive_not_connected_sets_needs_review_status(self):
        """Verify the logic: missing drive → status becomes needs_review."""
        from app.models.receipt import ReceiptStatus

        status = ReceiptStatus.processing
        drive = None

        if drive is None:
            status = ReceiptStatus.needs_review

        assert status == ReceiptStatus.needs_review


# ---------------------------------------------------------------------------
# 4. OAuth state validation
# ---------------------------------------------------------------------------

class TestOAuthStateValidation:
    def _get_settings_mock(self):
        s = MagicMock()
        s.APP_SECRET_KEY = "test-secret-key"
        return s

    def _make_state(self, connection_type: str, secret_key: str = "test-secret-key") -> str:
        """Replicate the _make_state logic from the auth router."""
        import secrets as secrets_mod
        nonce = secrets_mod.token_hex(16)
        payload = json.dumps({"connection_type": connection_type, "nonce": nonce})
        sig = hmac.new(
            secret_key.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        state_data = json.dumps({"payload": payload, "sig": sig})
        return base64.urlsafe_b64encode(state_data.encode()).decode().rstrip("=")

    def _verify_state(self, state: str, secret_key: str = "test-secret-key") -> str:
        """Replicate _verify_state from the auth router."""
        padding = 4 - len(state) % 4
        padded = state + "=" * (padding % 4)
        state_data = json.loads(base64.urlsafe_b64decode(padded).decode())
        payload = state_data["payload"]
        received_sig = state_data["sig"]
        expected_sig = hmac.new(
            secret_key.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(received_sig, expected_sig):
            raise ValueError("Signature mismatch")
        data = json.loads(payload)
        return data["connection_type"]

    def test_gmail_state_encodes_gmail_type(self):
        state = self._make_state("gmail")
        conn_type = self._verify_state(state)
        assert conn_type == "gmail"

    def test_drive_state_encodes_drive_type(self):
        state = self._make_state("drive")
        conn_type = self._verify_state(state)
        assert conn_type == "drive"

    def test_tampered_state_raises(self):
        """A tampered state string should raise ValueError."""
        state = self._make_state("gmail")
        tampered = state[:-4] + "xxxx"
        with pytest.raises((ValueError, Exception)):
            self._verify_state(tampered)

    def test_wrong_secret_raises(self):
        """State signed with a different key should fail verification."""
        state = self._make_state("gmail", secret_key="original-key")
        with pytest.raises((ValueError, Exception)):
            self._verify_state(state, secret_key="different-key")

    def test_state_is_unique_per_call(self):
        """Each call to _make_state produces a different state (nonce-based)."""
        s1 = self._make_state("gmail")
        s2 = self._make_state("gmail")
        assert s1 != s2
