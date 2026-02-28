"""Models for card statement imports and individual transaction lines."""
import enum
from datetime import datetime, date as date_type
from typing import Optional
from sqlalchemy import String, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class MatchStatus(str, enum.Enum):
    unmatched = "unmatched"
    matched = "matched"
    ignored = "ignored"


class CardStatement(Base):
    """A statement file uploaded for a specific physical card and user."""

    __tablename__ = "card_statements"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("physical_cards.id"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    format: Mapped[str] = mapped_column(String(10))  # "csv" or "ofx"
    row_count: Mapped[int]
    imported_at: Mapped[datetime] = mapped_column(default=func.now())

    lines: Mapped[list["StatementLine"]] = relationship(
        "StatementLine", back_populates="statement", cascade="all, delete-orphan"
    )


class StatementLine(Base):
    """A single transaction line from an imported card statement."""

    __tablename__ = "statement_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("card_statements.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("physical_cards.id"), index=True)
    txn_date: Mapped[date_type]
    amount: Mapped[float]
    merchant: Mapped[Optional[str]] = mapped_column(String(500))
    transaction_id: Mapped[Optional[str]] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    raw_data: Mapped[Optional[str]] = mapped_column(Text)
    match_status: Mapped[MatchStatus] = mapped_column(default=MatchStatus.unmatched)

    statement: Mapped["CardStatement"] = relationship("CardStatement", back_populates="lines")
    match: Mapped[Optional["StatementLineMatch"]] = relationship(
        "StatementLineMatch", back_populates="line", uselist=False, cascade="all, delete-orphan"
    )


class StatementLineMatch(Base):
    """Links a reconciled statement line to a receipt stored in Drive."""

    __tablename__ = "statement_line_matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_line_id: Mapped[int] = mapped_column(
        ForeignKey("statement_lines.id"), unique=True, index=True
    )
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    line: Mapped["StatementLine"] = relationship("StatementLine", back_populates="match")
    receipt: Mapped["Receipt"] = relationship("Receipt")


# Import Receipt for relationship resolution
from app.models.receipt import Receipt  # noqa: E402, F401
