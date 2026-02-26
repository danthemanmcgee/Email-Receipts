import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ConnectionType(str, enum.Enum):
    gmail = "gmail"
    drive = "drive"


class GoogleConnection(Base):
    __tablename__ = "google_connections"
    __table_args__ = (
        UniqueConstraint("connection_type", name="uq_google_connections_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_type: Mapped[ConnectionType] = mapped_column(String(20))
    google_account_email: Mapped[Optional[str]] = mapped_column(String(255))
    access_token: Mapped[Optional[str]] = mapped_column(Text)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text)
    token_expiry: Mapped[Optional[datetime]]
    scopes: Mapped[Optional[str]] = mapped_column(String(500))  # comma-separated
    is_active: Mapped[bool] = mapped_column(default=True)
    connected_at: Mapped[Optional[datetime]]
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())
