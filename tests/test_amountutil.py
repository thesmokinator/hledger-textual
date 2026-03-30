"""Tests for the shared amount parsing utility."""

from __future__ import annotations

from decimal import Decimal

import pytest

from hledger_textual.amountutil import parse_amount_string


class TestParseAmountString:
    """Tests for parse_amount_string."""

    def test_left_commodity(self):
        """Parse amount with left-side commodity symbol."""
        qty, commodity = parse_amount_string("€800.00")
        assert qty == Decimal("800.00")
        assert commodity == "€"

    def test_right_commodity(self):
        """Parse amount with right-side commodity code."""
        qty, commodity = parse_amount_string("800.00EUR")
        assert qty == Decimal("800.00")
        assert commodity == "EUR"

    def test_dollar(self):
        """Parse dollar amount."""
        qty, commodity = parse_amount_string("$150.50")
        assert qty == Decimal("150.50")
        assert commodity == "$"

    def test_negative(self):
        """Parse negative amount."""
        qty, commodity = parse_amount_string("€-50.00")
        assert qty == Decimal("-50.00")
        assert commodity == "€"

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped."""
        qty, commodity = parse_amount_string("  €100.00  ")
        assert qty == Decimal("100.00")
        assert commodity == "€"

    def test_left_commodity_with_thousands_separator(self):
        """Parse amount with left-side commodity and thousands separator."""
        qty, commodity = parse_amount_string("$1,320.28")
        assert qty == Decimal("1320.28")
        assert commodity == "$"

    def test_left_commodity_negative_with_thousands_separator(self):
        """Parse negative amount with left-side commodity and thousands separator."""
        qty, commodity = parse_amount_string("$-1,536.75")
        assert qty == Decimal("-1536.75")
        assert commodity == "$"

    def test_right_commodity_with_thousands_separator(self):
        """Parse amount with right-side commodity and thousands separator."""
        qty, commodity = parse_amount_string("1,320.28EUR")
        assert qty == Decimal("1320.28")
        assert commodity == "EUR"

    def test_large_amount_with_thousands_separators(self):
        """Parse large amount with multiple thousands separators."""
        qty, commodity = parse_amount_string("€1,000,000.00")
        assert qty == Decimal("1000000.00")
        assert commodity == "€"

    def test_empty_raises(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError):
            parse_amount_string("")

    def test_invalid_raises(self):
        """Unparseable string raises ValueError."""
        with pytest.raises(ValueError):
            parse_amount_string("notanamount")
