from datetime import datetime
from typing import Optional
from sqlalchemy import String, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class PhysicalCard(Base):
    __tablename__ = "physical_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), unique=True)
    last4: Mapped[Optional[str]] = mapped_column(String(10))
    network: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    aliases: Mapped[list["CardAlias"]] = relationship(
        "CardAlias", back_populates="physical_card", cascade="all, delete-orphan"
    )


class CardAlias(Base):
    __tablename__ = "card_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    physical_card_id: Mapped[int] = mapped_column(ForeignKey("physical_cards.id"))
    alias_last4: Mapped[str] = mapped_column(String(10))
    alias_pattern: Mapped[Optional[str]] = mapped_column(String(100))
    notes: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    physical_card: Mapped["PhysicalCard"] = relationship("PhysicalCard", back_populates="aliases")
