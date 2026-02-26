from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel
from app.models.receipt import ReceiptStatus


class AttachmentLogSchema(BaseModel):
    id: int
    filename: str
    score: int
    decision: str
    reason: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ReceiptBase(BaseModel):
    subject: Optional[str] = None
    sender: Optional[str] = None
    merchant: Optional[str] = None
    purchase_date: Optional[date] = None
    amount: Optional[float] = None
    currency: Optional[str] = "USD"
    card_last4_seen: Optional[str] = None


class ReceiptCreate(ReceiptBase):
    gmail_message_id: str


class ReceiptUpdate(ReceiptBase):
    status: Optional[ReceiptStatus] = None
    physical_card_id: Optional[int] = None


class ReceiptResponse(ReceiptBase):
    id: int
    gmail_message_id: str
    status: ReceiptStatus
    received_at: Optional[datetime] = None
    card_network_or_issuer: Optional[str] = None
    source_type: Optional[str] = None
    confidence: Optional[float] = None
    extraction_notes: Optional[str] = None
    physical_card_id: Optional[int] = None
    drive_file_id: Optional[str] = None
    drive_path: Optional[str] = None
    content_hash: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    attachment_logs: List[AttachmentLogSchema] = []

    model_config = {"from_attributes": True}


class ReceiptListResponse(BaseModel):
    items: List[ReceiptResponse]
    total: int
