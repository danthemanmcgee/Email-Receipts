import re
import io
import logging
from datetime import date, datetime
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    merchant: Optional[str] = None
    purchase_date: Optional[date] = None
    amount: Optional[float] = None
    currency: str = "USD"
    card_last4: Optional[str] = None
    card_network_or_issuer: Optional[str] = None
    confidence: float = 0.0
    notes: list = field(default_factory=list)
    source_type: str = "email_body"


# Common currency patterns
AMOUNT_PATTERN = re.compile(
    r"(?:total|amount|charged|paid|order total)[:\s]*"
    r"(?P<currency>\$|USD|EUR|GBP)?\s*(?P<amount>\d{1,6}[.,]\d{2})",
    re.IGNORECASE,
)
AMOUNT_FALLBACK = re.compile(
    r"(?P<currency>\$|USD|EUR|GBP)\s*(?P<amount>\d{1,6}[.,]\d{2})",
    re.IGNORECASE,
)

DATE_PATTERNS = [
    re.compile(r"(?:date|dated|order date|purchase date)[:\s]*"
               r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", re.IGNORECASE),
    re.compile(r"(\d{4}-\d{2}-\d{2})"),
    re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})"),
]

CARD_PATTERN = re.compile(
    r"(?:ending\s+in|ending\s*:|\*{2,}|x{2,})[\s]*(\d{4})",
    re.IGNORECASE,
)

NETWORK_PATTERN = re.compile(
    r"\b(visa|mastercard|amex|american express|discover|diners|jcb)\b",
    re.IGNORECASE,
)

MERCHANT_PATTERNS = [
    re.compile(r"(?:merchant|store|retailer|sold by|from)[:\s]+([A-Za-z0-9& ,.\-]{2,50})", re.IGNORECASE),
    re.compile(r"(?:thank you for (?:shopping|your order) (?:at|with|from))[:\s]+([A-Za-z0-9& ,.\-]{2,50})", re.IGNORECASE),
]


def _parse_amount(text: str) -> tuple[Optional[float], str]:
    m = AMOUNT_PATTERN.search(text)
    if not m:
        m = AMOUNT_FALLBACK.search(text)
    if m:
        raw = m.group("amount").replace(",", ".")
        try:
            amount = float(raw)
            currency_sym = m.group("currency") or "USD"
            currency_map = {"$": "USD", "€": "EUR", "£": "GBP"}
            currency = currency_map.get(currency_sym.upper(), currency_sym.upper())
            return amount, currency
        except ValueError:
            pass
    return None, "USD"


def _parse_date(text: str) -> Optional[date]:
    for pattern in DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1)
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    return datetime.strptime(raw, fmt).date()
                except ValueError:
                    continue
    return None


def _parse_card(text: str) -> tuple[Optional[str], Optional[str]]:
    last4 = None
    network = None
    m = CARD_PATTERN.search(text)
    if m:
        last4 = m.group(1)
    nm = NETWORK_PATTERN.search(text)
    if nm:
        network = nm.group(1).title()
    return last4, network


def _parse_merchant(text: str) -> Optional[str]:
    for pattern in MERCHANT_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1).strip()[:100]
    return None


def extract_from_text(text: str, source_type: str = "email_body") -> ExtractionResult:
    """Extract receipt fields from plain text."""
    result = ExtractionResult(source_type=source_type)
    fields_found = 0

    merchant = _parse_merchant(text)
    if merchant:
        result.merchant = merchant
        fields_found += 1
        result.notes.append(f"merchant: {merchant}")

    purchase_date = _parse_date(text)
    if purchase_date:
        result.purchase_date = purchase_date
        fields_found += 1
        result.notes.append(f"date: {purchase_date}")

    amount, currency = _parse_amount(text)
    if amount is not None:
        result.amount = amount
        result.currency = currency
        fields_found += 1
        result.notes.append(f"amount: {amount} {currency}")

    last4, network = _parse_card(text)
    if last4:
        result.card_last4 = last4
        fields_found += 1
        result.notes.append(f"card last4: {last4}")
    if network:
        result.card_network_or_issuer = network

    result.confidence = min(1.0, fields_found / 4.0)
    return result


def extract_from_pdf_bytes(pdf_bytes: bytes) -> ExtractionResult:
    """Extract receipt fields from PDF bytes using PyPDF2."""
    try:
        import PyPDF2  # noqa: PLC0415

        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        text_parts = []
        for page in reader.pages:
            try:
                text_parts.append(page.extract_text() or "")
            except Exception:
                continue
        full_text = "\n".join(text_parts)
        if not full_text.strip():
            result = ExtractionResult()
            result.notes.append("PDF text extraction returned empty content")
            return result
        return extract_from_text(full_text, source_type="pdf_attachment")
    except Exception as exc:
        logger.warning("PDF extraction failed: %s", exc)
        result = ExtractionResult()
        result.notes.append(f"PDF extraction error: {exc}")
        return result
