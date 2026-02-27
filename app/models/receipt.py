import enum
from datetime import datetime
from datetime import date as date_type
from typing import Optional
from sqlalchemy import String, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ReceiptStatus(str, enum.Enum):
    new = "new"
    processing = "processing"
    processed = "processed"
    needs_review = "needs_review"
    failed = "failed"
    ignored = "ignored"


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    gmail_message_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[ReceiptStatus] = mapped_column(default=ReceiptStatus.new)
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    sender: Mapped[Optional[str]] = mapped_column(String(255))
    received_at: Mapped[Optional[datetime]]
    # Extraction fields
    merchant: Mapped[Optional[str]] = mapped_column(String(255))
    purchase_date: Mapped[Optional[date_type]]
    amount: Mapped[Optional[float]]
    currency: Mapped[Optional[str]] = mapped_column(String(10), default="USD")
    card_last4_seen: Mapped[Optional[str]] = mapped_column(String(10))
    card_network_or_issuer: Mapped[Optional[str]] = mapped_column(String(50))
    source_type: Mapped[Optional[str]] = mapped_column(String(50))
    confidence: Mapped[Optional[float]]
    extraction_notes: Mapped[Optional[str]] = mapped_column(Text)
    # Card resolution
    physical_card_id: Mapped[Optional[int]] = mapped_column(ForeignKey("physical_cards.id"))
    # Drive output
    drive_file_id: Mapped[Optional[str]] = mapped_column(String(255))
    drive_path: Mapped[Optional[str]] = mapped_column(String(1000))
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    # Relationships
    attachment_logs: Mapped[list["AttachmentLog"]] = relationship(
        "AttachmentLog", back_populates="receipt", cascade="all, delete-orphan"
    )
    physical_card: Mapped[Optional["PhysicalCard"]] = relationship("PhysicalCard")


class AttachmentLog(Base):
    __tablename__ = "attachment_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"))
    filename: Mapped[str] = mapped_column(String(500))
    score: Mapped[int]
    decision: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    receipt: Mapped["Receipt"] = relationship("Receipt", back_populates="attachment_logs")


# Import PhysicalCard for relationship resolution
from app.models.card import PhysicalCard  # noqa: E402, F401
