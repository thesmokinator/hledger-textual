"""Tests for transaction formatter."""

from decimal import Decimal

from hledger_tui.formatter import format_amount, format_posting, format_transaction
from hledger_tui.models import (
    Amount,
    AmountStyle,
    Posting,
    Transaction,
    TransactionStatus,
)


class TestFormatAmount:
    """Tests for format_amount."""

    def test_left_commodity(self):
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        amt = Amount(commodity="€", quantity=Decimal("40.80"), style=style)
        assert format_amount(amt) == "€40.80"

    def test_right_commodity_spaced(self):
        style = AmountStyle(commodity_side="R", commodity_spaced=True, precision=2)
        amt = Amount(commodity="EUR", quantity=Decimal("40.80"), style=style)
        assert format_amount(amt) == "40.80 EUR"

    def test_negative_amount(self):
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        amt = Amount(commodity="$", quantity=Decimal("-100.00"), style=style)
        assert format_amount(amt) == "-$100.00"


class TestFormatPosting:
    """Tests for format_posting."""

    def test_posting_with_amount(self):
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        posting = Posting(
            account="expenses:food",
            amounts=[Amount(commodity="€", quantity=Decimal("40.80"), style=style)],
        )
        result = format_posting(posting)
        assert result.startswith("    expenses:food")
        assert "€40.80" in result

    def test_posting_without_amount(self):
        posting = Posting(account="assets:bank:checking")
        result = format_posting(posting)
        assert result == "    assets:bank:checking"

    def test_posting_with_comment(self):
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        posting = Posting(
            account="expenses:food",
            amounts=[Amount(commodity="€", quantity=Decimal("40.80"), style=style)],
            comment="groceries",
        )
        result = format_posting(posting)
        assert "; groceries" in result


class TestFormatTransaction:
    """Tests for format_transaction."""

    def test_cleared_transaction(self, sample_transaction):
        result = format_transaction(sample_transaction)
        lines = result.splitlines()
        assert lines[0] == "2026-01-15 * (INV-001) Grocery shopping  ; weekly groceries"
        assert len(lines) == 3

    def test_unmarked_transaction(self, euro_style):
        txn = Transaction(
            index=1,
            date="2026-01-16",
            description="Salary",
            status=TransactionStatus.UNMARKED,
            postings=[
                Posting(
                    account="assets:bank:checking",
                    amounts=[Amount(commodity="€", quantity=Decimal("3000.00"), style=euro_style)],
                ),
                Posting(
                    account="income:salary",
                    amounts=[Amount(commodity="€", quantity=Decimal("-3000.00"), style=euro_style)],
                ),
            ],
        )
        result = format_transaction(txn)
        lines = result.splitlines()
        assert lines[0] == "2026-01-16 Salary"

    def test_pending_transaction(self, euro_style):
        txn = Transaction(
            index=1,
            date="2026-01-17",
            description="Office supplies",
            status=TransactionStatus.PENDING,
            postings=[
                Posting(
                    account="expenses:office",
                    amounts=[Amount(commodity="€", quantity=Decimal("25.00"), style=euro_style)],
                ),
                Posting(
                    account="assets:bank:checking",
                    amounts=[Amount(commodity="€", quantity=Decimal("-25.00"), style=euro_style)],
                ),
            ],
        )
        result = format_transaction(txn)
        assert result.startswith("2026-01-17 ! Office supplies")

    def test_posting_alignment(self, sample_transaction):
        result = format_transaction(sample_transaction)
        lines = result.splitlines()
        # Amount columns should be right-aligned (same end position)
        amount_end_1 = len(lines[1].rstrip())
        amount_end_2 = len(lines[2].rstrip())
        assert amount_end_1 == amount_end_2

    def test_roundtrip_preserves_structure(self, sample_transaction):
        result = format_transaction(sample_transaction)
        assert "expenses:food:groceries" in result
        assert "assets:bank:checking" in result
        assert "€40.80" in result
