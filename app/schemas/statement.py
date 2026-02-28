"""Pydantic schemas for card statement imports and lines."""
from datetime import datetime, date as date_type
from typing import Optional, List
from pydantic import BaseModel


class StatementLineResponse(BaseModel):
    id: int
    statement_id: int
    user_id: int
    card_id: int
    txn_date: date_type
    amount: float
    merchant: Optional[str] = None
    transaction_id: Optional[str] = None
    currency: str

    model_config = {"from_attributes": True}


class CardStatementResponse(BaseModel):
    id: int
    user_id: int
    card_id: int
    filename: str
    format: str
    row_count: int
    imported_at: datetime
    lines: List[StatementLineResponse] = []

    model_config = {"from_attributes": True}
