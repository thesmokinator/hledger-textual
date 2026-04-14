"""Tests for the shared amount parsing utility."""

from __future__ import annotations

from decimal import Decimal

import pytest

from hledger_textual.amountutil import _normalize_number_string, parse_amount_string


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

    # --- European format (comma as decimal, dot as thousands) ---

    def test_european_left_commodity_no_thousands(self):
        """Parse European amount without thousands separator: €100,00 → 100.00."""
        qty, commodity = parse_amount_string("€100,00")
        assert qty == Decimal("100.00")
        assert commodity == "€"

    def test_european_left_commodity_with_thousands(self):
        """Parse European amount with thousands separator: €1.000,00 → 1000.00."""
        qty, commodity = parse_amount_string("€1.000,00")
        assert qty == Decimal("1000.00")
        assert commodity == "€"

    def test_european_left_commodity_large(self):
        """Parse large European amount with multiple thousands separators."""
        qty, commodity = parse_amount_string("€1.234.567,89")
        assert qty == Decimal("1234567.89")
        assert commodity == "€"

    def test_european_right_commodity(self):
        """Parse European amount with right-side commodity: 1.000,00 EUR → 1000.00."""
        qty, commodity = parse_amount_string("1.000,00 EUR")
        assert qty == Decimal("1000.00")
        assert commodity == "EUR"

    def test_european_negative(self):
        """Parse negative European amount: €-150,50 → -150.50."""
        qty, commodity = parse_amount_string("€-150,50")
        assert qty == Decimal("-150.50")
        assert commodity == "€"

    def test_european_salary(self):
        """Parse European salary amount matching the fixture: €3.000,00 → 3000.00."""
        qty, commodity = parse_amount_string("€3.000,00")
        assert qty == Decimal("3000.00")
        assert commodity == "€"


class TestNormalizeNumberString:
    """Tests for _normalize_number_string."""

    def test_us_with_thousands(self):
        """US format with thousands separator: 1,000.00 → 1000.00."""
        assert _normalize_number_string("1,000.00") == "1000.00"

    def test_us_plain(self):
        """Plain decimal: 150.00 → 150.00."""
        assert _normalize_number_string("150.00") == "150.00"

    def test_european_with_thousands(self):
        """European format: 1.000,00 → 1000.00."""
        assert _normalize_number_string("1.000,00") == "1000.00"

    def test_european_no_thousands(self):
        """European decimal-only: 100,00 → 100.00."""
        assert _normalize_number_string("100,00") == "100.00"

    def test_european_large(self):
        """European with multiple thousands separators: 1.234.567,89 → 1234567.89."""
        assert _normalize_number_string("1.234.567,89") == "1234567.89"

    def test_negative_european(self):
        """Negative European: -1.000,00 → -1000.00."""
        assert _normalize_number_string("-1.000,00") == "-1000.00"

    def test_negative_us(self):
        """Negative US: -1,000.00 → -1000.00."""
        assert _normalize_number_string("-1,000.00") == "-1000.00"

    def test_thousands_comma_only(self):
        """Comma-only with 3 trailing digits: thousands separator."""
        assert _normalize_number_string("1,000") == "1000"

    def test_plain_integer(self):
        """Plain integer with no separators passes through unchanged."""
        assert _normalize_number_string("3000") == "3000"


# ---------------------------------------------------------------------------
# Edge cases: precision, large amounts, multi-currency
# ---------------------------------------------------------------------------


class TestParseAmountStringEdgeCases:
    """Precision, large amounts, and multi-currency edge cases."""

    def test_nine_digit_us_amount(self):
        """Parse a 9-digit US amount with three thousands separators."""
        qty, commodity = parse_amount_string("999,999,999.99 USD")
        assert qty == Decimal("999999999.99")
        assert commodity == "USD"

    def test_sub_cent_precision(self):
        """Parse an amount with 3 decimal places (sub-cent)."""
        qty, commodity = parse_amount_string("$0.001")
        assert qty == Decimal("0.001")
        assert commodity == "$"

    def test_bitcoin_style_8_decimals(self):
        """Parse a Bitcoin-style amount with 8 decimal places."""
        qty, commodity = parse_amount_string("0.00100000 BTC")
        assert qty == Decimal("0.00100000")
        assert commodity == "BTC"

    def test_negative_right_commodity(self):
        """Parse a negative amount with right-side commodity."""
        qty, commodity = parse_amount_string("-1,500.75 EUR")
        assert qty == Decimal("-1500.75")
        assert commodity == "EUR"

    def test_integer_no_decimal(self):
        """Parse an integer amount with no decimal point."""
        qty, commodity = parse_amount_string("100 USD")
        assert qty == Decimal("100")
        assert commodity == "USD"

    def test_european_nine_digit(self):
        """Parse a large European amount: 999.999.999,99 EUR."""
        qty, commodity = parse_amount_string("999.999.999,99 EUR")
        assert qty == Decimal("999999999.99")
        assert commodity == "EUR"


class TestDecimalArithmeticInvariants:
    """Decimal arithmetic properties relevant to budget rounding."""

    def test_thirds_rounding(self):
        """3 × 33.33 should equal 99.99, not 100 (no implicit rounding)."""
        third = Decimal("33.33")
        total = third * 3
        assert total == Decimal("99.99")
        assert total != Decimal("100")

    def test_large_sum_precision(self):
        """Sum of large Decimal values preserves full precision."""
        a = Decimal("999999999.99")
        b = Decimal("0.01")
        assert a + b == Decimal("1000000000.00")

    def test_negative_budget_delta(self):
        """Negative minus positive stays negative (overspend scenario)."""
        actual = Decimal("-200.00")
        budget = Decimal("100.00")
        delta = actual - budget
        assert delta == Decimal("-300.00")
        assert delta < 0
