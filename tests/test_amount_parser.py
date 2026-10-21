"""Unit tests for the amount/cost parser extracted from the transaction form.

These tests exercise :mod:`hledger_textual.amount_parser` directly, without
mounting any UI and without requiring the hledger binary.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hledger_textual.amount_parser import (
    extract_commodity_and_qty,
    load_journal_commodity_styles,
    parse_amount_str,
    parse_simple_amount_str,
)


class TestParseAmountStr:
    """Tests for parse_amount_str across the accepted amount grammar."""

    def test_integer_amount(self):
        """A bare integer uses the default commodity."""
        amt = parse_amount_str("100", "€")
        assert amt is not None
        assert amt.quantity == Decimal("100")
        assert amt.commodity == "€"

    def test_decimal_amount(self):
        """A decimal amount keeps its precision."""
        amt = parse_amount_str("50.25", "€")
        assert amt is not None
        assert amt.quantity == Decimal("50.25")

    def test_european_format_with_default_style(self, tmp_path):
        """European grouping/decimal marks are honoured via journal styles."""
        journal = tmp_path / "test.journal"
        journal.write_text("commodity EUR 1.000,00\n", encoding="utf-8")
        styles = load_journal_commodity_styles(journal)
        amt = parse_amount_str("1.000,50 EUR", "€", styles)
        assert amt is not None
        assert amt.quantity == Decimal("1000.50")
        assert amt.commodity == "EUR"

    def test_currency_before_amount(self):
        """A currency symbol may precede the quantity."""
        amt = parse_amount_str("€50.00", "$")
        assert amt is not None
        assert (amt.quantity, amt.commodity) == (Decimal("50.00"), "€")

    def test_currency_after_amount(self):
        """A commodity name may follow the quantity."""
        amt = parse_amount_str("50.00 EUR", "$")
        assert amt is not None
        assert (amt.quantity, amt.commodity) == (Decimal("50.00"), "EUR")

    def test_unit_cost_annotation(self):
        """``@`` unit cost is converted to a total cost."""
        amt = parse_amount_str("-10 STCK @ €20.00", "€")
        assert amt is not None
        assert amt.quantity == Decimal("-10")
        assert amt.cost is not None
        assert amt.cost.quantity == Decimal("200.00")

    def test_total_cost_annotation(self):
        """``@@`` total cost is kept as the total cost."""
        amt = parse_amount_str("-10 STCK @@ €200.00", "€")
        assert amt is not None
        assert amt.cost is not None
        assert amt.cost.quantity == Decimal("200.00")

    def test_negative_amount(self):
        """Negative amounts keep their sign."""
        amt = parse_amount_str("-50.00", "€")
        assert amt is not None
        assert amt.quantity == Decimal("-50.00")

    def test_negative_commodity_amount(self):
        """Negative quantity with a named commodity."""
        amt = parse_amount_str("-10.00 STCK", "€")
        assert amt is not None
        assert (amt.quantity, amt.commodity) == (Decimal("-10.00"), "STCK")

    @pytest.mark.parametrize("raw", ["", "abc", "-10 STCK @@ invalid"])
    def test_unparseable_amounts_return_none(self, raw):
        """Unparseable input returns None instead of raising."""
        assert parse_amount_str(raw, "€") is None


class TestParseSimpleAmountStr:
    """Tests for parse_simple_amount_str (no cost annotation)."""

    def test_symbol_prefixed(self):
        """Symbol-prefixed amounts parse to that commodity."""
        amt = parse_simple_amount_str("€742.59", "")
        assert amt is not None
        assert (amt.quantity, amt.commodity) == (Decimal("742.59"), "€")

    def test_plain_number_uses_default_commodity(self):
        """Plain numbers fall back to the default commodity."""
        amt = parse_simple_amount_str("742.59", "€")
        assert amt is not None
        assert (amt.quantity, amt.commodity) == (Decimal("742.59"), "€")


class TestExtractCommodityAndQty:
    """Tests for extract_commodity_and_qty."""

    def test_plain_and_currency_amounts_return_none(self):
        """Plain numbers and symbol amounts are not named commodities."""
        assert extract_commodity_and_qty("50.00") is None
        assert extract_commodity_and_qty("€742.55") is None

    def test_named_commodity(self):
        """Quantity plus named commodity is extracted with sign."""
        assert extract_commodity_and_qty("-5 XEON") == (Decimal("-5"), "XEON", None)

    def test_total_cost_proceeds(self):
        """``@@`` proceeds are the total cost."""
        result = extract_commodity_and_qty("-5 XEON @@ €200")
        assert result == (Decimal("-5"), "XEON", Decimal("200"))

    def test_unit_cost_proceeds(self):
        """``@`` proceeds are unit cost times quantity."""
        result = extract_commodity_and_qty("-5 XEON @ €10")
        assert result == (Decimal("-5"), "XEON", Decimal("50"))


class TestLoadJournalCommodityStyles:
    """Tests for load_journal_commodity_styles."""

    def test_missing_file_returns_empty(self, tmp_path):
        """A missing journal yields no styles."""
        assert load_journal_commodity_styles(tmp_path / "missing.journal") == {}

    def test_commodity_directive_style(self, tmp_path):
        """A European commodity directive yields a comma decimal style."""
        journal = tmp_path / "test.journal"
        journal.write_text("commodity €1.000,00\n", encoding="utf-8")
        styles = load_journal_commodity_styles(journal)
        assert styles["€"].decimal_mark == ","
