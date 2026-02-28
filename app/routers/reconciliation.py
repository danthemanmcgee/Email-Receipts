"""Router for statement line reconciliation actions.

Endpoints:
  GET  /cards/{card_id}/statements/{stmt_id}/reconcile-data  – Reconciliation data + suggestions
  POST /statements/lines/{line_id}/match/{receipt_id}        – Link receipt to line
  DELETE /statements/lines/{line_id}/match                   – Unlink receipt from line
  PATCH /statements/lines/{line_id}/ignore                   – Toggle ignored status
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.card import PhysicalCard
from app.models.statement import CardStatement, StatementLine, StatementLineMatch, MatchStatus
from app.models.user import User
from app.services.auth_service import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_card_for_user(card_id: int, user_id: int, db: Session) -> PhysicalCard:
    """Return the card owned by user or raise 404."""
    card = (
        db.query(PhysicalCard)
        .filter(PhysicalCard.id == card_id, PhysicalCard.user_id == user_id)
        .first()
    )
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.get("/cards/{card_id}/statements/{stmt_id}/reconcile-data")
def get_reconcile_data(
    card_id: int,
    stmt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return reconciliation data for a statement.

    Each line includes its match_status, the linked receipt (if matched), and
    up to 5 suggested receipts (only those stored in Drive) for unmatched lines.
    """
    from app.models.receipt import Receipt
    from app.services.reconciliation_service import suggest_matches

    _get_card_for_user(card_id, current_user.id, db)
    statement = (
        db.query(CardStatement)
        .filter(
            CardStatement.id == stmt_id,
            CardStatement.card_id == card_id,
            CardStatement.user_id == current_user.id,
        )
        .options(
            selectinload(CardStatement.lines).selectinload(StatementLine.match).selectinload(
                StatementLineMatch.receipt
            )
        )
        .first()
    )
    if not statement:
        raise HTTPException(status_code=404, detail="Statement not found")

    all_receipts = (
        db.query(Receipt)
        .filter(
            Receipt.user_id == current_user.id,
            Receipt.drive_file_id.isnot(None),
        )
        .all()
    )

    result = []
    for line in statement.lines:
        entry: dict = {
            "id": line.id,
            "txn_date": line.txn_date.isoformat(),
            "amount": line.amount,
            "merchant": line.merchant,
            "transaction_id": line.transaction_id,
            "currency": line.currency,
            "match_status": line.match_status.value
            if isinstance(line.match_status, MatchStatus)
            else line.match_status,
            "matched_receipt": None,
            "suggestions": [],
        }
        if line.match and line.match.receipt:
            r = line.match.receipt
            entry["matched_receipt"] = {
                "id": r.id,
                "merchant": r.merchant,
                "amount": r.amount,
                "purchase_date": r.purchase_date.isoformat() if r.purchase_date else None,
                "drive_file_id": r.drive_file_id,
            }
        elif line.match_status != MatchStatus.ignored:
            suggestions = suggest_matches(line, all_receipts)
            entry["suggestions"] = [
                {
                    "id": r.id,
                    "merchant": r.merchant,
                    "amount": r.amount,
                    "purchase_date": r.purchase_date.isoformat() if r.purchase_date else None,
                    "drive_file_id": r.drive_file_id,
                    "score": score,
                }
                for r, score in suggestions
            ]
        result.append(entry)

    return result


@router.post("/statements/lines/{line_id}/match/{receipt_id}", status_code=200)
def link_receipt(
    line_id: int,
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Link a receipt to a statement line (manual or confirmed suggestion)."""
    from app.models.receipt import Receipt

    line = (
        db.query(StatementLine)
        .filter(StatementLine.id == line_id, StatementLine.user_id == current_user.id)
        .first()
    )
    if not line:
        raise HTTPException(status_code=404, detail="Statement line not found")

    receipt = (
        db.query(Receipt)
        .filter(
            Receipt.id == receipt_id,
            Receipt.user_id == current_user.id,
            Receipt.drive_file_id.isnot(None),
        )
        .first()
    )
    if not receipt:
        raise HTTPException(
            status_code=404,
            detail="Receipt not found or not stored in Drive",
        )

    if line.match:
        db.delete(line.match)
        db.flush()

    match = StatementLineMatch(
        statement_line_id=line.id,
        receipt_id=receipt.id,
        user_id=current_user.id,
    )
    db.add(match)
    line.match_status = MatchStatus.matched
    db.commit()
    return {"status": "matched", "line_id": line_id, "receipt_id": receipt_id}


@router.delete("/statements/lines/{line_id}/match", status_code=200)
def unlink_receipt(
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove the match link from a statement line and reset to unmatched."""
    line = (
        db.query(StatementLine)
        .filter(StatementLine.id == line_id, StatementLine.user_id == current_user.id)
        .options(selectinload(StatementLine.match))
        .first()
    )
    if not line:
        raise HTTPException(status_code=404, detail="Statement line not found")

    if line.match:
        db.delete(line.match)
    line.match_status = MatchStatus.unmatched
    db.commit()
    return {"status": "unmatched", "line_id": line_id}


@router.patch("/statements/lines/{line_id}/ignore", status_code=200)
def toggle_ignore(
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle ignored status on an unmatched line (ignored ↔ unmatched).

    Ignoring a matched line first unlinks the receipt then marks as ignored.
    """
    line = (
        db.query(StatementLine)
        .filter(StatementLine.id == line_id, StatementLine.user_id == current_user.id)
        .options(selectinload(StatementLine.match))
        .first()
    )
    if not line:
        raise HTTPException(status_code=404, detail="Statement line not found")

    current_status = (
        line.match_status.value
        if isinstance(line.match_status, MatchStatus)
        else line.match_status
    )

    if current_status == "ignored":
        line.match_status = MatchStatus.unmatched
        new_status = "unmatched"
    else:
        if line.match:
            db.delete(line.match)
            db.flush()
        line.match_status = MatchStatus.ignored
        new_status = "ignored"

    db.commit()
    return {"status": new_status, "line_id": line_id}
