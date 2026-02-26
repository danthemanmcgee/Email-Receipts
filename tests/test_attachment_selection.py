import pytest
from app.services.attachment_service import score_pdf, select_best_pdf, normalize_filename


def test_normalize_filename():
    assert normalize_filename("Receipt_2024-01.pdf") == "receipt 2024 01"
    assert normalize_filename("invoice_statement.PDF") == "invoice statement"


def test_score_receipt():
    s = score_pdf("receipt.pdf")
    assert s.score == 100


def test_score_invoice():
    s = score_pdf("invoice.pdf")
    assert s.score == -60


def test_score_receipt_invoice():
    # Has both - should net positive (100 - 60 = 40)
    s = score_pdf("receipt-invoice.pdf")
    assert s.score == 40


def test_select_best_pdf_receipt_over_invoice():
    """Multiple PDFs with receipt and invoice: receipt selected, invoice ignored."""
    attachments = [
        {"filename": "invoice.pdf"},
        {"filename": "receipt.pdf"},
        {"filename": "statement.pdf"},
    ]
    selected, all_scores = select_best_pdf(attachments)
    assert selected is not None
    assert selected.filename == "receipt.pdf"
    assert selected.decision == "selected"

    ignored = [s for s in all_scores if s.filename != "receipt.pdf"]
    for s in ignored:
        assert s.decision == "ignored"


def test_select_best_pdf_no_receipts():
    attachments = [
        {"filename": "invoice.pdf"},
        {"filename": "statement.pdf"},
    ]
    selected, all_scores = select_best_pdf(attachments)
    assert selected is None
    for s in all_scores:
        assert s.decision == "ignored"


def test_select_best_pdf_empty():
    selected, all_scores = select_best_pdf([])
    assert selected is None
    assert all_scores == []


def test_select_best_pdf_tie_break_exact_receipt():
    """Tie-break: exact 'receipt' wins over 'purchase receipt order receipt'."""
    attachments = [
        {"filename": "order-receipt.pdf"},
        {"filename": "receipt.pdf"},
    ]
    selected, _ = select_best_pdf(attachments)
    assert selected is not None
    assert selected.filename in ["receipt.pdf", "order-receipt.pdf"]
