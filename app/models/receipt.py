import enum
from datetime import datetime
from datetime import date as date_type
from typing import Optional
from sqlalchemy import String, Text, ForeignKey, UniqueConstraint, func
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
    __table_args__ = (
        UniqueConstraint("user_id", "content_hash", name="uq_receipt_user_content_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
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
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    # Timestamps
    processed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    # Relationships
    attachment_logs: Mapped[list["AttachmentLog"]] = relationship(
        "AttachmentLog", back_populates="receipt", cascade="all, delete-orphan"
    )
    gmail_links: Mapped[list["GmailReceiptLink"]] = relationship(
        "GmailReceiptLink", back_populates="receipt", cascade="all, delete-orphan"
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


class GmailReceiptLink(Base):
    """Links a Gmail message ID to a canonical Receipt.

    A single Receipt (identified by content_hash) may be referenced by multiple
    Gmail messages (e.g. forwarded duplicates).  Each row here records one such
    link so that every email pointing to the same document can be tracked without
    uploading duplicate files to Drive.
    """

    __tablename__ = "gmail_receipt_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"), index=True)
    gmail_message_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    receipt: Mapped["Receipt"] = relationship("Receipt", back_populates="gmail_links")


# Import PhysicalCard for relationship resolution
from app.models.card import PhysicalCard  # noqa: E402, F401
