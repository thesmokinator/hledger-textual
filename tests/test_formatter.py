"""Tests for transaction formatter and amount formatting helpers."""

from decimal import Decimal

from hledger_textual.formatter import format_posting, format_transaction, normalize_commodity
from hledger_textual.models import (
    Amount,
    AmountStyle,
    Posting,
    Transaction,
    TransactionStatus,
)
from hledger_textual.widgets.formatting import (
    fmt_amount_str,
    fmt_single_amount_str,
    get_commodity_name,
    split_multi_commodity_amounts,
    split_raw_commodities,
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


class TestFmtAmountStr:
    """Tests for fmt_amount_str — single and multi-commodity formatting."""

    def test_single_euro(self):
        """Single-commodity EUR amount gets locale formatting."""
        assert fmt_amount_str("€3741.81") == "€3,741.81"

    def test_single_dollar(self):
        """Single-commodity USD amount gets locale formatting."""
        assert fmt_amount_str("$5750.00") == "$5,750.00"

    def test_single_named_commodity(self):
        """Named-commodity amounts pass through unchanged."""
        assert fmt_amount_str("0.17500000 BTC") == "0.17500000 BTC"
        assert fmt_amount_str("28.0000 XDWD") == "28.0000 XDWD"

    def test_negative_symbol(self):
        """Negative amounts with left-side symbol are formatted correctly."""
        assert fmt_amount_str("£-8.99") == "£-8.99"
        # -€1.73 gets normalized to €-1.73 (sign after symbol)
        assert fmt_amount_str("-€1.73") == "€-1.73"

    def test_two_commodities(self):
        """Two currencies joined by ', ' are split and joined with newline."""
        result = fmt_amount_str("£-8.99, €3741.81")
        assert result == "£-8.99\n€3,741.81"

    def test_six_commodities(self):
        """Full multi-commodity cell from hledger gets stacked formatting."""
        raw = "$5750.00, 0.17500000 BTC, 28.0000 XDWD, 15.0000 XEON, £-8.99, €3741.81"
        result = fmt_amount_str(raw)
        lines = result.split("\n")
        assert len(lines) == 6
        assert lines[0] == "$5,750.00"
        assert lines[1] == "0.17500000 BTC"
        assert lines[5] == "€3,741.81"

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert fmt_amount_str("") == ""

    def test_zero(self):
        """Zero amount passes through unchanged."""
        assert fmt_amount_str("0") == "0"

    def test_locale_uses_en_us_in_tests(self):
        """The test fixture forces en_US locale (period decimal, comma thousands)."""
        assert fmt_amount_str("€1234.56") == "€1,234.56"


class TestFmtSingleAmountStr:
    """Tests for fmt_single_amount_str — no multi-commodity splitting."""

    def test_formats_single_currency(self):
        """Left-side currency symbol with 2+ decimals gets formatted."""
        assert fmt_single_amount_str("€3741.81") == "€3,741.81"

    def test_passes_named_through(self):
        """Named commodities are returned unchanged."""
        assert fmt_single_amount_str("0.17500000 BTC") == "0.17500000 BTC"

    def test_passes_comma_separated_through(self):
        """Comma-separated string is NOT split by this function."""
        assert fmt_single_amount_str("£-8.99, €3741.81") == "£-8.99, €3741.81"


class TestSplitRawCommodities:
    """Tests for split_raw_commodities."""

    def test_single_commodity(self):
        """Single commodity returns a one-element list."""
        assert split_raw_commodities("€3741.81") == ["€3741.81"]

    def test_multi_commodity(self):
        """Multi-commodity string is split on ', '."""
        result = split_raw_commodities("£-8.99, €3741.81")
        assert result == ["£-8.99", "€3741.81"]

    def test_six_commodities(self):
        """Full multi-commodity string is split correctly."""
        raw = "$5750.00, 0.17500000 BTC, 28.0000 XDWD, 15.0000 XEON, £-8.99, €3741.81"
        result = split_raw_commodities(raw)
        assert len(result) == 6
        assert "0.17500000 BTC" in result
        assert "15.0000 XEON" in result

    def test_empty_string(self):
        """Empty string returns single-element list with empty string."""
        assert split_raw_commodities("") == [""]

    def test_named_commodity(self):
        """Named commodity is returned as single-element list."""
        assert split_raw_commodities("28.0000 XDWD") == ["28.0000 XDWD"]


class TestSplitMultiCommodityAmounts:
    """Tests for split_multi_commodity_amounts."""

    def test_single_commodity_formatted(self):
        """Single commodity gets formatted and returned in a list."""
        result = split_multi_commodity_amounts("€3741.81")
        assert result == ["€3,741.81"]

    def test_multi_commodity_formatted(self):
        """Each sub-amount is individually formatted."""
        result = split_multi_commodity_amounts("£-8.99, €3741.81")
        assert result == ["£-8.99", "€3,741.81"]

    def test_named_commodities_unchanged(self):
        """Named commodities stay as-is."""
        result = split_multi_commodity_amounts("0.17500000 BTC, 28.0000 XDWD")
        assert result == ["0.17500000 BTC", "28.0000 XDWD"]

    def test_empty_string(self):
        """Empty string returns a list with empty string."""
        assert split_multi_commodity_amounts("") == [""]


class TestGetCommodityName:
    """Tests for get_commodity_name."""

    def test_symbol_commodity(self):
        """Single-char symbol is returned as-is."""
        assert get_commodity_name("€3741.81") == "€"
        assert get_commodity_name("$5750.00") == "$"
        assert get_commodity_name("£-8.99") == "£"

    def test_named_commodity(self):
        """Multi-char commodity code is returned."""
        assert get_commodity_name("0.17500000 BTC") == "BTC"
        assert get_commodity_name("28.0000 XDWD") == "XDWD"

    def test_unparseable_returns_empty(self):
        """Unparseable amounts return empty string."""
        assert get_commodity_name("") == ""
        assert get_commodity_name("not an amount") == ""
