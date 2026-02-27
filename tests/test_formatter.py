"""Tests for transaction formatter."""

from decimal import Decimal

from hledger_textual.formatter import format_posting, format_transaction, normalize_commodity
from hledger_textual.models import (
    Amount,
    AmountStyle,
    Posting,
    Transaction,
    TransactionStatus,
)


class TestNormalizeCommodity:
    """Tests for normalize_commodity helper."""

    def test_eur_to_symbol(self):
        """EUR is converted to the Euro sign."""
        assert normalize_commodity("EUR") == "€"

    def test_usd_to_symbol(self):
        """USD is converted to the Dollar sign."""
        assert normalize_commodity("USD") == "$"

    def test_gbp_to_symbol(self):
        """GBP is converted to the Pound sign."""
        assert normalize_commodity("GBP") == "£"

    def test_unknown_code_unchanged(self):
        """Unknown commodity codes are returned as-is."""
        assert normalize_commodity("XDWD") == "XDWD"

    def test_symbol_unchanged(self):
        """Already-symbol commodities pass through unchanged."""
        assert normalize_commodity("€") == "€"

    def test_empty_string(self):
        """Empty string is returned as-is."""
        assert normalize_commodity("") == ""


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
