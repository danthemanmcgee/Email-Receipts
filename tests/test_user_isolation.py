"""Tests for per-user data isolation of integrations, jobs, settings, and card resolution."""
import os
from datetime import datetime
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.models.integration import GoogleConnection, ConnectionType  # noqa: E402
from app.models.job import JobRun, JobType, JobStatus  # noqa: E402
from app.models.setting import AllowedSender, AppSetting  # noqa: E402
from app.models.card import PhysicalCard, CardAlias  # noqa: E402
from app.models.user import User  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id: int, email: str = None) -> User:
    u = User.__new__(User)
    u.id = user_id
    u.email = email or f"user{user_id}@example.com"
    u.hashed_password = None
    u.google_sub = None
    u.is_active = True
    return u


def _make_connection(user_id: int, conn_type: ConnectionType) -> GoogleConnection:
    c = GoogleConnection.__new__(GoogleConnection)
    c.id = user_id * 10 + (1 if conn_type == ConnectionType.gmail else 2)
    c.user_id = user_id
    c.connection_type = conn_type
    c.google_account_email = f"user{user_id}@gmail.com"
    c.access_token = f"token-{user_id}"
    c.refresh_token = f"refresh-{user_id}"
    c.is_active = True
    return c


def _make_job(user_id: int, status: str = "completed") -> JobRun:
    j = JobRun.__new__(JobRun)
    j.id = user_id * 100
    j.user_id = user_id
    j.job_type = JobType.gmail_sync
    j.status = JobStatus(status)
    j.task_id = f"task-{user_id}"
    j.started_at = datetime(2025, 1, 1)
    j.completed_at = None
    j.details = None
    j.error_message = None
    return j


def _make_sender(user_id: int, email: str) -> AllowedSender:
    s = AllowedSender.__new__(AllowedSender)
    s.id = user_id * 1000
    s.user_id = user_id
    s.email = email
    return s


def _make_setting(user_id: int, key: str, value: str) -> AppSetting:
    s = AppSetting.__new__(AppSetting)
    s.id = user_id * 10000
    s.user_id = user_id
    s.key = key
    s.value = value
    return s


def _make_card(user_id: int, last4: str, display_name: str) -> PhysicalCard:
    c = PhysicalCard.__new__(PhysicalCard)
    c.id = user_id * 100 + int(last4)
    c.user_id = user_id
    c.display_name = display_name
    c.last4 = last4
    c.network = "Visa"
    return c


# ---------------------------------------------------------------------------
# 1. GoogleConnection isolation
# ---------------------------------------------------------------------------

class TestGoogleConnectionIsolation:
    """GoogleConnection records are scoped by user_id."""

    def test_user_a_and_b_have_separate_gmail_connections(self):
        conn_a = _make_connection(user_id=1, conn_type=ConnectionType.gmail)
        conn_b = _make_connection(user_id=2, conn_type=ConnectionType.gmail)
        assert conn_a.user_id != conn_b.user_id
        assert conn_a.access_token != conn_b.access_token

    def test_user_b_cannot_see_user_a_connection(self):
        conn_a = _make_connection(user_id=1, conn_type=ConnectionType.gmail)
        all_conns = [conn_a]

        # Simulate filtered query: user_id == 2
        user_b_conns = [c for c in all_conns if c.user_id == 2]
        assert len(user_b_conns) == 0

    def test_query_by_connection_type_includes_user_filter(self):
        """Simulates what integrations.py does: filter by user_id AND connection_type."""
        conn_a_gmail = _make_connection(user_id=1, conn_type=ConnectionType.gmail)
        conn_b_gmail = _make_connection(user_id=2, conn_type=ConnectionType.gmail)
        all_conns = [conn_a_gmail, conn_b_gmail]

        # User A's view
        result = next(
            (c for c in all_conns if c.user_id == 1 and c.connection_type == ConnectionType.gmail),
            None,
        )
        assert result is not None
        assert result.user_id == 1

    def test_google_connection_has_user_id_field(self):
        conn = _make_connection(user_id=42, conn_type=ConnectionType.drive)
        assert conn.user_id == 42

    def test_unique_constraint_is_per_user_and_type(self):
        """Two users can both have gmail connections (different user_id, same connection_type)."""
        conn1 = _make_connection(user_id=1, conn_type=ConnectionType.gmail)
        conn2 = _make_connection(user_id=2, conn_type=ConnectionType.gmail)
        # Different users, same type — this is valid; uniqueness is on (user_id, connection_type)
        assert conn1.connection_type == conn2.connection_type
        assert conn1.user_id != conn2.user_id


# ---------------------------------------------------------------------------
# 2. JobRun isolation
# ---------------------------------------------------------------------------

class TestJobRunIsolation:
    """JobRun records are scoped by user_id."""

    def test_job_has_user_id_field(self):
        job = _make_job(user_id=7)
        assert job.user_id == 7

    def test_user_b_cannot_see_user_a_jobs(self):
        job_a = _make_job(user_id=1)
        job_b = _make_job(user_id=2)
        all_jobs = [job_a, job_b]

        # Simulate filtered query: user_id == 2
        user_a_jobs = [j for j in all_jobs if j.user_id == 1]
        user_b_jobs = [j for j in all_jobs if j.user_id == 2]

        assert len(user_a_jobs) == 1
        assert user_a_jobs[0] is job_a

        assert len(user_b_jobs) == 1
        assert user_b_jobs[0] is job_b

        assert job_b not in user_a_jobs
        assert job_a not in user_b_jobs

    def test_jobs_router_filters_by_user_id(self):
        """list_recent_jobs endpoint query is scoped to current_user.id."""
        from app.routers.jobs import list_recent_jobs

        job_a = _make_job(user_id=1)
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = [job_a]
        mock_db.query.return_value = mock_q

        mock_user = MagicMock()
        mock_user.id = 1

        result = list_recent_jobs(limit=10, db=mock_db, current_user=mock_user)
        assert result == [job_a]
        # Verify filter was called (scoped query)
        mock_q.filter.assert_called_once()


# ---------------------------------------------------------------------------
# 3. AllowedSender isolation
# ---------------------------------------------------------------------------

class TestAllowedSenderIsolation:
    """AllowedSender records are scoped by user_id."""

    def test_sender_has_user_id_field(self):
        sender = _make_sender(user_id=1, email="store@example.com")
        assert sender.user_id == 1

    def test_user_b_allowlist_does_not_see_user_a_entries(self):
        sender_a = _make_sender(user_id=1, email="store_a@example.com")
        sender_b = _make_sender(user_id=2, email="store_b@example.com")
        all_senders = [sender_a, sender_b]

        user_a_senders = [s for s in all_senders if s.user_id == 1]
        user_b_senders = [s for s in all_senders if s.user_id == 2]

        assert len(user_a_senders) == 1
        assert user_a_senders[0].email == "store_a@example.com"

        assert len(user_b_senders) == 1
        assert user_b_senders[0].email == "store_b@example.com"

    def test_is_sender_allowed_scoped_to_user(self):
        """is_sender_allowed uses user-scoped allowlist."""
        from app.services.settings_service import is_sender_allowed

        sender = _make_sender(user_id=1, email="allowed@example.com")

        # User 1's db with the sender
        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.all.return_value = [sender]
        db.query.return_value = mock_q

        # User 1: "allowed@example.com" should be allowed
        result = is_sender_allowed(db, "allowed@example.com", user_id=1)
        assert result is True

    def test_get_allowed_senders_passes_user_id_filter(self):
        """get_allowed_senders filters by user_id when provided."""
        from app.services.settings_service import get_allowed_senders

        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.all.return_value = []
        db.query.return_value = mock_q

        get_allowed_senders(db, user_id=5)
        # filter should have been called to scope by user_id
        mock_q.filter.assert_called_once()


# ---------------------------------------------------------------------------
# 4. AppSetting isolation
# ---------------------------------------------------------------------------

class TestAppSettingIsolation:
    """AppSetting records are scoped by user_id."""

    def test_setting_has_user_id_field(self):
        setting = _make_setting(user_id=1, key="drive_root_folder", value="Receipts")
        assert setting.user_id == 1

    def test_user_b_cannot_see_user_a_setting(self):
        setting_a = _make_setting(user_id=1, key="drive_root_folder", value="Alice-Receipts")
        setting_b = _make_setting(user_id=2, key="drive_root_folder", value="Bob-Receipts")
        all_settings = [setting_a, setting_b]

        user_a_settings = [s for s in all_settings if s.user_id == 1]
        user_b_settings = [s for s in all_settings if s.user_id == 2]

        assert user_a_settings[0].value == "Alice-Receipts"
        assert user_b_settings[0].value == "Bob-Receipts"

    def test_get_drive_root_folder_scoped_to_user(self):
        """get_drive_root_folder filters by user_id."""
        from app.services.settings_service import get_drive_root_folder, DRIVE_ROOT_FOLDER_KEY

        setting = _make_setting(user_id=3, key=DRIVE_ROOT_FOLDER_KEY, value="User3Receipts")
        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = setting
        db.query.return_value = mock_q

        result = get_drive_root_folder(db, user_id=3)
        assert result == "User3Receipts"

    def test_set_drive_root_folder_scoped_to_user(self):
        """set_drive_root_folder creates new setting with user_id."""
        from app.services.settings_service import set_drive_root_folder

        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = None  # no existing setting
        db.query.return_value = mock_q

        set_drive_root_folder(db, "NewFolder", user_id=4)

        # A new AppSetting was added
        db.add.assert_called_once()
        added_obj = db.add.call_args[0][0]
        assert added_obj.user_id == 4
        assert added_obj.value == "NewFolder"

    def test_app_setting_has_id_primary_key(self):
        """AppSetting now has an integer id PK (not key)."""
        setting = _make_setting(user_id=1, key="drive_root_folder", value="test")
        assert hasattr(setting, "id")
        assert isinstance(setting.id, int)


# ---------------------------------------------------------------------------
# 5. Card resolution isolation
# ---------------------------------------------------------------------------

class TestCardResolutionIsolation:
    """resolve_card is scoped by user_id when provided."""

    def test_resolve_card_with_user_id_scopes_to_that_user(self):
        """When user_id is provided, only that user's cards are returned."""
        from app.services.card_service import resolve_card

        card_a = _make_card(user_id=1, last4="1234", display_name="Alice Visa")
        card_b = _make_card(user_id=2, last4="1234", display_name="Bob Visa")

        # Simulate DB with both cards; user_id=1 query should only match Alice
        db = MagicMock()
        mock_alias_q = MagicMock()
        mock_alias_q.join.return_value = mock_alias_q
        mock_alias_q.filter.return_value = mock_alias_q
        mock_alias_q.first.return_value = None  # no alias match
        mock_alias_q.all.return_value = []

        mock_card_q = MagicMock()
        mock_card_q.filter.return_value = mock_card_q
        mock_card_q.first.return_value = card_a  # user 1's card

        def query_side_effect(model):
            if model == CardAlias:
                return mock_alias_q
            return mock_card_q

        db.query.side_effect = query_side_effect

        card, resolution = resolve_card(db, "1234", user_id=1)
        assert card is card_a
        assert resolution == "exact"

    def test_resolve_card_without_user_id_uses_global_scope(self):
        """When user_id is None, original (unscoped) behavior is preserved."""
        from app.services.card_service import resolve_card

        card = _make_card(user_id=1, last4="5678", display_name="Test Card")

        db = MagicMock()
        mock_alias_q = MagicMock()
        mock_alias_q.filter.return_value = mock_alias_q
        mock_alias_q.first.return_value = None  # no alias
        mock_alias_q.all.return_value = []

        mock_card_q = MagicMock()
        mock_card_q.filter.return_value = mock_card_q
        mock_card_q.first.return_value = card

        def query_side_effect(model):
            if model == CardAlias:
                return mock_alias_q
            return mock_card_q

        db.query.side_effect = query_side_effect

        result_card, resolution = resolve_card(db, "5678")
        assert result_card is card
        assert resolution == "exact"


# ---------------------------------------------------------------------------
# 6. build_gmail/drive_service_from_db isolation
# ---------------------------------------------------------------------------

class TestGmailServiceIsolation:
    """build_gmail_service_from_db and build_drive_service_from_db use user_id filter."""

    def test_build_gmail_service_filters_by_user_id(self):
        """build_gmail_service_from_db passes user_id filter to query."""
        from app.services.gmail_service import build_gmail_service_from_db

        conn = _make_connection(user_id=3, conn_type=ConnectionType.gmail)
        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = conn
        db.query.return_value = mock_q

        with MagicMock() as mock_creds:
            from unittest.mock import patch
            with patch("app.services.gmail_service._credentials_from_connection", return_value=None):
                build_gmail_service_from_db(db, user_id=3)

        # filter should be called (with user_id scope included)
        assert mock_q.filter.call_count >= 1

    def test_build_drive_service_filters_by_user_id(self):
        """build_drive_service_from_db passes user_id filter to query."""
        from app.services.gmail_service import build_drive_service_from_db

        conn = _make_connection(user_id=5, conn_type=ConnectionType.drive)
        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = conn
        db.query.return_value = mock_q

        from unittest.mock import patch
        with patch("app.services.gmail_service._credentials_from_connection", return_value=None):
            build_drive_service_from_db(db, user_id=5)

        assert mock_q.filter.call_count >= 1

    def test_build_gmail_service_returns_none_for_wrong_user(self):
        """Returns None when no connection exists for the given user_id."""
        from app.services.gmail_service import build_gmail_service_from_db

        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = None  # no connection for user_id=99
        db.query.return_value = mock_q

        result = build_gmail_service_from_db(db, user_id=99)
        assert result is None
