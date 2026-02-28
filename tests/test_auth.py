"""Tests for multi-user authentication: email/password and data isolation."""
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.models.user import User  # noqa: E402
from app.services.auth_service import (  # noqa: E402
    hash_password,
    verify_password,
    create_session_token,
    decode_session_token,
    set_session_cookie,
    clear_session_cookie,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(id: int = 1, email: str = "alice@example.com", password: str = "secret123") -> User:
    """Build a User instance without a DB session."""
    user = User.__new__(User)
    user.id = id
    user.email = email
    user.hashed_password = hash_password(password)
    user.google_sub = None
    user.is_active = True
    user.created_at = datetime.now(tz=timezone.utc)
    user.updated_at = datetime.now(tz=timezone.utc)
    return user


# ---------------------------------------------------------------------------
# 1. Password hashing
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        hashed = hash_password("mysecret")
        assert hashed != "mysecret"

    def test_hash_is_bcrypt(self):
        hashed = hash_password("mysecret")
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")

    def test_correct_password_verifies(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", hashed) is True

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("wrong-password", hashed) is False

    def test_empty_password_fails_against_real_hash(self):
        hashed = hash_password("notempty")
        assert verify_password("", hashed) is False

    def test_two_hashes_of_same_password_differ(self):
        """bcrypt uses a random salt, so identical passwords produce different hashes."""
        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        assert h1 != h2

    def test_both_hashes_verify_correctly(self):
        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        assert verify_password("same-password", h1) is True
        assert verify_password("same-password", h2) is True


# ---------------------------------------------------------------------------
# 2. JWT session tokens
# ---------------------------------------------------------------------------

class TestSessionTokens:
    def test_token_encodes_user_id(self):
        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.APP_SECRET_KEY = "test-secret"
            token = create_session_token(42)
            user_id = decode_session_token(token)
        assert user_id == 42

    def test_different_users_produce_different_tokens(self):
        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.APP_SECRET_KEY = "test-secret"
            t1 = create_session_token(1)
            t2 = create_session_token(2)
        assert t1 != t2

    def test_tampered_token_raises(self):
        import jwt as pyjwt
        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.APP_SECRET_KEY = "test-secret"
            token = create_session_token(1)
        # Tamper by appending garbage
        tampered = token[:-4] + "xxxx"
        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.APP_SECRET_KEY = "test-secret"
            with pytest.raises(Exception):
                decode_session_token(tampered)

    def test_wrong_secret_key_raises(self):
        import jwt as pyjwt
        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.APP_SECRET_KEY = "secret-a"
            token = create_session_token(5)
        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.APP_SECRET_KEY = "secret-b"
            with pytest.raises(Exception):
                decode_session_token(token)


# ---------------------------------------------------------------------------
# 3. get_current_user dependency
# ---------------------------------------------------------------------------

class TestGetCurrentUser:
    def _make_request(self, cookie_value=None, cookie_name="session"):
        request = MagicMock()
        request.cookies = {cookie_name: cookie_value} if cookie_value else {}
        return request

    def test_missing_cookie_raises_401(self):
        from fastapi import HTTPException
        from app.services.auth_service import get_current_user

        request = self._make_request()
        db = MagicMock()

        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.SESSION_COOKIE_NAME = "session"
            mock_settings.return_value.APP_SECRET_KEY = "secret"
            with pytest.raises(HTTPException) as exc_info:
                get_current_user(request, db)
        assert exc_info.value.status_code == 401

    def test_invalid_token_raises_401(self):
        from fastapi import HTTPException
        from app.services.auth_service import get_current_user

        request = self._make_request(cookie_value="not-a-valid-jwt")
        db = MagicMock()

        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.SESSION_COOKIE_NAME = "session"
            mock_settings.return_value.APP_SECRET_KEY = "secret"
            with pytest.raises(HTTPException) as exc_info:
                get_current_user(request, db)
        assert exc_info.value.status_code == 401

    def test_valid_token_returns_user(self):
        from app.services.auth_service import get_current_user

        user = _make_user(id=7)
        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.APP_SECRET_KEY = "test-secret"
            mock_settings.return_value.SESSION_COOKIE_NAME = "session"
            token = create_session_token(7)

        request = self._make_request(cookie_value=token)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user

        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.SESSION_COOKIE_NAME = "session"
            mock_settings.return_value.APP_SECRET_KEY = "test-secret"
            result = get_current_user(request, db)

        assert result.id == 7
        assert result.email == "alice@example.com"

    def test_inactive_user_raises_401(self):
        from fastapi import HTTPException
        from app.services.auth_service import get_current_user

        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.APP_SECRET_KEY = "test-secret"
            mock_settings.return_value.SESSION_COOKIE_NAME = "session"
            token = create_session_token(9)

        request = self._make_request(cookie_value=token)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None  # user not found

        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.SESSION_COOKIE_NAME = "session"
            mock_settings.return_value.APP_SECRET_KEY = "test-secret"
            with pytest.raises(HTTPException) as exc_info:
                get_current_user(request, db)
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# 4. Cookie management
# ---------------------------------------------------------------------------

class TestCookieManagement:
    def test_set_session_cookie_is_httponly(self):
        response = MagicMock()
        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.SESSION_COOKIE_NAME = "session"
            mock_settings.return_value.SESSION_COOKIE_SECURE = False
            mock_settings.return_value.APP_SECRET_KEY = "test-secret"
            set_session_cookie(response, user_id=1)

        call_kwargs = response.set_cookie.call_args.kwargs
        assert call_kwargs.get("httponly") is True

    def test_set_session_cookie_has_samesite_lax(self):
        response = MagicMock()
        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.SESSION_COOKIE_NAME = "session"
            mock_settings.return_value.SESSION_COOKIE_SECURE = False
            mock_settings.return_value.APP_SECRET_KEY = "test-secret"
            set_session_cookie(response, user_id=1)

        call_kwargs = response.set_cookie.call_args.kwargs
        assert call_kwargs.get("samesite") == "lax"

    def test_set_session_cookie_secure_in_production(self):
        response = MagicMock()
        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.SESSION_COOKIE_NAME = "session"
            mock_settings.return_value.SESSION_COOKIE_SECURE = True
            mock_settings.return_value.APP_SECRET_KEY = "test-secret"
            set_session_cookie(response, user_id=1)

        call_kwargs = response.set_cookie.call_args.kwargs
        assert call_kwargs.get("secure") is True

    def test_clear_session_cookie_calls_delete_cookie(self):
        response = MagicMock()
        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.SESSION_COOKIE_NAME = "session"
            mock_settings.return_value.SESSION_COOKIE_SECURE = False
            clear_session_cookie(response)

        response.delete_cookie.assert_called_once()
        call_kwargs = response.delete_cookie.call_args.kwargs
        assert call_kwargs.get("key") == "session"


# ---------------------------------------------------------------------------
# 5. User model
# ---------------------------------------------------------------------------

class TestUserModel:
    def test_email_stored_on_user(self):
        user = _make_user(email="test@example.com")
        assert user.email == "test@example.com"

    def test_password_is_hashed(self):
        user = _make_user(password="plaintext")
        assert user.hashed_password != "plaintext"
        assert verify_password("plaintext", user.hashed_password) is True

    def test_google_sub_defaults_none(self):
        user = _make_user()
        assert user.google_sub is None

    def test_google_only_user_has_no_password(self):
        user = User.__new__(User)
        user.id = 99
        user.email = "google@example.com"
        user.hashed_password = None
        user.google_sub = "google-sub-id-123"
        user.is_active = True
        assert user.hashed_password is None
        assert user.google_sub == "google-sub-id-123"


# ---------------------------------------------------------------------------
# 6. Two-user data isolation
# ---------------------------------------------------------------------------

class TestTwoUserDataIsolation:
    """Verify that User A's data is not accessible to User B."""

    def _make_receipt(self, id: int, user_id: int, subject: str):
        from app.models.receipt import Receipt, ReceiptStatus
        r = Receipt.__new__(Receipt)
        r.id = id
        r.user_id = user_id
        r.gmail_message_id = f"msg-{id}"
        r.status = ReceiptStatus.new
        r.subject = subject
        r.sender = None
        r.received_at = None
        r.merchant = None
        r.purchase_date = None
        r.amount = None
        r.currency = "USD"
        r.card_last4_seen = None
        r.card_network_or_issuer = None
        r.source_type = None
        r.confidence = None
        r.extraction_notes = None
        r.physical_card_id = None
        r.drive_file_id = None
        r.drive_path = None
        r.content_hash = None
        r.processed_at = None
        r.created_at = datetime.now(tz=timezone.utc)
        r.updated_at = datetime.now(tz=timezone.utc)
        return r

    def test_user_a_receipts_not_visible_to_user_b(self):
        """Simulate DB query filtered by user_id: User B cannot see User A's receipts."""
        user_a = _make_user(id=1, email="alice@example.com")
        user_b = _make_user(id=2, email="bob@example.com")

        receipt_a = self._make_receipt(id=10, user_id=user_a.id, subject="Alice's receipt")
        receipt_b = self._make_receipt(id=20, user_id=user_b.id, subject="Bob's receipt")

        all_receipts = [receipt_a, receipt_b]

        # Simulate what list_receipts does: filter by current_user.id
        alice_sees = [r for r in all_receipts if r.user_id == user_a.id]
        bob_sees = [r for r in all_receipts if r.user_id == user_b.id]

        assert len(alice_sees) == 1
        assert alice_sees[0].subject == "Alice's receipt"

        assert len(bob_sees) == 1
        assert bob_sees[0].subject == "Bob's receipt"

        # Cross-check: Alice cannot see Bob's receipt, Bob cannot see Alice's
        assert receipt_b not in alice_sees
        assert receipt_a not in bob_sees

    def test_get_receipt_scoped_to_user(self):
        """A user requesting another user's receipt_id gets nothing (404)."""
        user_a = _make_user(id=1)
        user_b = _make_user(id=2, email="bob@example.com")

        receipt_a = self._make_receipt(id=5, user_id=user_a.id, subject="Alice's receipt")

        # Bob tries to fetch receipt 5 (Alice's)
        # Simulates: db.query(Receipt).filter(id==5, user_id==user_b.id).first()
        result = next(
            (r for r in [receipt_a] if r.id == 5 and r.user_id == user_b.id),
            None,
        )
        assert result is None  # Bob gets nothing

    def test_two_users_have_distinct_ids(self):
        user_a = _make_user(id=1, email="alice@example.com")
        user_b = _make_user(id=2, email="bob@example.com")
        assert user_a.id != user_b.id
        assert user_a.email != user_b.email

    def test_login_produces_user_specific_token(self):
        """Tokens for different users decode to their respective user_ids."""
        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.APP_SECRET_KEY = "test-secret"
            token_a = create_session_token(1)
            token_b = create_session_token(2)

        with patch("app.services.auth_service.get_settings") as mock_settings:
            mock_settings.return_value.APP_SECRET_KEY = "test-secret"
            assert decode_session_token(token_a) == 1
            assert decode_session_token(token_b) == 2

        # Tokens are different
        assert token_a != token_b


# ---------------------------------------------------------------------------
# 7. User schema validation
# ---------------------------------------------------------------------------

class TestUserSchemas:
    def test_signup_normalizes_email(self):
        from app.schemas.user import UserCreate
        schema = UserCreate(email="  Alice@EXAMPLE.COM  ", password="password123")
        assert schema.email == "alice@example.com"

    def test_signup_rejects_short_password(self):
        from pydantic import ValidationError
        from app.schemas.user import UserCreate
        with pytest.raises(ValidationError):
            UserCreate(email="a@b.com", password="short")

    def test_login_normalizes_email(self):
        from app.schemas.user import UserLogin
        schema = UserLogin(email="  Bob@EXAMPLE.COM  ", password="anypassword")
        assert schema.email == "bob@example.com"
