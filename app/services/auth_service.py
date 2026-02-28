"""Authentication utilities: password hashing, session tokens, and FastAPI dependencies."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_TOKEN_EXPIRE_DAYS = 30


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the bcrypt *hashed* value."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT session tokens
# ---------------------------------------------------------------------------

def create_session_token(user_id: int) -> str:
    """Encode a signed JWT containing the user's id."""
    settings = get_settings()
    exp = datetime.now(tz=timezone.utc) + timedelta(days=_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": exp}
    return jwt.encode(payload, settings.APP_SECRET_KEY, algorithm=_ALGORITHM)


def decode_session_token(token: str) -> int:
    """Decode a JWT and return the user_id.  Raises jwt.PyJWTError on failure."""
    settings = get_settings()
    payload = jwt.decode(token, settings.APP_SECRET_KEY, algorithms=[_ALGORITHM])
    return int(payload["sub"])


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Return the authenticated User, or raise 401."""
    from app.models.user import User

    settings = get_settings()
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        user_id = decode_session_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def set_session_cookie(response, user_id: int) -> None:
    """Write the session JWT into an HttpOnly cookie on *response*."""
    settings = get_settings()
    token = create_session_token(user_id)
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="lax",
        max_age=_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


def clear_session_cookie(response) -> None:
    """Remove the session cookie from *response*."""
    settings = get_settings()
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="lax",
    )
