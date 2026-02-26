import base64
import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.services.gmail_service import GMAIL_ONLY_SCOPES, DRIVE_ONLY_SCOPES

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# State helpers (HMAC-signed to prevent CSRF)
# ---------------------------------------------------------------------------

def _make_state(connection_type: str) -> str:
    """Encode connection_type + nonce into a signed, base64-encoded state string."""
    settings = get_settings()
    nonce = secrets.token_hex(16)
    payload = json.dumps({"connection_type": connection_type, "nonce": nonce})
    sig = hmac.new(
        settings.APP_SECRET_KEY.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    state_data = json.dumps({"payload": payload, "sig": sig})
    return base64.urlsafe_b64encode(state_data.encode()).decode().rstrip("=")


def _verify_state(state: str) -> str:
    """Verify HMAC-signed state and return connection_type.  Raises HTTPException on failure."""
    try:
        # Restore base64 padding
        padding = 4 - len(state) % 4
        padded = state + "=" * (padding % 4)
        state_data = json.loads(base64.urlsafe_b64decode(padded).decode())
        payload: str = state_data["payload"]
        received_sig: str = state_data["sig"]
        settings = get_settings()
        expected_sig = hmac.new(
            settings.APP_SECRET_KEY.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(received_sig, expected_sig):
            raise ValueError("Signature mismatch")
        data = json.loads(payload)
        return data["connection_type"]
    except (KeyError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid or tampered OAuth state")


# ---------------------------------------------------------------------------
# OAuth flow helpers
# ---------------------------------------------------------------------------

def _build_flow(scopes: list):
    """Build a google_auth_oauthlib Flow from client config."""
    settings = get_settings()
    from google_auth_oauthlib.flow import Flow  # type: ignore

    client_config = {
        "web": {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_OAUTH_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=scopes)
    flow.redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
    return flow


def _get_account_email(access_token: str) -> Optional[str]:
    """Fetch the Google account email from the userinfo endpoint."""
    try:
        resp = httpx.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if resp.is_success:
            return resp.json().get("email")
    except Exception as exc:
        logger.warning("Could not retrieve account email: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/google/gmail/start")
def gmail_oauth_start():
    """Begin the Gmail OAuth flow."""
    settings = get_settings()
    if not settings.GOOGLE_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")
    state = _make_state("gmail")
    flow = _build_flow(GMAIL_ONLY_SCOPES)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes=False,
        prompt="consent",
        state=state,
    )
    return RedirectResponse(url=auth_url)


@router.get("/google/drive/start")
def drive_oauth_start():
    """Begin the Drive OAuth flow."""
    settings = get_settings()
    if not settings.GOOGLE_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")
    state = _make_state("drive")
    flow = _build_flow(DRIVE_ONLY_SCOPES)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes=False,
        prompt="consent",
        state=state,
    )
    return RedirectResponse(url=auth_url)


@router.get("/google/callback")
def google_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """Handle the OAuth callback for both gmail and drive connections."""
    connection_type = _verify_state(state)
    if connection_type not in ("gmail", "drive"):
        raise HTTPException(status_code=400, detail="Unknown connection type in state")

    scopes = GMAIL_ONLY_SCOPES if connection_type == "gmail" else DRIVE_ONLY_SCOPES

    try:
        flow = _build_flow(scopes)
        flow.fetch_token(code=code)
        creds = flow.credentials
    except Exception as exc:
        logger.error("OAuth token exchange failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {exc}")

    email = _get_account_email(creds.token)

    # Upsert the connection record
    from app.models.integration import GoogleConnection, ConnectionType

    conn_enum = ConnectionType(connection_type)
    conn = (
        db.query(GoogleConnection)
        .filter(GoogleConnection.connection_type == conn_enum)
        .first()
    )
    if conn is None:
        conn = GoogleConnection(connection_type=conn_enum)
        db.add(conn)

    conn.google_account_email = email
    conn.access_token = creds.token
    conn.refresh_token = creds.refresh_token
    conn.token_expiry = creds.expiry
    conn.scopes = ",".join(creds.scopes or scopes)
    conn.is_active = True
    conn.connected_at = datetime.utcnow()
    db.commit()

    logger.info("Saved %s connection for %s", connection_type, email)
    return RedirectResponse(url="/ui/settings")
