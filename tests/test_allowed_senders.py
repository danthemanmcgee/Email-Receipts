"""Tests for allowed-sender filtering and drive-folder setting."""
from unittest.mock import MagicMock

import pytest

from app.services.settings_service import (
    _extract_email,
    get_allowed_senders,
    is_sender_allowed,
    get_drive_root_folder,
    set_drive_root_folder,
    DRIVE_ROOT_FOLDER_KEY,
)
from app.models.setting import AllowedSender, AppSetting


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_allowed_sender(email: str) -> AllowedSender:
    s = AllowedSender.__new__(AllowedSender)
    s.id = 1
    s.email = email
    return s


def _make_app_setting(key: str, value: str) -> AppSetting:
    s = AppSetting.__new__(AppSetting)
    s.key = key
    s.value = value
    return s


def _make_db_with_senders(*emails):
    """Return a mock DB that returns AllowedSender rows for given emails."""
    rows = [_make_allowed_sender(e) for e in emails]
    db = MagicMock()
    db.query.return_value.all.return_value = rows
    return db


def _make_db_with_setting(key: str, value: str):
    setting = _make_app_setting(key, value)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = setting
    return db


def _make_db_no_setting():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


# ---------------------------------------------------------------------------
# _extract_email
# ---------------------------------------------------------------------------

class TestExtractEmail:
    def test_bare_email(self):
        assert _extract_email("foo@example.com") == "foo@example.com"

    def test_name_and_angle_bracket(self):
        assert _extract_email("Store Name <store@example.com>") == "store@example.com"

    def test_lowercases_result(self):
        assert _extract_email("STORE@EXAMPLE.COM") == "store@example.com"

    def test_angle_bracket_lowercased(self):
        assert _extract_email("Store <STORE@EXAMPLE.COM>") == "store@example.com"

    def test_whitespace_stripped(self):
        assert _extract_email("  foo@bar.com  ") == "foo@bar.com"


# ---------------------------------------------------------------------------
# get_allowed_senders
# ---------------------------------------------------------------------------

class TestGetAllowedSenders:
    def test_empty_list(self):
        db = _make_db_with_senders()
        assert get_allowed_senders(db) == []

    def test_returns_lowercase_emails(self):
        db = _make_db_with_senders("A@example.com", "B@example.com")
        result = get_allowed_senders(db)
        assert "a@example.com" in result
        assert "b@example.com" in result

    def test_returns_all_configured_senders(self):
        emails = ["a@a.com", "b@b.com", "c@c.com"]
        db = _make_db_with_senders(*emails)
        result = get_allowed_senders(db)
        assert sorted(result) == sorted(emails)


# ---------------------------------------------------------------------------
# is_sender_allowed
# ---------------------------------------------------------------------------

class TestIsSenderAllowed:
    def test_empty_allowlist_allows_any_sender(self):
        db = _make_db_with_senders()
        assert is_sender_allowed(db, "anyone@anywhere.com") is True

    def test_sender_in_list_is_allowed(self):
        db = _make_db_with_senders("receipts@store.com")
        assert is_sender_allowed(db, "receipts@store.com") is True

    def test_sender_not_in_list_is_rejected(self):
        db = _make_db_with_senders("allowed@store.com")
        assert is_sender_allowed(db, "spam@unknown.com") is False

    def test_display_name_format_is_parsed(self):
        db = _make_db_with_senders("store@receipts.com")
        assert is_sender_allowed(db, "Big Store <store@receipts.com>") is True

    def test_case_insensitive_match(self):
        db = _make_db_with_senders("store@receipts.com")
        assert is_sender_allowed(db, "STORE@RECEIPTS.COM") is True

    def test_multiple_allowed_senders_match_any(self):
        db = _make_db_with_senders("a@a.com", "b@b.com")
        assert is_sender_allowed(db, "a@a.com") is True
        # Re-use the mock to test second match
        db2 = _make_db_with_senders("a@a.com", "b@b.com")
        assert is_sender_allowed(db2, "b@b.com") is True


# ---------------------------------------------------------------------------
# get_drive_root_folder
# ---------------------------------------------------------------------------

class TestGetDriveRootFolder:
    def test_returns_db_value_when_set(self):
        db = _make_db_with_setting(DRIVE_ROOT_FOLDER_KEY, "MyReceipts")
        result = get_drive_root_folder(db)
        assert result == "MyReceipts"

    def test_falls_back_to_config_default_when_no_db_row(self):
        from unittest.mock import patch
        db = _make_db_no_setting()
        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value.DRIVE_ROOT_FOLDER = "Receipts"
            result = get_drive_root_folder(db)
        assert result == "Receipts"

    def test_falls_back_when_db_value_is_empty_string(self):
        from unittest.mock import patch
        db = _make_db_with_setting(DRIVE_ROOT_FOLDER_KEY, "")
        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value.DRIVE_ROOT_FOLDER = "Receipts"
            result = get_drive_root_folder(db)
        assert result == "Receipts"


# ---------------------------------------------------------------------------
# archive_message (gmail_service)
# ---------------------------------------------------------------------------

class TestArchiveMessage:
    def test_archive_removes_inbox_label(self):
        from app.services.gmail_service import archive_message

        service = MagicMock()
        result = archive_message(service, "msg123")

        assert result is True
        service.users().messages().modify.assert_called_once_with(
            userId="me",
            id="msg123",
            body={"removeLabelIds": ["INBOX"]},
        )

    def test_archive_returns_false_when_service_is_none(self):
        from app.services.gmail_service import archive_message

        assert archive_message(None, "msg123") is False

    def test_archive_returns_false_on_api_error(self):
        from app.services.gmail_service import archive_message

        service = MagicMock()
        service.users().messages().modify.return_value.execute.side_effect = Exception(
            "API error"
        )
        result = archive_message(service, "msg123")
        assert result is False
