"""Tests for the posting running-balance helpers (issue #142)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from hledger_textual.widgets.posting_sum import (
    collect_posting_totals,
    format_posting_sum,
)


def _row(account: str, amount: str, commodity: str = "€") -> SimpleNamespace:
    """Minimal PostingRow stand-in with the attributes the helper reads."""
    return SimpleNamespace(account=account, amount=amount, commodity=commodity)


def _parse_simple(text: str, commodity: str) -> tuple[Decimal, str] | None:
    """Plain-decimal parser used by most tests."""
    try:
        return Decimal(text), commodity
    except Exception:
        return None


class TestCollectPostingTotals:
    """Tests for collect_posting_totals."""

    def test_sums_balanced_rows(self):
        """Two balancing rows sum to zero."""
        totals, incomplete = collect_posting_totals(
            [_row("expenses:food", "50"), _row("assets:bank", "-50")],
            _parse_simple,
        )
        assert totals == {"€": Decimal("0")}
        assert incomplete is False

    def test_unbalanced_rows(self):
        """A missing leg leaves a visible remainder."""
        totals, incomplete = collect_posting_totals(
            [_row("expenses:food", "50"), _row("assets:bank", "-40")],
            _parse_simple,
        )
        assert totals == {"€": Decimal("10")}
        assert incomplete is False

    def test_skips_rows_without_account(self):
        """A row with an amount but no account is not a posting yet."""
        totals, incomplete = collect_posting_totals(
            [_row("", "50", "€")], _parse_simple
        )
        assert totals == {}
        assert incomplete is False

    def test_invalid_amount_marks_incomplete(self):
        """An unparsable amount is reported instead of being silently dropped."""
        totals, incomplete = collect_posting_totals(
            [_row("expenses:food", "abc")], _parse_simple
        )
        assert totals == {}
        assert incomplete is True

    def test_multiple_commodities_are_kept_apart(self):
        """Each commodity gets its own running sum."""
        totals, _ = collect_posting_totals(
            [
                _row("expenses:food", "50", "€"),
                _row("expenses:book", "20", "$"),
                _row("assets:bank", "-50", "€"),
            ],
            _parse_simple,
        )
        assert totals == {"€": Decimal("0"), "$": Decimal("20")}


class TestFormatPostingSum:
    """Tests for format_posting_sum."""

    def test_balanced_is_green_with_check(self):
        """A zero total is shown as balanced."""
        text = format_posting_sum({"€": Decimal("0")}, False, "€")
        assert text.startswith("Sum: ")
        assert "€0.00" in text
        assert "✓" in text
        assert "[green]" in text

    def test_unbalanced_is_red_with_cross(self):
        """A non-zero total is shown as unbalanced."""
        text = format_posting_sum({"€": Decimal("10")}, False, "€")
        assert "€10.00" in text
        assert "✗" in text
        assert "[red]" in text

    def test_incomplete_marker(self):
        """Unparsable amounts are flagged at the end of the line."""
        text = format_posting_sum({"€": Decimal("10")}, True, "€")
        assert "incomplete" in text

    def test_empty_shows_zero(self):
        """Before any amount is typed the sum shows zero in the default currency."""
        text = format_posting_sum({}, False, "€")
        assert "€0.00" in text
        assert "✓" in text
