"""Service functions for parsing CSV and OFX/QFX card statement files.

Each parser returns a list of dicts with keys:
  date (date), amount (float), merchant (str|None), transaction_id (str|None), currency (str)

Any parsing error raises ``ValueError`` with a descriptive message so the
router can perform a full rollback.
"""
import csv
import io
import re
from datetime import date
from typing import Optional


_DEFAULT_CSV_COLUMNS = ("date", "amount", "merchant", "transaction_id")


def parse_csv_statement(
    content: str,
    column_map: Optional[dict] = None,
) -> list[dict]:
    """Parse a CSV statement file.

    Args:
        content: Raw text content of the CSV file.
        column_map: Optional mapping of logical field name → CSV header name.
            Logical fields: ``date``, ``amount``, ``merchant``, ``transaction_id``.
            When *None* the default template order is assumed:
            ``date, amount, merchant, transaction_id``.

    Returns:
        List of transaction dicts.

    Raises:
        ValueError: On any parsing error.
    """
    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames

    if headers is None:
        raise ValueError("CSV file is empty or has no header row")

    # Normalize header names (strip whitespace)
    headers = [h.strip() for h in headers]

    if column_map is not None:
        # Validate that all mapped columns exist
        for logical, csv_col in column_map.items():
            if csv_col not in headers:
                raise ValueError(
                    f"Column {csv_col!r} specified in column_map for {logical!r} "
                    f"not found in CSV headers: {headers}"
                )
        date_col = column_map.get("date")
        amount_col = column_map.get("amount")
        merchant_col = column_map.get("merchant")
        txn_id_col = column_map.get("transaction_id")
        if not date_col:
            raise ValueError("column_map must include a 'date' key")
        if not amount_col:
            raise ValueError("column_map must include an 'amount' key")
    else:
        # Use default template: first header row position
        if len(headers) < 2:
            raise ValueError(
                "CSV must have at least 2 columns (date, amount) when no column_map is provided"
            )
        date_col = headers[0]
        amount_col = headers[1]
        merchant_col = headers[2] if len(headers) > 2 else None
        txn_id_col = headers[3] if len(headers) > 3 else None

    rows = []
    for row_num, raw_row in enumerate(reader, start=2):
        # Strip whitespace from all values; skip None keys (extra columns)
        row = {k.strip(): (v.strip() if v else "") for k, v in raw_row.items() if k is not None}

        # --- date ---
        raw_date = row.get(date_col, "")
        if not raw_date:
            raise ValueError(f"Row {row_num}: missing date value in column {date_col!r}")
        txn_date = _parse_date(raw_date, row_num)

        # --- amount ---
        raw_amount = row.get(amount_col, "")
        if not raw_amount:
            raise ValueError(f"Row {row_num}: missing amount value in column {amount_col!r}")
        try:
            # Remove common currency symbols/commas before parsing
            amount = float(re.sub(r"[,$£€\s]", "", raw_amount))
        except ValueError:
            raise ValueError(
                f"Row {row_num}: cannot parse amount {raw_amount!r} as a number"
            )

        # --- optional fields ---
        merchant = row.get(merchant_col, "") if merchant_col else None
        merchant = merchant or None
        transaction_id = row.get(txn_id_col, "") if txn_id_col else None
        transaction_id = transaction_id or None

        rows.append(
            {
                "date": txn_date,
                "amount": amount,
                "merchant": merchant,
                "transaction_id": transaction_id,
                "currency": "USD",
            }
        )

    if not rows:
        raise ValueError("CSV file contains no transaction rows")

    return rows


def parse_ofx_statement(content: str) -> list[dict]:
    """Parse an OFX or QFX statement file (SGML format).

    Handles the traditional SGML (tag-per-line, no closing tags) format used by
    most bank OFX exports.  Also handles basic XML-style OFX 2.x.

    Returns:
        List of transaction dicts.

    Raises:
        ValueError: On any parsing error.
    """
    rows = []

    # Normalize line endings
    text = content.replace("\r\n", "\n").replace("\r", "\n")

    # Extract all STMTTRN blocks
    # Works for both SGML and XML styles
    blocks = re.findall(
        r"<STMTTRN>(.*?)</STMTTRN>",
        text,
        re.DOTALL | re.IGNORECASE,
    )

    if not blocks:
        # Try alternative SGML pattern without explicit closing tags
        # Some exporters end blocks with <STMTTRN> on the next transaction
        parts = re.split(r"(?i)<STMTTRN>", text)
        blocks = [p for p in parts[1:]]  # Skip content before first <STMTTRN>

    if not blocks:
        raise ValueError("No transaction blocks (<STMTTRN>) found in OFX/QFX file")

    for idx, block in enumerate(blocks, start=1):
        txn = _parse_ofx_block(block, idx)
        rows.append(txn)

    if not rows:
        raise ValueError("OFX/QFX file contains no transaction rows")

    return rows


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_ofx_field(block: str, tag: str) -> Optional[str]:
    """Extract the value of an OFX SGML/XML tag from a transaction block."""
    pattern = rf"<{tag}>\s*([^<\n]+)"
    m = re.search(pattern, block, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _parse_ofx_block(block: str, idx: int) -> dict:
    """Parse a single STMTTRN block into a transaction dict."""
    # Date: DTPOSTED or DTUSER, format YYYYMMDD[HHMMSS...]
    raw_date = _get_ofx_field(block, "DTPOSTED") or _get_ofx_field(block, "DTUSER")
    if not raw_date:
        raise ValueError(f"Transaction {idx}: missing DTPOSTED/DTUSER field")

    txn_date = _parse_ofx_date(raw_date, idx)

    # Amount
    raw_amount = _get_ofx_field(block, "TRNAMT")
    if not raw_amount:
        raise ValueError(f"Transaction {idx}: missing TRNAMT field")
    try:
        amount = float(raw_amount)
    except ValueError:
        raise ValueError(f"Transaction {idx}: cannot parse amount {raw_amount!r}")

    # Merchant / description
    merchant = _get_ofx_field(block, "NAME") or _get_ofx_field(block, "MEMO")

    # Transaction ID
    transaction_id = _get_ofx_field(block, "FITID")

    # Currency (optional, defaults to USD)
    currency = _get_ofx_field(block, "CURDEF") or _get_ofx_field(block, "CURRENCY") or "USD"
    # OFX CURRENCY tag may contain child tags; take only if short
    if len(currency) > 10:
        currency = "USD"

    return {
        "date": txn_date,
        "amount": amount,
        "merchant": merchant or None,
        "transaction_id": transaction_id or None,
        "currency": currency,
    }


def _parse_date(value: str, row_num: int) -> date:
    """Parse a date string in common formats used in CSV statements."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%Y%m%d"):
        try:
            return date.fromisoformat(value) if fmt == "%Y-%m-%d" else _strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"Row {row_num}: cannot parse date {value!r}. "
        "Expected formats: YYYY-MM-DD, MM/DD/YYYY, DD/MM/YYYY, YYYYMMDD"
    )


def _strptime(value: str, fmt: str) -> date:
    from datetime import datetime as _dt
    return _dt.strptime(value, fmt).date()


def _parse_ofx_date(value: str, idx: int) -> date:
    """Parse an OFX date string (YYYYMMDD[HHMMSS][.sss][TZ])."""
    # Take only the first 8 characters (YYYYMMDD)
    raw = re.sub(r"[^0-9]", "", value)[:8]
    if len(raw) < 8:
        raise ValueError(
            f"Transaction {idx}: cannot parse OFX date {value!r} (expected YYYYMMDD...)"
        )
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError as exc:
        raise ValueError(f"Transaction {idx}: invalid OFX date {value!r}: {exc}") from exc
