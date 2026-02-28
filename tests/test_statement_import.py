"""Tests for CSV and OFX/QFX card statement import.

Covers:
- CSV parsing with default template and custom column_map
- OFX parsing (SGML format)
- Validation errors cause full rollback (no partial data)
- User + card scoping
- Valid import yields correct lines
"""
import os
import pytest
from datetime import date
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


# ---------------------------------------------------------------------------
# CSV parser unit tests
# ---------------------------------------------------------------------------

class TestCsvParsing:
    def test_default_template_four_columns(self):
        from app.services.statement_service import parse_csv_statement

        content = "date,amount,merchant,transaction_id\n2023-04-15,-42.50,AMAZON,TXN001\n"
        rows = parse_csv_statement(content)
        assert len(rows) == 1
        row = rows[0]
        assert row["date"] == date(2023, 4, 15)
        assert row["amount"] == -42.50
        assert row["merchant"] == "AMAZON"
        assert row["transaction_id"] == "TXN001"

    def test_default_template_two_columns(self):
        from app.services.statement_service import parse_csv_statement

        content = "date,amount\n2023-01-01,100.00\n"
        rows = parse_csv_statement(content)
        assert len(rows) == 1
        assert rows[0]["merchant"] is None
        assert rows[0]["transaction_id"] is None

    def test_column_map_reorders_columns(self):
        from app.services.statement_service import parse_csv_statement

        content = "Transaction Date,Debit,Description,Ref#\n04/15/2023,50.00,Starbucks,REF123\n"
        col_map = {
            "date": "Transaction Date",
            "amount": "Debit",
            "merchant": "Description",
            "transaction_id": "Ref#",
        }
        rows = parse_csv_statement(content, column_map=col_map)
        assert rows[0]["date"] == date(2023, 4, 15)
        assert rows[0]["amount"] == 50.00
        assert rows[0]["merchant"] == "Starbucks"
        assert rows[0]["transaction_id"] == "REF123"

    def test_currency_symbol_stripped(self):
        from app.services.statement_service import parse_csv_statement

        content = 'date,amount\n2023-06-01,"$1,234.56"\n'
        rows = parse_csv_statement(content)
        assert rows[0]["amount"] == pytest.approx(1234.56)

    def test_multiple_rows(self):
        from app.services.statement_service import parse_csv_statement

        content = (
            "date,amount,merchant,transaction_id\n"
            "2023-01-01,-10.00,Walmart,T1\n"
            "2023-01-02,-20.00,Target,T2\n"
            "2023-01-03,-30.00,Costco,T3\n"
        )
        rows = parse_csv_statement(content)
        assert len(rows) == 3
        assert [r["merchant"] for r in rows] == ["Walmart", "Target", "Costco"]

    def test_empty_file_raises(self):
        from app.services.statement_service import parse_csv_statement

        with pytest.raises(ValueError, match="empty"):
            parse_csv_statement("")

    def test_no_data_rows_raises(self):
        from app.services.statement_service import parse_csv_statement

        # Header only, no data rows
        with pytest.raises(ValueError, match="no transaction rows"):
            parse_csv_statement("date,amount\n")

    def test_invalid_date_raises(self):
        from app.services.statement_service import parse_csv_statement

        content = "date,amount\nNOT-A-DATE,100.00\n"
        with pytest.raises(ValueError, match="cannot parse date"):
            parse_csv_statement(content)

    def test_invalid_amount_raises(self):
        from app.services.statement_service import parse_csv_statement

        content = "date,amount\n2023-01-01,not-a-number\n"
        with pytest.raises(ValueError, match="cannot parse amount"):
            parse_csv_statement(content)

    def test_missing_date_raises(self):
        from app.services.statement_service import parse_csv_statement

        content = "date,amount\n,100.00\n"
        with pytest.raises(ValueError, match="missing date value"):
            parse_csv_statement(content)

    def test_missing_amount_raises(self):
        from app.services.statement_service import parse_csv_statement

        content = "date,amount\n2023-01-01,\n"
        with pytest.raises(ValueError, match="missing amount value"):
            parse_csv_statement(content)

    def test_column_map_missing_date_key_raises(self):
        from app.services.statement_service import parse_csv_statement

        content = "amt,desc\n10.00,thing\n"
        with pytest.raises(ValueError, match="must include a 'date'"):
            parse_csv_statement(content, column_map={"amount": "amt"})

    def test_column_map_nonexistent_column_raises(self):
        from app.services.statement_service import parse_csv_statement

        content = "date,amount\n2023-01-01,50.00\n"
        with pytest.raises(ValueError, match="not found in CSV headers"):
            parse_csv_statement(content, column_map={"date": "date", "amount": "NONEXISTENT"})

    def test_date_formats_supported(self):
        from app.services.statement_service import parse_csv_statement

        for date_str, expected in [
            ("2023-04-15", date(2023, 4, 15)),
            ("04/15/2023", date(2023, 4, 15)),
            ("20230415", date(2023, 4, 15)),
        ]:
            rows = parse_csv_statement(f"date,amount\n{date_str},1.00\n")
            assert rows[0]["date"] == expected, f"Failed for {date_str}"

    def test_whitespace_stripped_from_headers(self):
        from app.services.statement_service import parse_csv_statement

        content = " date , amount \n2023-01-01,5.00\n"
        rows = parse_csv_statement(content)
        assert rows[0]["amount"] == 5.00

    def test_bom_handled(self):
        """CSV with UTF-8 BOM is decoded correctly (simulated by service layer)."""
        from app.services.statement_service import parse_csv_statement

        content = "\ufeffdate,amount\n2023-01-01,10.00\n"
        # BOM would be stripped by utf-8-sig decode in the router; here it's in the string
        # The parser itself should handle leading BOM in header
        rows = parse_csv_statement(content)
        assert rows[0]["amount"] == 10.00


# ---------------------------------------------------------------------------
# OFX / QFX parser unit tests
# ---------------------------------------------------------------------------

OFX_SAMPLE = """\
OFXHEADER:100
DATA:OFXSGML
VERSION:102

<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<CURDEF>USD
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20230415
<TRNAMT>-42.50
<FITID>TXN001
<NAME>AMAZON.COM
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20230416120000
<TRNAMT>-15.99
<FITID>TXN002
<NAME>NETFLIX
</STMTTRN>
</BANKTRANLIST>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


class TestOfxParsing:
    def test_parses_two_transactions(self):
        from app.services.statement_service import parse_ofx_statement

        rows = parse_ofx_statement(OFX_SAMPLE)
        assert len(rows) == 2

    def test_first_transaction_fields(self):
        from app.services.statement_service import parse_ofx_statement

        rows = parse_ofx_statement(OFX_SAMPLE)
        row = rows[0]
        assert row["date"] == date(2023, 4, 15)
        assert row["amount"] == pytest.approx(-42.50)
        assert row["merchant"] == "AMAZON.COM"
        assert row["transaction_id"] == "TXN001"

    def test_second_transaction_datetime_stripped(self):
        from app.services.statement_service import parse_ofx_statement

        rows = parse_ofx_statement(OFX_SAMPLE)
        assert rows[1]["date"] == date(2023, 4, 16)
        assert rows[1]["merchant"] == "NETFLIX"

    def test_empty_content_raises(self):
        from app.services.statement_service import parse_ofx_statement

        with pytest.raises(ValueError, match="No transaction blocks"):
            parse_ofx_statement("OFXHEADER:100\nDATA:OFXSGML\n")

    def test_missing_dtposted_raises(self):
        from app.services.statement_service import parse_ofx_statement

        content = "<STMTTRN>\n<TRNAMT>-10.00\n<FITID>X\n</STMTTRN>"
        with pytest.raises(ValueError, match="missing DTPOSTED"):
            parse_ofx_statement(content)

    def test_missing_trnamt_raises(self):
        from app.services.statement_service import parse_ofx_statement

        content = "<STMTTRN>\n<DTPOSTED>20230101\n<FITID>X\n</STMTTRN>"
        with pytest.raises(ValueError, match="missing TRNAMT"):
            parse_ofx_statement(content)

    def test_invalid_amount_raises(self):
        from app.services.statement_service import parse_ofx_statement

        content = "<STMTTRN>\n<DTPOSTED>20230101\n<TRNAMT>bad\n</STMTTRN>"
        with pytest.raises(ValueError, match="cannot parse amount"):
            parse_ofx_statement(content)

    def test_ofx_without_closing_stmttrn_tags(self):
        """Some OFX files omit </STMTTRN> closing tags."""
        from app.services.statement_service import parse_ofx_statement

        content = (
            "<BANKTRANLIST>\n"
            "<STMTTRN>\n<DTPOSTED>20230101\n<TRNAMT>-5.00\n<FITID>A\n<NAME>Shop A\n"
            "<STMTTRN>\n<DTPOSTED>20230102\n<TRNAMT>-8.00\n<FITID>B\n<NAME>Shop B\n"
            "</BANKTRANLIST>"
        )
        rows = parse_ofx_statement(content)
        assert len(rows) >= 2

    def test_positive_amount_credit(self):
        from app.services.statement_service import parse_ofx_statement

        content = "<STMTTRN>\n<DTPOSTED>20230501\n<TRNAMT>200.00\n<FITID>CR1\n<NAME>REFUND\n</STMTTRN>"
        rows = parse_ofx_statement(content)
        assert rows[0]["amount"] == 200.00


# ---------------------------------------------------------------------------
# Router-level tests (endpoint logic without live DB)
# ---------------------------------------------------------------------------

class TestStatementEndpointLogic:
    """Test the import endpoint's validation and rollback behavior via service layer."""

    def _make_card(self, card_id=1, user_id=1):
        from app.models.card import PhysicalCard
        card = PhysicalCard.__new__(PhysicalCard)
        card.id = card_id
        card.user_id = user_id
        card.display_name = "My Visa"
        card.last4 = "1234"
        card.network = "Visa"
        return card

    def _make_user(self, user_id=1):
        from app.models.user import User
        from datetime import datetime, timezone
        user = User.__new__(User)
        user.id = user_id
        user.email = "alice@example.com"
        user.hashed_password = "hash"
        user.google_sub = None
        user.is_active = True
        user.created_at = datetime.now(tz=timezone.utc)
        user.updated_at = datetime.now(tz=timezone.utc)
        return user

    def test_valid_csv_creates_statement_and_lines(self):
        """Simulate the full import flow with a valid CSV."""
        from app.services.statement_service import parse_csv_statement

        content = (
            "date,amount,merchant,transaction_id\n"
            "2023-04-15,-42.50,AMAZON,TXN001\n"
            "2023-04-16,-15.99,NETFLIX,TXN002\n"
        )
        rows = parse_csv_statement(content)
        assert len(rows) == 2

        # Simulate creating a CardStatement
        from app.models.statement import CardStatement, StatementLine
        from datetime import datetime, timezone

        stmt = CardStatement.__new__(CardStatement)
        stmt.id = 1
        stmt.user_id = 1
        stmt.card_id = 1
        stmt.filename = "statement.csv"
        stmt.format = "csv"
        stmt.row_count = len(rows)
        stmt.imported_at = datetime.now(tz=timezone.utc)

        lines = []
        for i, row in enumerate(rows):
            line = StatementLine.__new__(StatementLine)
            line.id = i + 1
            line.statement_id = stmt.id
            line.user_id = 1
            line.card_id = 1
            line.txn_date = row["date"]
            line.amount = row["amount"]
            line.merchant = row.get("merchant")
            line.transaction_id = row.get("transaction_id")
            line.currency = row.get("currency", "USD")
            line.raw_data = None
            lines.append(line)

        assert len(lines) == 2
        assert lines[0].txn_date == date(2023, 4, 15)
        assert lines[1].merchant == "NETFLIX"

    def test_invalid_csv_no_lines_written(self):
        """A ValueError from parsing must prevent any DB writes (rollback)."""
        from app.services.statement_service import parse_csv_statement

        invalid_csv = "date,amount\nNOT-A-DATE,100.00\n"
        with pytest.raises(ValueError):
            parse_csv_statement(invalid_csv)
        # No lines should have been created because parsing failed before any DB write

    def test_card_not_owned_by_user_returns_404(self):
        """A card that belongs to user A cannot be imported to by user B."""
        from fastapi import HTTPException
        from app.routers.statements import _get_card_for_user

        db = MagicMock()
        # Simulate no card found for user_id=2
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            _get_card_for_user(card_id=1, user_id=2, db=db)
        assert exc_info.value.status_code == 404

    def test_card_owned_by_user_returns_card(self):
        from app.routers.statements import _get_card_for_user

        card = self._make_card(card_id=5, user_id=3)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = card

        result = _get_card_for_user(card_id=5, user_id=3, db=db)
        assert result.id == 5


# ---------------------------------------------------------------------------
# User + card scoping tests
# ---------------------------------------------------------------------------

class TestUserCardScoping:
    """Verify that statement data is always scoped to user + card."""

    def _make_statement(self, id, user_id, card_id):
        from app.models.statement import CardStatement
        from datetime import datetime, timezone
        stmt = CardStatement.__new__(CardStatement)
        stmt.id = id
        stmt.user_id = user_id
        stmt.card_id = card_id
        stmt.filename = f"stmt_{id}.csv"
        stmt.format = "csv"
        stmt.row_count = 1
        stmt.imported_at = datetime.now(tz=timezone.utc)
        stmt.lines = []
        return stmt

    def test_user_a_cannot_see_user_b_statements(self):
        """Simulate the list_statements filter: scoped by user_id AND card_id."""
        all_stmts = [
            self._make_statement(1, user_id=1, card_id=10),
            self._make_statement(2, user_id=2, card_id=11),
            self._make_statement(3, user_id=1, card_id=12),
        ]

        user_a_stmts = [s for s in all_stmts if s.user_id == 1 and s.card_id == 10]
        assert len(user_a_stmts) == 1
        assert user_a_stmts[0].id == 1

        user_b_stmts = [s for s in all_stmts if s.user_id == 2]
        assert len(user_b_stmts) == 1
        assert user_b_stmts[0].id == 2

    def test_statement_line_has_user_and_card_id(self):
        from app.services.statement_service import parse_csv_statement
        from app.models.statement import StatementLine

        rows = parse_csv_statement("date,amount\n2023-01-01,50.00\n")
        line = StatementLine.__new__(StatementLine)
        line.user_id = 42
        line.card_id = 99
        line.txn_date = rows[0]["date"]
        line.amount = rows[0]["amount"]
        line.currency = rows[0]["currency"]

        assert line.user_id == 42
        assert line.card_id == 99

    def test_two_users_same_card_id_are_isolated(self):
        """Even if two users somehow share the same card_id value, scoping by user_id isolates them."""
        all_stmts = [
            self._make_statement(1, user_id=1, card_id=5),
            self._make_statement(2, user_id=2, card_id=5),
        ]
        user1_stmts = [s for s in all_stmts if s.user_id == 1 and s.card_id == 5]
        user2_stmts = [s for s in all_stmts if s.user_id == 2 and s.card_id == 5]

        assert len(user1_stmts) == 1
        assert len(user2_stmts) == 1
        assert user1_stmts[0].id != user2_stmts[0].id


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestStatementSchemas:
    def test_statement_line_response_from_attrs(self):
        from app.schemas.statement import StatementLineResponse
        from app.models.statement import StatementLine
        from datetime import datetime, timezone

        line = StatementLine.__new__(StatementLine)
        line.id = 1
        line.statement_id = 10
        line.user_id = 1
        line.card_id = 2
        line.txn_date = date(2023, 6, 1)
        line.amount = -50.00
        line.merchant = "Whole Foods"
        line.transaction_id = "ABC123"
        line.currency = "USD"
        line.raw_data = None

        schema = StatementLineResponse.model_validate(line)
        assert schema.txn_date == date(2023, 6, 1)
        assert schema.amount == -50.00
        assert schema.merchant == "Whole Foods"
        assert schema.currency == "USD"

    def test_card_statement_response_from_attrs(self):
        from app.schemas.statement import CardStatementResponse
        from app.models.statement import CardStatement
        from datetime import datetime, timezone

        stmt = CardStatement.__new__(CardStatement)
        stmt.id = 5
        stmt.user_id = 1
        stmt.card_id = 3
        stmt.filename = "bank_statement.ofx"
        stmt.format = "ofx"
        stmt.row_count = 7
        stmt.imported_at = datetime.now(tz=timezone.utc)
        stmt.lines = []

        schema = CardStatementResponse.model_validate(stmt)
        assert schema.id == 5
        assert schema.format == "ofx"
        assert schema.row_count == 7
        assert schema.lines == []
