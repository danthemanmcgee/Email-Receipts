"""Models for card statement imports and individual transaction lines."""
from datetime import datetime, date as date_type
from typing import Optional
from sqlalchemy import String, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


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

    statement: Mapped["CardStatement"] = relationship("CardStatement", back_populates="lines")
