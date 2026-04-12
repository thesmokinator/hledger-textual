"""Tests for recurring calendar widget logic."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch


from hledger_textual.models import (
    Amount,
    Posting,
    RecurringRule,
    TransactionStatus,
)
from hledger_textual.widgets.recurring_calendar import CalendarEntry, RecurringCalendar


def _make_rule(
    rule_id: str = "test-001",
    description: str = "Test rule",
    period: str = "monthly",
    start: str = "2026-01-01",
    end: str | None = None,
    amount: str = "100.00",
    commodity: str = "\u20ac",
) -> RecurringRule:
    """Create a test recurring rule."""
    return RecurringRule(
        rule_id=rule_id,
        period_expr=period,
        description=description,
        start_date=start,
        end_date=end,
        postings=[
            Posting(
                account="expenses:test",
                amounts=[Amount(commodity=commodity, quantity=Decimal(amount))],
            ),
            Posting(account="assets:bank", amounts=[]),
        ],
        status=TransactionStatus.UNMARKED,
    )


class TestCalendarEntry:
    """Tests for CalendarEntry dataclass."""

    def test_amount_str_with_posting(self) -> None:
        """Should return formatted amount from first posting."""
        rule = _make_rule(amount="500.00")
        entry = CalendarEntry(day=date(2026, 3, 1), rule=rule, pending=True)
        assert "\u20ac" in entry.amount_str
        assert "500" in entry.amount_str

    def test_amount_str_empty_postings(self) -> None:
        """Should return empty string when no amounts."""
        rule = _make_rule()
        rule.postings = [Posting(account="test", amounts=[])]
        entry = CalendarEntry(day=date(2026, 3, 1), rule=rule, pending=True)
        assert entry.amount_str == ""


class TestComputeEntries:
    """Tests for RecurringCalendar._compute_entries logic."""

    def _make_calendar(self, rules: list[RecurringRule]) -> RecurringCalendar:
        """Create a calendar widget without mounting."""
        cal = RecurringCalendar.__new__(RecurringCalendar)
        cal._rules = rules
        cal._journal_file = Path("/tmp/test.journal")
        cal._year = 2026
        cal._month = 3
        return cal

    @patch("hledger_textual.widgets.recurring_calendar.load_transactions")
    def test_monthly_rule_one_entry_per_month(self, mock_load) -> None:
        """Monthly rule should produce one entry per month."""
        mock_load.return_value = []
        rule = _make_rule(start="2026-01-01")
        cal = self._make_calendar([rule])
        entries = cal._compute_entries()
        assert len(entries) == 1
        assert entries[0].day == date(2026, 3, 1)
        assert entries[0].pending is True

    @patch("hledger_textual.widgets.recurring_calendar.load_transactions")
    def test_rule_not_started_yet(self, mock_load) -> None:
        """Rule starting after the displayed month should have no entries."""
        mock_load.return_value = []
        rule = _make_rule(start="2026-06-01")
        cal = self._make_calendar([rule])
        entries = cal._compute_entries()
        assert len(entries) == 0

    @patch("hledger_textual.widgets.recurring_calendar.load_transactions")
    def test_rule_ended_before_month(self, mock_load) -> None:
        """Rule that ended before the displayed month should have no entries."""
        mock_load.return_value = []
        rule = _make_rule(start="2026-01-01", end="2026-02-15")
        cal = self._make_calendar([rule])
        entries = cal._compute_entries()
        assert len(entries) == 0

    @patch("hledger_textual.widgets.recurring_calendar.load_transactions")
    def test_generated_entry_marked_not_pending(self, mock_load) -> None:
        """Entry with matching generated transaction should not be pending."""
        from hledger_textual.models import Transaction

        mock_load.return_value = [
            Transaction(index=0, date="2026-03-01", description="Test rule")
        ]
        rule = _make_rule(start="2026-01-01")
        cal = self._make_calendar([rule])
        entries = cal._compute_entries()
        assert len(entries) == 1
        assert entries[0].pending is False

    @patch("hledger_textual.widgets.recurring_calendar.load_transactions")
    def test_multiple_rules_same_day(self, mock_load) -> None:
        """Multiple rules on the same day should produce multiple entries."""
        mock_load.return_value = []
        rule1 = _make_rule(rule_id="r1", description="Rent", start="2026-01-01")
        rule2 = _make_rule(rule_id="r2", description="Insurance", start="2026-01-01")
        cal = self._make_calendar([rule1, rule2])
        entries = cal._compute_entries()
        assert len(entries) == 2

    @patch("hledger_textual.widgets.recurring_calendar.load_transactions")
    def test_weekly_rule_multiple_entries(self, mock_load) -> None:
        """Weekly rule should produce ~4 entries in a month."""
        mock_load.return_value = []
        rule = _make_rule(period="weekly", start="2026-03-01")
        cal = self._make_calendar([rule])
        entries = cal._compute_entries()
        # March starts on Sunday, weekly from March 1 gives: 1, 8, 15, 22, 29
        assert len(entries) == 5

    @patch("hledger_textual.widgets.recurring_calendar.load_transactions")
    def test_no_start_date_skipped(self, mock_load) -> None:
        """Rule without start_date should be skipped."""
        mock_load.return_value = []
        rule = _make_rule(start="2026-01-01")
        rule.start_date = None
        cal = self._make_calendar([rule])
        entries = cal._compute_entries()
        assert len(entries) == 0
