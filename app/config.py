from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://receipts:receipts@postgres:5432/receipts"
    REDIS_URL: str = "redis://redis:6379/0"
    GMAIL_CREDENTIALS_FILE: str = "/secrets/credentials.json"
    GMAIL_TOKEN_FILE: str = "/secrets/token.json"
    GMAIL_POLL_INTERVAL_SECONDS: int = 300
    DRIVE_ROOT_FOLDER: str = "Receipts"
    CONFIDENCE_THRESHOLD: float = 0.75
    RETENTION_DAYS_PROCESSED: int = 45
    RETENTION_DAYS_REVIEW: int = 90
    MAX_ATTACHMENT_SIZE_MB: int = 25

    # Google OAuth (required for web-based connect flow)
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/auth/google/callback"
    APP_SECRET_KEY: str = "change-me-in-production"

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
