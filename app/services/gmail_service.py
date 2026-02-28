import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Legacy combined scopes (file-based credential helpers use these)
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive.file",
]

# Separate scope sets for distinct connections
GMAIL_ONLY_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

DRIVE_ONLY_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

LABEL_MAP = {
    "new": "receipt/new",
    "processed": "receipt/processed",
    "needs_review": "receipt/needs-review",
    "failed": "receipt/failed",
}


def _load_credentials(credentials_file: str, token_file: str):
    """Load or refresh OAuth2 credentials."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request

        creds = None
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, GMAIL_SCOPES)

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, "w") as f:
                f.write(creds.to_json())
            return creds

        if os.path.exists(credentials_file):
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
            with open(token_file, "w") as f:
                f.write(creds.to_json())
            return creds

        logger.warning("No Gmail credentials found at %s", credentials_file)
        return None
    except Exception as exc:
        logger.error("Failed to load Gmail credentials: %s", exc)
        return None


def build_gmail_service(credentials_file: str, token_file: str):
    """Build the Gmail API service client."""
    creds = _load_credentials(credentials_file, token_file)
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build

        return build("gmail", "v1", credentials=creds)
    except Exception as exc:
        logger.error("Failed to build Gmail service: %s", exc)
        return None


def build_drive_service(credentials_file: str, token_file: str):
    """Build the Drive API service client."""
    creds = _load_credentials(credentials_file, token_file)
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build

        return build("drive", "v3", credentials=creds)
    except Exception as exc:
        logger.error("Failed to build Drive service: %s", exc)
        return None


def list_new_messages(service, max_results: int = 50) -> list[dict]:
    """List messages with label receipt/new or unread in inbox."""
    if not service:
        return []
    try:
        query = "label:receipt/new OR (label:inbox is:unread)"
        result = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        return result.get("messages", [])
    except Exception as exc:
        logger.error("Failed to list Gmail messages: %s", exc)
        return []


def get_message_detail(service, message_id: str) -> Optional[dict]:
    """Get full message details including attachments."""
    if not service:
        return None
    try:
        return (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to get Gmail message %s: %s", message_id, exc)
        return None


def get_attachment_bytes(service, message_id: str, attachment_id: str) -> Optional[bytes]:
    """Download attachment bytes."""
    if not service:
        return None
    try:
        import base64

        result = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        data = result.get("data", "")
        return base64.urlsafe_b64decode(data)
    except Exception as exc:
        logger.error("Failed to get attachment: %s", exc)
        return None


def apply_label(service, message_id: str, label_name: str) -> bool:
    """Apply a Gmail label to a message."""
    if not service:
        return False
    try:
        # Get or create label (idempotent: handle 409 conflicts)
        labels = service.users().labels().list(userId="me").execute().get("labels", [])
        label_id = next((l["id"] for l in labels if l["name"] == label_name), None)
        if not label_id:
            try:
                new_label = (
                    service.users()
                    .labels()
                    .create(userId="me", body={"name": label_name})
                    .execute()
                )
                label_id = new_label["id"]
            except Exception as create_exc:
                # 409 Conflict means the label already exists (race condition or
                # nested label created outside this flow). Re-fetch to get the ID.
                _status = getattr(getattr(create_exc, "resp", None), "status", None)
                if _status == 409 or "409" in str(create_exc):
                    labels = (
                        service.users().labels().list(userId="me").execute().get("labels", [])
                    )
                    label_id = next(
                        (l["id"] for l in labels if l["name"] == label_name), None
                    )
                else:
                    raise
        if not label_id:
            logger.warning("Could not obtain label ID for %s; skipping apply", label_name)
            return False

        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()
        return True
    except Exception as exc:
        logger.error("Failed to apply label %s to %s: %s", label_name, message_id, exc)
        return False


def archive_message(service, message_id: str) -> bool:
    """Archive a Gmail message by removing the INBOX label."""
    if not service:
        return False
    try:
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["INBOX"]},
        ).execute()
        return True
    except Exception as exc:
        logger.error("Failed to archive message %s: %s", message_id, exc)
        return False


def extract_attachments_from_message(message: dict) -> list[dict]:
    """Extract PDF attachment metadata from a Gmail message payload."""
    attachments = []
    payload = message.get("payload", {})
    parts = payload.get("parts", [])
    if not parts:
        parts = [payload]

    def walk_parts(parts_list):
        for part in parts_list:
            mime = part.get("mimeType", "")
            filename = part.get("filename", "")
            body = part.get("body", {})
            attachment_id = body.get("attachmentId")
            if filename and mime in ("application/pdf", "application/octet-stream") and attachment_id:
                attachments.append({
                    "filename": filename,
                    "attachment_id": attachment_id,
                    "size": body.get("size", 0),
                })
            sub_parts = part.get("parts", [])
            if sub_parts:
                walk_parts(sub_parts)

    walk_parts(parts)
    return attachments


def extract_body_text(message: dict) -> str:
    """Extract plain text body from Gmail message."""
    import base64

    payload = message.get("payload", {})
    parts = payload.get("parts", [])
    if not parts:
        parts = [payload]

    def walk_parts(parts_list):
        for part in parts_list:
            mime = part.get("mimeType", "")
            body = part.get("body", {})
            data = body.get("data", "")
            if mime == "text/plain" and data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            sub_parts = part.get("parts", [])
            if sub_parts:
                result = walk_parts(sub_parts)
                if result:
                    return result
        return ""

    return walk_parts(parts)


def _credentials_from_connection(conn) -> Optional[object]:
    """Build a google.oauth2.credentials.Credentials from a GoogleConnection record."""
    from app.config import get_settings
    settings = get_settings()
    try:
        from google.oauth2.credentials import Credentials

        scopes = conn.scopes.split(",") if conn.scopes else None
        return Credentials(
            token=conn.access_token,
            refresh_token=conn.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
            scopes=scopes,
            expiry=conn.token_expiry,
        )
    except Exception as exc:
        logger.error("Failed to build credentials from connection: %s", exc)
        return None


def _refresh_and_persist(creds, conn, db) -> None:
    """Refresh expired credentials and persist updated tokens to DB."""
    try:
        from google.auth.transport.requests import Request

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            conn.access_token = creds.token
            conn.token_expiry = creds.expiry
            db.commit()
    except Exception as exc:
        logger.warning("Token refresh failed: %s", exc)


def build_gmail_service_from_db(db, user_id: Optional[int] = None):
    """Build Gmail API service using the stored gmail connection tokens.

    Returns None if no active Gmail connection exists for the given user.
    """
    from app.models.integration import GoogleConnection, ConnectionType

    q = db.query(GoogleConnection).filter(
        GoogleConnection.connection_type == ConnectionType.gmail,
        GoogleConnection.is_active.is_(True),
    )
    if user_id is not None:
        q = q.filter(GoogleConnection.user_id == user_id)
    conn = q.first()

    if conn and conn.refresh_token:
        creds = _credentials_from_connection(conn)
        if creds:
            _refresh_and_persist(creds, conn, db)
            try:
                from googleapiclient.discovery import build as google_build

                return google_build("gmail", "v1", credentials=creds)
            except Exception as exc:
                logger.error("Failed to build Gmail service from DB credentials: %s", exc)
                return None

    return None


def build_drive_service_from_db(db, user_id: Optional[int] = None):
    """Build Drive API service using the stored drive connection tokens.

    Returns None if no active Drive connection exists for the given user.
    """
    from app.models.integration import GoogleConnection, ConnectionType

    q = db.query(GoogleConnection).filter(
        GoogleConnection.connection_type == ConnectionType.drive,
        GoogleConnection.is_active.is_(True),
    )
    if user_id is not None:
        q = q.filter(GoogleConnection.user_id == user_id)
    conn = q.first()

    if conn and conn.refresh_token:
        creds = _credentials_from_connection(conn)
        if creds:
            _refresh_and_persist(creds, conn, db)
            try:
                from googleapiclient.discovery import build as google_build

                return google_build("drive", "v3", credentials=creds)
            except Exception as exc:
                logger.error("Failed to build Drive service from DB credentials: %s", exc)
                return None

    return None

