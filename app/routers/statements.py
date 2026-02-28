"""Router for card statement imports (CSV and OFX/QFX).

Endpoints:
  POST /cards/{card_id}/statements/import  – Upload + parse a statement file
  GET  /cards/{card_id}/statements          – List imported statements for a card
  GET  /cards/{card_id}/statements/{stmt_id}/lines – List transaction lines
"""
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.card import PhysicalCard
from app.models.statement import CardStatement, StatementLine
from app.models.user import User
from app.schemas.statement import CardStatementResponse, StatementLineResponse
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


@router.post(
    "/{card_id}/statements/import",
    response_model=CardStatementResponse,
    status_code=201,
)
async def import_statement(
    card_id: int,
    file: UploadFile = File(...),
    column_map: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload and parse a card statement file (CSV or OFX/QFX).

    - **file**: CSV, OFX, or QFX file.
    - **column_map**: Optional JSON string mapping logical field names
      (``date``, ``amount``, ``merchant``, ``transaction_id``) to the actual
      CSV column header names.  Ignored for OFX/QFX files.

    All lines are validated before anything is written.  A single invalid line
    causes a full rollback (no partial imports).
    """
    from app.services.statement_service import parse_csv_statement, parse_ofx_statement

    _get_card_for_user(card_id, current_user.id, db)

    filename = file.filename or "statement"
    content_bytes = await file.read()

    # Detect format from extension or content type
    fname_lower = filename.lower()
    content_type = (file.content_type or "").lower()

    if fname_lower.endswith(".csv") or content_type in ("text/csv", "application/csv"):
        fmt = "csv"
    elif (
        fname_lower.endswith(".ofx")
        or fname_lower.endswith(".qfx")
        or "ofx" in content_type
    ):
        fmt = "ofx"
    else:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported file type for statement import: {filename!r}. "
                "Accepted formats: .csv, .ofx, .qfx"
            ),
        )

    # Decode file content
    try:
        content = content_bytes.decode("utf-8-sig")  # handle BOM
    except UnicodeDecodeError:
        try:
            content = content_bytes.decode("latin-1")
        except UnicodeDecodeError:
            raise HTTPException(status_code=422, detail="Could not decode file as text")

    # Parse column_map JSON if provided
    parsed_column_map: Optional[dict] = None
    if column_map:
        try:
            parsed_column_map = json.loads(column_map)
            if not isinstance(parsed_column_map, dict):
                raise ValueError("column_map must be a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid column_map JSON: {exc}"
            )

    # Parse and validate all rows BEFORE writing anything (full-rollback semantics)
    try:
        if fmt == "csv":
            rows = parse_csv_statement(content, parsed_column_map)
        else:
            rows = parse_ofx_statement(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # All rows valid → write to DB in a single transaction
    try:
        statement = CardStatement(
            user_id=current_user.id,
            card_id=card_id,
            filename=filename,
            format=fmt,
            row_count=len(rows),
        )
        db.add(statement)
        db.flush()  # populate statement.id without committing

        for row in rows:
            line = StatementLine(
                statement_id=statement.id,
                user_id=current_user.id,
                card_id=card_id,
                txn_date=row["date"],
                amount=row["amount"],
                merchant=row.get("merchant"),
                transaction_id=row.get("transaction_id"),
                currency=row.get("currency", "USD"),
                raw_data=None,
            )
            db.add(line)

        db.commit()
        db.refresh(statement)
    except Exception as exc:
        db.rollback()
        logger.error("DB error during statement import: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save imported statement")

    return statement


@router.get("/{card_id}/statements", response_model=List[CardStatementResponse])
def list_statements(
    card_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all imported statements for a card owned by the current user."""
    _get_card_for_user(card_id, current_user.id, db)
    return (
        db.query(CardStatement)
        .filter(
            CardStatement.card_id == card_id,
            CardStatement.user_id == current_user.id,
        )
        .order_by(CardStatement.imported_at.desc())
        .all()
    )


@router.get(
    "/{card_id}/statements/{stmt_id}/lines",
    response_model=List[StatementLineResponse],
)
def list_statement_lines(
    card_id: int,
    stmt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all transaction lines for a specific statement."""
    _get_card_for_user(card_id, current_user.id, db)
    statement = (
        db.query(CardStatement)
        .filter(
            CardStatement.id == stmt_id,
            CardStatement.card_id == card_id,
            CardStatement.user_id == current_user.id,
        )
        .first()
    )
    if not statement:
        raise HTTPException(status_code=404, detail="Statement not found")
    return statement.lines
