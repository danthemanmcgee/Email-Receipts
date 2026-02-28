"""Reconciliation service: match statement lines to receipts.

Scoring strategy (each component contributes to a 0.0–1.0 score):
- Amount:   exact ±0   → 0.50, within 1 % → 0.40, within 5 % → 0.25
- Date:     same day   → 0.30, within 3 d → 0.20, within 7 d → 0.10
- Merchant: normalised substring match → 0.20
- Card:     same card_id                → 0.10 (bonus)

A receipt must score ≥ 0.50 to be returned as a suggestion.
Only receipts with a drive_file_id (stored in Drive) are eligible.
"""
from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.statement import StatementLine
    from app.models.receipt import Receipt

_SCORE_THRESHOLD = 0.50


def _normalise(text: str | None) -> str:
    """Lower-case, strip punctuation/extra spaces for fuzzy merchant matching."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _amount_score(line_amount: float, receipt_amount: float | None) -> float:
    if receipt_amount is None:
        return 0.0
    # Use absolute values (statement debits are often negative)
    la, ra = abs(line_amount), abs(receipt_amount)
    if la == 0 and ra == 0:
        return 0.50
    if la == 0 or ra == 0:
        return 0.0
    diff_pct = abs(la - ra) / max(la, ra)
    if diff_pct == 0:
        return 0.50
    if diff_pct <= 0.01:
        return 0.40
    if diff_pct <= 0.05:
        return 0.25
    return 0.0


def _date_score(line_date: date, receipt_date: date | None) -> float:
    if receipt_date is None:
        return 0.0
    delta = abs((line_date - receipt_date).days)
    if delta == 0:
        return 0.30
    if delta <= 3:
        return 0.20
    if delta <= 7:
        return 0.10
    return 0.0


def _merchant_score(line_merchant: str | None, receipt_merchant: str | None) -> float:
    lm = _normalise(line_merchant)
    rm = _normalise(receipt_merchant)
    if not lm or not rm:
        return 0.0
    if lm == rm:
        return 0.20
    if lm in rm or rm in lm:
        return 0.15
    # Check first significant word
    lm_words = lm.split()
    rm_words = rm.split()
    if lm_words and rm_words and lm_words[0] == rm_words[0]:
        return 0.10
    return 0.0


def _card_score(line_card_id: int, receipt_card_id: int | None) -> float:
    if receipt_card_id is None:
        return 0.0
    return 0.10 if line_card_id == receipt_card_id else 0.0


def score_receipt(line: "StatementLine", receipt: "Receipt") -> float:
    """Return a match score in [0, 1] for (line, receipt) pair."""
    return (
        _amount_score(line.amount, receipt.amount)
        + _date_score(line.txn_date, receipt.purchase_date)
        + _merchant_score(line.merchant, receipt.merchant)
        + _card_score(line.card_id, receipt.physical_card_id)
    )


def suggest_matches(
    line: "StatementLine",
    receipts: list["Receipt"],
    *,
    threshold: float = _SCORE_THRESHOLD,
    limit: int = 5,
) -> list[tuple["Receipt", float]]:
    """Return up to *limit* receipts that score above *threshold*, sorted by score desc.

    Only receipts with a ``drive_file_id`` are considered.
    """
    scored = []
    for receipt in receipts:
        if not receipt.drive_file_id:
            continue
        s = score_receipt(line, receipt)
        if s >= threshold:
            scored.append((receipt, round(s, 3)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]
