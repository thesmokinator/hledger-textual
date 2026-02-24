"""Tests for data models."""

from decimal import Decimal

from hledger_tui.models import (
    Amount,
    AmountStyle,
    Posting,
    Transaction,
    TransactionStatus,
)


class TestTransactionStatus:
    """Tests for TransactionStatus enum."""

    def test_cleared_symbol(self):
        assert TransactionStatus.CLEARED.symbol == "*"

    def test_pending_symbol(self):
        assert TransactionStatus.PENDING.symbol == "!"

    def test_unmarked_symbol(self):
        assert TransactionStatus.UNMARKED.symbol == ""

    def test_from_value(self):
        assert TransactionStatus("Cleared") == TransactionStatus.CLEARED
        assert TransactionStatus("Pending") == TransactionStatus.PENDING
        assert TransactionStatus("Unmarked") == TransactionStatus.UNMARKED


class TestAmount:
    """Tests for Amount formatting."""

    def test_format_left_commodity(self):
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        amt = Amount(commodity="€", quantity=Decimal("40.80"), style=style)
        assert amt.format() == "€40.80"

    def test_format_right_commodity(self):
        style = AmountStyle(commodity_side="R", commodity_spaced=True, precision=2)
        amt = Amount(commodity="EUR", quantity=Decimal("40.80"), style=style)
        assert amt.format() == "40.80 EUR"

    def test_format_negative(self):
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        amt = Amount(commodity="€", quantity=Decimal("-40.80"), style=style)
        assert amt.format() == "-€40.80"

    def test_format_zero_precision(self):
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=0)
        amt = Amount(commodity="$", quantity=Decimal("100"), style=style)
        assert amt.format() == "$100"

    def test_format_high_precision(self):
        style = AmountStyle(commodity_side="R", commodity_spaced=True, precision=4)
        amt = Amount(commodity="BTC", quantity=Decimal("0.0001"), style=style)
        assert amt.format() == "0.0001 BTC"


class TestTransaction:
    """Tests for Transaction properties."""

    def test_total_amount_single_commodity(self, euro_style):
        txn = Transaction(
            index=1,
            date="2026-01-01",
            description="Test",
            postings=[
                Posting(
                    account="expenses:food",
                    amounts=[Amount(commodity="€", quantity=Decimal("40.80"), style=euro_style)],
                ),
                Posting(
                    account="assets:bank",
                    amounts=[Amount(commodity="€", quantity=Decimal("-40.80"), style=euro_style)],
                ),
            ],
        )
        assert txn.total_amount == "€40.80"

    def test_total_amount_no_positive(self, euro_style):
        txn = Transaction(
            index=1,
            date="2026-01-01",
            description="Test",
            postings=[
                Posting(
                    account="expenses:food",
                    amounts=[Amount(commodity="€", quantity=Decimal("-40.80"), style=euro_style)],
                ),
            ],
        )
        assert txn.total_amount == ""

    def test_total_amount_multiple_postings(self, euro_style):
        txn = Transaction(
            index=1,
            date="2026-01-01",
            description="Test",
            postings=[
                Posting(
                    account="expenses:office",
                    amounts=[Amount(commodity="€", quantity=Decimal("25.00"), style=euro_style)],
                ),
                Posting(
                    account="expenses:shipping",
                    amounts=[Amount(commodity="€", quantity=Decimal("10.00"), style=euro_style)],
                ),
                Posting(
                    account="assets:bank",
                    amounts=[Amount(commodity="€", quantity=Decimal("-35.00"), style=euro_style)],
                ),
            ],
        )
        assert txn.total_amount == "€35.00"
