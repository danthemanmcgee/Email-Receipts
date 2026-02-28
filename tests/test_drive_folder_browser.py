"""Tests for the Google Drive folder browser feature."""
from unittest.mock import MagicMock, patch

import pytest

from app.services.drive_service import ensure_drive_folder, upload_pdf_to_drive
from app.services.settings_service import (
    get_drive_root_folder_id,
    set_drive_root_folder_id,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_with_setting(key: str, value: str):
    """Return a mock DB that returns an AppSetting for the given key/value."""
    from app.models.setting import AppSetting

    setting = AppSetting.__new__(AppSetting)
    setting.key = key
    setting.value = value

    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value.first.return_value = setting
    db.query.return_value = mock_q
    return db


def _make_empty_db():
    """Return a mock DB where queries return None."""
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value.first.return_value = None
    db.query.return_value = mock_q
    return db


def _make_drive_service(folder_name="Receipts", folder_id="folder-id-root"):
    """Return a mock Drive API service that lists a single folder."""
    svc = MagicMock()
    svc.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": folder_id, "name": folder_name}]
    }
    svc.files.return_value.create.return_value.execute.return_value = {
        "id": "new-folder-id"
    }
    return svc


# ---------------------------------------------------------------------------
# settings_service – drive_root_folder_id
# ---------------------------------------------------------------------------

class TestDriveRootFolderIdSetting:
    def test_get_returns_empty_string_when_not_set(self):
        db = _make_empty_db()
        result = get_drive_root_folder_id(db)
        assert result == ""

    def test_get_returns_stored_id(self):
        db = _make_db_with_setting("drive_root_folder_id", "abc123")
        result = get_drive_root_folder_id(db)
        assert result == "abc123"

    def test_set_creates_new_setting(self):
        db = _make_empty_db()
        set_drive_root_folder_id(db, "new-folder-id")
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_set_updates_existing_setting(self):
        db = _make_db_with_setting("drive_root_folder_id", "old-id")
        set_drive_root_folder_id(db, "new-id")
        # Value should have been updated on the setting object
        setting = db.query().filter().first()
        assert setting.value == "new-id"
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# drive_service – ensure_drive_folder with root_folder_id
# ---------------------------------------------------------------------------

class TestEnsureDriveFolderWithRootId:
    def test_without_root_id_starts_from_drive_root(self):
        """When no root_folder_id is given, traversal starts from 'root'."""
        svc = _make_drive_service("Receipts", "receipts-folder-id")
        # Override create to also return an id for new folders
        svc.files.return_value.create.return_value.execute.return_value = {"id": "new-id"}

        folder_id = ensure_drive_folder(svc, "Receipts/Chase/2024/2024-01")

        # The first list call should search under 'root'
        first_call_args = svc.files.return_value.list.call_args_list[0]
        query_arg = first_call_args[1]["q"]
        assert "'root' in parents" in query_arg

    def test_with_root_id_skips_first_segment(self):
        """When root_folder_id is set, traversal starts inside that folder."""
        svc = _make_drive_service("Chase", "chase-folder-id")
        svc.files.return_value.create.return_value.execute.return_value = {"id": "new-id"}

        folder_id = ensure_drive_folder(
            svc, "Receipts/Chase/2024/2024-01", root_folder_id="receipts-id"
        )

        # The first list call should search under the provided root_folder_id
        first_call_args = svc.files.return_value.list.call_args_list[0]
        query_arg = first_call_args[1]["q"]
        assert "'receipts-id' in parents" in query_arg
        # "root" should NOT be the starting parent
        assert "'root' in parents" not in query_arg

    def test_single_segment_path_with_root_id_returns_root_id_directly(self):
        """A path like 'Receipts' with root_folder_id means no sub-traversal needed."""
        svc = MagicMock()
        # Should not call files().list() at all since parts is empty after skip
        folder_id = ensure_drive_folder(svc, "Receipts", root_folder_id="receipts-id")
        assert folder_id == "receipts-id"
        svc.files.return_value.list.assert_not_called()


# ---------------------------------------------------------------------------
# drive_service – upload_pdf_to_drive passes root_folder_id
# ---------------------------------------------------------------------------

class TestUploadPdfRootFolderIdPropagation:
    def test_root_folder_id_passed_to_ensure_drive_folder(self):
        """upload_pdf_to_drive forwards root_folder_id to ensure_drive_folder."""
        with patch("app.services.drive_service.ensure_drive_folder", return_value="leaf-id") as mock_ensure:
            with patch("app.services.drive_service.validate_drive_folder_id", return_value=(True, "ok")):
                svc = MagicMock()
                svc.files.return_value.list.return_value.execute.return_value = {"files": []}
                svc.files.return_value.create.return_value.execute.return_value = {"id": "file-id"}

                from googleapiclient.http import MediaIoBaseUpload  # ensure importable
                with patch("googleapiclient.http.MediaIoBaseUpload"):
                    upload_pdf_to_drive(
                        svc, b"%PDF-1", "Receipts/Chase/2024/2024-01", "receipt.pdf",
                        root_folder_id="receipts-folder-id",
                    )

            mock_ensure.assert_called_once_with(svc, "Receipts/Chase/2024/2024-01", "receipts-folder-id")

    def test_no_root_folder_id_calls_ensure_without_id(self):
        """upload_pdf_to_drive with no root_folder_id passes None to ensure_drive_folder."""
        with patch("app.services.drive_service.ensure_drive_folder", return_value="leaf-id") as mock_ensure:
            svc = MagicMock()
            svc.files.return_value.list.return_value.execute.return_value = {"files": []}
            svc.files.return_value.create.return_value.execute.return_value = {"id": "file-id"}

            with patch("googleapiclient.http.MediaIoBaseUpload"):
                upload_pdf_to_drive(
                    svc, b"%PDF-1", "Receipts/Chase/2024/2024-01", "receipt.pdf",
                )

            mock_ensure.assert_called_once_with(svc, "Receipts/Chase/2024/2024-01", None)


# ---------------------------------------------------------------------------
# settings_router – list_drive_folders endpoint
# ---------------------------------------------------------------------------

class TestListDriveFoldersEndpoint:
    def test_list_drive_folders_returns_folder_list(self):
        """list_drive_folders returns folders from Drive API."""
        from app.routers.settings_router import list_drive_folders

        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "id1", "name": "Alpha"},
                {"id": "id2", "name": "Beta"},
            ]
        }

        db = MagicMock()

        with patch("app.services.gmail_service.build_drive_service_from_db", return_value=svc):
            from fastapi import HTTPException
            mock_user = MagicMock()
            mock_user.id = 1
            result = list_drive_folders(parent_id="root", db=db, current_user=mock_user)

        assert len(result.folders) == 2
        assert result.folders[0].name == "Alpha"
        assert result.folders[0].id == "id1"
        assert result.parent_id == "root"

    def test_list_drive_folders_raises_503_when_not_connected(self):
        """list_drive_folders raises 503 when Drive is not connected."""
        from app.routers.settings_router import list_drive_folders
        from fastapi import HTTPException

        db = MagicMock()

        with patch("app.services.gmail_service.build_drive_service_from_db", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                mock_user = MagicMock()
                mock_user.id = 1
                list_drive_folders(parent_id="root", db=db, current_user=mock_user)

        assert exc_info.value.status_code == 503

    def test_list_drive_folders_raises_502_on_api_error(self):
        """list_drive_folders raises 502 when Drive API call fails."""
        from app.routers.settings_router import list_drive_folders
        from fastapi import HTTPException

        svc = MagicMock()
        svc.files.return_value.list.side_effect = Exception("API error")

        db = MagicMock()

        with patch("app.services.gmail_service.build_drive_service_from_db", return_value=svc):
            with pytest.raises(HTTPException) as exc_info:
                mock_user = MagicMock()
                mock_user.id = 1
                list_drive_folders(parent_id="root", db=db, current_user=mock_user)

        assert exc_info.value.status_code == 502

    def test_list_drive_folders_uses_custom_parent_id(self):
        """list_drive_folders queries Drive with the provided parent_id."""
        from app.routers.settings_router import list_drive_folders

        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {"files": []}

        db = MagicMock()

        with patch("app.services.gmail_service.build_drive_service_from_db", return_value=svc):
            mock_user = MagicMock()
            mock_user.id = 1
            result = list_drive_folders(parent_id="custom-parent-id", db=db, current_user=mock_user)

        assert result.parent_id == "custom-parent-id"
        query_kwarg = svc.files.return_value.list.call_args[1]["q"]
        assert "'custom-parent-id' in parents" in query_kwarg


# ---------------------------------------------------------------------------
# settings_router – get_drive_access_token endpoint
# ---------------------------------------------------------------------------

class TestGetDriveAccessTokenEndpoint:
    def test_returns_access_token_when_connected(self):
        """get_drive_access_token returns the token for a connected Drive account."""
        from app.routers.settings_router import get_drive_access_token
        from app.models.integration import GoogleConnection, ConnectionType
        from datetime import datetime

        conn = GoogleConnection.__new__(GoogleConnection)
        conn.connection_type = ConnectionType.drive
        conn.access_token = "test-access-token"
        conn.refresh_token = "test-refresh-token"
        conn.token_expiry = datetime(2099, 1, 1)
        conn.scopes = "https://www.googleapis.com/auth/drive.file"
        conn.is_active = True

        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = conn
        db.query.return_value = mock_q

        with patch("app.services.gmail_service._credentials_from_connection", return_value=None):
            mock_user = MagicMock()
            mock_user.id = 1
            result = get_drive_access_token(db=db, current_user=mock_user)

        assert result.access_token == "test-access-token"

    def test_raises_503_when_not_connected(self):
        """get_drive_access_token raises 503 when Drive is not connected."""
        from app.routers.settings_router import get_drive_access_token
        from fastapi import HTTPException

        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = None
        db.query.return_value = mock_q

        mock_user = MagicMock()
        mock_user.id = 1
        with pytest.raises(HTTPException) as exc_info:
            get_drive_access_token(db=db, current_user=mock_user)

        assert exc_info.value.status_code == 503

    def test_raises_503_when_token_missing(self):
        """get_drive_access_token raises 503 when connection exists but has no access_token."""
        from app.routers.settings_router import get_drive_access_token
        from app.models.integration import GoogleConnection, ConnectionType
        from fastapi import HTTPException

        conn = GoogleConnection.__new__(GoogleConnection)
        conn.connection_type = ConnectionType.drive
        conn.access_token = None
        conn.refresh_token = "test-refresh-token"
        conn.is_active = True

        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = conn
        db.query.return_value = mock_q

        mock_user = MagicMock()
        mock_user.id = 1
        with pytest.raises(HTTPException) as exc_info:
            get_drive_access_token(db=db, current_user=mock_user)

        assert exc_info.value.status_code == 503

    def test_refreshes_token_before_returning(self):
        """get_drive_access_token calls _refresh_and_persist when credentials are valid."""
        from app.routers.settings_router import get_drive_access_token
        from app.models.integration import GoogleConnection, ConnectionType
        from datetime import datetime

        conn = GoogleConnection.__new__(GoogleConnection)
        conn.connection_type = ConnectionType.drive
        conn.access_token = "old-token"
        conn.refresh_token = "refresh-token"
        conn.token_expiry = datetime(2099, 1, 1)
        conn.scopes = "https://www.googleapis.com/auth/drive.file"
        conn.is_active = True

        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = conn
        db.query.return_value = mock_q

        mock_creds = MagicMock()

        with patch("app.services.gmail_service._credentials_from_connection", return_value=mock_creds):
            with patch("app.services.gmail_service._refresh_and_persist") as mock_refresh:
                mock_user = MagicMock()
                mock_user.id = 1
                result = get_drive_access_token(db=db, current_user=mock_user)

        mock_refresh.assert_called_once_with(mock_creds, conn, db)
        assert result.access_token == "old-token"
