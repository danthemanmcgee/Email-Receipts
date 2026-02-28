"""Tests for the reconciliation service and reconciliation API endpoints.

Covers:
- Scoring components (amount, date, merchant, card)
- suggest_matches filtering and threshold
- Only Drive-stored receipts are eligible
- API: link, unlink, ignore/restore
"""
import os
import pytest
from datetime import date
from unittest.mock import MagicMock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


# ---------------------------------------------------------------------------
# Reconciliation service unit tests
# ---------------------------------------------------------------------------

def _make_receipt(
    id=1,
    merchant="Amazon",
    amount=-42.50,
    purchase_date=date(2023, 4, 15),
    drive_file_id="file123",
    physical_card_id=None,
):
    from app.models.receipt import Receipt

    r = Receipt.__new__(Receipt)
    r.id = id
    r.merchant = merchant
    r.amount = amount
    r.purchase_date = purchase_date
    r.drive_file_id = drive_file_id
    r.physical_card_id = physical_card_id
    return r


def _make_line(
    id=1,
    merchant="AMAZON",
    amount=-42.50,
    txn_date=date(2023, 4, 15),
    card_id=1,
):
    from app.models.statement import StatementLine, MatchStatus

    line = StatementLine.__new__(StatementLine)
    line.id = id
    line.merchant = merchant
    line.amount = amount
    line.txn_date = txn_date
    line.card_id = card_id
    line.match_status = MatchStatus.unmatched
    return line


class TestAmountScore:
    def test_exact_match(self):
        from app.services.reconciliation_service import _amount_score

        assert _amount_score(-42.50, -42.50) == pytest.approx(0.50)

    def test_exact_absolute_value_match(self):
        from app.services.reconciliation_service import _amount_score

        assert _amount_score(-42.50, 42.50) == pytest.approx(0.50)

    def test_within_one_percent(self):
        from app.services.reconciliation_service import _amount_score

        assert _amount_score(100.00, 100.50) == pytest.approx(0.40)

    def test_within_five_percent(self):
        from app.services.reconciliation_service import _amount_score

        assert _amount_score(100.00, 103.00) == pytest.approx(0.25)

    def test_outside_five_percent(self):
        from app.services.reconciliation_service import _amount_score

        assert _amount_score(100.00, 200.00) == 0.0

    def test_receipt_amount_none(self):
        from app.services.reconciliation_service import _amount_score

        assert _amount_score(50.0, None) == 0.0


class TestDateScore:
    def test_same_day(self):
        from app.services.reconciliation_service import _date_score

        assert _date_score(date(2023, 4, 15), date(2023, 4, 15)) == pytest.approx(0.30)

    def test_within_three_days(self):
        from app.services.reconciliation_service import _date_score

        assert _date_score(date(2023, 4, 15), date(2023, 4, 17)) == pytest.approx(0.20)

    def test_within_seven_days(self):
        from app.services.reconciliation_service import _date_score

        assert _date_score(date(2023, 4, 15), date(2023, 4, 20)) == pytest.approx(0.10)

    def test_outside_seven_days(self):
        from app.services.reconciliation_service import _date_score

        assert _date_score(date(2023, 4, 15), date(2023, 5, 15)) == 0.0

    def test_none_date(self):
        from app.services.reconciliation_service import _date_score

        assert _date_score(date(2023, 4, 15), None) == 0.0


class TestMerchantScore:
    def test_exact_match(self):
        from app.services.reconciliation_service import _merchant_score

        assert _merchant_score("Amazon", "Amazon") == pytest.approx(0.20)

    def test_case_insensitive_match(self):
        from app.services.reconciliation_service import _merchant_score

        assert _merchant_score("AMAZON", "amazon") == pytest.approx(0.20)

    def test_substring_match(self):
        from app.services.reconciliation_service import _merchant_score

        assert _merchant_score("Amazon", "Amazon.com") == pytest.approx(0.15)

    def test_first_word_match(self):
        from app.services.reconciliation_service import _merchant_score

        # "Starbucks Roastery" vs "Starbucks Cafe" — first word matches but neither is a substring
        assert _merchant_score("Starbucks Roastery", "Starbucks Cafe") == pytest.approx(0.10)

    def test_no_match(self):
        from app.services.reconciliation_service import _merchant_score

        assert _merchant_score("Walmart", "Amazon") == 0.0

    def test_none_merchant(self):
        from app.services.reconciliation_service import _merchant_score

        assert _merchant_score(None, "Amazon") == 0.0
        assert _merchant_score("Amazon", None) == 0.0


class TestCardScore:
    def test_same_card(self):
        from app.services.reconciliation_service import _card_score

        assert _card_score(5, 5) == pytest.approx(0.10)

    def test_different_card(self):
        from app.services.reconciliation_service import _card_score

        assert _card_score(5, 6) == 0.0

    def test_none_card(self):
        from app.services.reconciliation_service import _card_score

        assert _card_score(5, None) == 0.0


class TestSuggestMatches:
    def test_high_score_receipt_suggested(self):
        from app.services.reconciliation_service import suggest_matches

        line = _make_line(merchant="AMAZON", amount=-42.50, txn_date=date(2023, 4, 15))
        receipt = _make_receipt(
            merchant="Amazon",
            amount=-42.50,
            purchase_date=date(2023, 4, 15),
            drive_file_id="f1",
        )
        results = suggest_matches(line, [receipt])
        assert len(results) == 1
        assert results[0][0].id == receipt.id
        assert results[0][1] >= 0.50

    def test_no_drive_file_excluded(self):
        from app.services.reconciliation_service import suggest_matches

        line = _make_line(merchant="AMAZON", amount=-42.50, txn_date=date(2023, 4, 15))
        receipt = _make_receipt(
            merchant="Amazon",
            amount=-42.50,
            purchase_date=date(2023, 4, 15),
            drive_file_id=None,  # not in Drive
        )
        results = suggest_matches(line, [receipt])
        assert len(results) == 0

    def test_low_score_excluded(self):
        from app.services.reconciliation_service import suggest_matches

        line = _make_line(merchant="Starbucks", amount=-5.00, txn_date=date(2023, 4, 15))
        receipt = _make_receipt(
            merchant="Whole Foods",
            amount=-200.00,
            purchase_date=date(2023, 1, 1),
            drive_file_id="f1",
        )
        results = suggest_matches(line, [receipt])
        assert len(results) == 0

    def test_results_sorted_by_score_desc(self):
        from app.services.reconciliation_service import suggest_matches

        line = _make_line(merchant="Target", amount=-30.00, txn_date=date(2023, 4, 15))
        # Better match: same day, same amount
        r1 = _make_receipt(
            id=1, merchant="Target", amount=-30.00,
            purchase_date=date(2023, 4, 15), drive_file_id="f1"
        )
        # Weaker match: 5 days off, same amount
        r2 = _make_receipt(
            id=2, merchant="Target", amount=-30.00,
            purchase_date=date(2023, 4, 10), drive_file_id="f2"
        )
        results = suggest_matches(line, [r2, r1])
        assert results[0][0].id == r1.id
        assert results[0][1] >= results[1][1]

    def test_limit_respected(self):
        from app.services.reconciliation_service import suggest_matches

        line = _make_line(merchant="Shop", amount=-10.00, txn_date=date(2023, 4, 15))
        receipts = [
            _make_receipt(
                id=i, merchant="Shop", amount=-10.00,
                purchase_date=date(2023, 4, 15), drive_file_id=f"f{i}"
            )
            for i in range(10)
        ]
        results = suggest_matches(line, receipts, limit=3)
        assert len(results) <= 3

    def test_custom_threshold(self):
        from app.services.reconciliation_service import suggest_matches

        line = _make_line(merchant="X", amount=-10.00, txn_date=date(2023, 4, 15))
        receipt = _make_receipt(
            merchant="X", amount=-10.00,
            purchase_date=date(2023, 4, 13),  # 2 days off → date_score 0.20
            drive_file_id="f1",
        )
        # With default threshold 0.50: amount 0.50 + date 0.20 + merchant 0.20 = 0.90 → included
        results_default = suggest_matches(line, [receipt])
        assert len(results_default) == 1

        # With threshold 0.99: should be excluded
        results_strict = suggest_matches(line, [receipt], threshold=0.99)
        assert len(results_strict) == 0


# ---------------------------------------------------------------------------
# MatchStatus model test
# ---------------------------------------------------------------------------

class TestMatchStatus:
    def test_default_is_unmatched(self):
        from app.models.statement import StatementLine, MatchStatus

        line = StatementLine.__new__(StatementLine)
        line.match_status = MatchStatus.unmatched
        assert line.match_status == MatchStatus.unmatched
        assert line.match_status.value == "unmatched"

    def test_enum_values(self):
        from app.models.statement import MatchStatus

        assert MatchStatus.matched.value == "matched"
        assert MatchStatus.ignored.value == "ignored"
        assert MatchStatus.unmatched.value == "unmatched"


# ---------------------------------------------------------------------------
# Reconciliation router unit tests (mocked DB)
# ---------------------------------------------------------------------------

class TestReconciliationEndpoints:
    def _make_line_db(self, id=1, user_id=1, card_id=1, match=None):
        from app.models.statement import StatementLine, MatchStatus

        line = StatementLine.__new__(StatementLine)
        line.id = id
        line.user_id = user_id
        line.card_id = card_id
        line.merchant = "Amazon"
        line.amount = -42.50
        line.txn_date = date(2023, 4, 15)
        line.currency = "USD"
        line.match_status = MatchStatus.unmatched
        line.match = match
        return line

    def _make_user(self, user_id=1):
        from app.models.user import User
        from datetime import datetime, timezone

        user = User.__new__(User)
        user.id = user_id
        user.email = "test@example.com"
        user.hashed_password = "hash"
        user.google_sub = None
        user.is_active = True
        user.created_at = datetime.now(tz=timezone.utc)
        user.updated_at = datetime.now(tz=timezone.utc)
        return user

    def test_link_receipt_line_not_found(self):
        from fastapi import HTTPException
        from app.routers.reconciliation import link_receipt

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        user = self._make_user()

        with pytest.raises(HTTPException) as exc_info:
            import asyncio
            # link_receipt is synchronous
            link_receipt(line_id=999, receipt_id=1, db=db, current_user=user)
        assert exc_info.value.status_code == 404

    def test_unlink_receipt_line_not_found(self):
        from fastapi import HTTPException
        from app.routers.reconciliation import unlink_receipt

        db = MagicMock()
        db.query.return_value.filter.return_value.options.return_value.first.return_value = None
        user = self._make_user()

        with pytest.raises(HTTPException) as exc_info:
            unlink_receipt(line_id=999, db=db, current_user=user)
        assert exc_info.value.status_code == 404

    def test_toggle_ignore_sets_ignored(self):
        from app.routers.reconciliation import toggle_ignore
        from app.models.statement import MatchStatus

        line = self._make_line_db()
        line.match = None

        db = MagicMock()
        db.query.return_value.filter.return_value.options.return_value.first.return_value = line
        user = self._make_user()

        result = toggle_ignore(line_id=line.id, db=db, current_user=user)
        assert result["status"] == "ignored"
        assert line.match_status == MatchStatus.ignored
        db.commit.assert_called_once()

    def test_toggle_ignore_restores_unmatched(self):
        from app.routers.reconciliation import toggle_ignore
        from app.models.statement import MatchStatus

        line = self._make_line_db()
        line.match_status = MatchStatus.ignored
        line.match = None

        db = MagicMock()
        db.query.return_value.filter.return_value.options.return_value.first.return_value = line
        user = self._make_user()

        result = toggle_ignore(line_id=line.id, db=db, current_user=user)
        assert result["status"] == "unmatched"
        assert line.match_status == MatchStatus.unmatched

    def test_unlink_clears_match_and_sets_unmatched(self):
        from app.routers.reconciliation import unlink_receipt
        from app.models.statement import MatchStatus

        match_obj = MagicMock()
        line = self._make_line_db(match=match_obj)
        line.match_status = MatchStatus.matched

        db = MagicMock()
        db.query.return_value.filter.return_value.options.return_value.first.return_value = line
        user = self._make_user()

        result = unlink_receipt(line_id=line.id, db=db, current_user=user)
        assert result["status"] == "unmatched"
        db.delete.assert_called_once_with(match_obj)
        assert line.match_status == MatchStatus.unmatched
