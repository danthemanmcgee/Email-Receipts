from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.receipt import Receipt, ReceiptStatus
from app.schemas.receipt import ReceiptResponse, ReceiptListResponse, ReceiptUpdate

router = APIRouter()


@router.get("", response_model=ReceiptListResponse)
def list_receipts(
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(Receipt)
    if status:
        try:
            q = q.filter(Receipt.status == ReceiptStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    if date_from:
        from datetime import date
        q = q.filter(Receipt.purchase_date >= date.fromisoformat(date_from))
    if date_to:
        from datetime import date
        q = q.filter(Receipt.purchase_date <= date.fromisoformat(date_to))

    total = q.count()
    items = q.order_by(Receipt.created_at.desc()).offset(skip).limit(limit).all()
    return ReceiptListResponse(items=items, total=total)


@router.get("/{receipt_id}", response_model=ReceiptResponse)
def get_receipt(receipt_id: int, db: Session = Depends(get_db)):
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return receipt


@router.post("/{receipt_id}/reprocess")
def reprocess_receipt(receipt_id: int, db: Session = Depends(get_db)):
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    receipt.status = ReceiptStatus.new
    db.commit()
    try:
        from app.tasks.process_receipt import process_receipt_task
        task = process_receipt_task.delay(receipt.gmail_message_id)
        return {"status": "queued", "task_id": task.id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{receipt_id}/resolve-card")
def resolve_card_for_receipt(
    receipt_id: int,
    card_id: int,
    db: Session = Depends(get_db),
):
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    from app.models.card import PhysicalCard
    card = db.query(PhysicalCard).filter(PhysicalCard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    receipt.physical_card_id = card_id
    receipt.status = ReceiptStatus.processed
    db.commit()
    return {"status": "ok"}
