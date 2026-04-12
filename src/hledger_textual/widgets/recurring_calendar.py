"""Calendar view widget for recurring transactions."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from hledger_textual.hledger import HledgerError, load_transactions
from hledger_textual.models import RecurringRule
from hledger_textual.widgets.formatting import fmt_amount_str
from hledger_textual.recurring import (
    SUPPORTED_PERIODS,
    _generate_occurrences,
    _get_occurrence_dates_hledger,
)

_PENDING = "\u25cf"
_GENERATED = "\u2713"


@dataclass
class CalendarEntry:
    """A recurring transaction entry for a specific day."""

    day: date
    rule: RecurringRule
    pending: bool

    @property
    def amount_str(self) -> str:
        """Return the first posting amount formatted for display."""
        for posting in self.rule.postings:
            if posting.amounts:
                return fmt_amount_str(posting.amounts[0].format())
        return ""


class RecurringCalendar(Widget, can_focus=True):
    """Monthly calendar showing recurring transaction markers."""

    def __init__(
        self,
        rules: list[RecurringRule],
        journal_file: Path,
        **kwargs,
    ) -> None:
        """Initialize the calendar widget.

        Args:
            rules: List of recurring rules to display.
            journal_file: Path to the journal file.
        """
        super().__init__(**kwargs)
        self._rules = rules
        self._journal_file = journal_file
        today = date.today()
        self._year = today.year
        self._month = today.month

    def compose(self) -> ComposeResult:
        """Create the calendar layout."""
        yield Static("", id="cal-header")
        yield VerticalScroll(Static("", id="cal-details"), id="cal-scroll")

    def on_mount(self) -> None:
        """Render the initial calendar."""
        self._refresh()

    def update_rules(self, rules: list[RecurringRule]) -> None:
        """Update the rules and refresh the display.

        Args:
            rules: New list of recurring rules.
        """
        self._rules = rules
        self._refresh()

    def prev_month(self) -> None:
        """Navigate to the previous month."""
        if self._month == 1:
            self._month = 12
            self._year -= 1
        else:
            self._month -= 1
        self._refresh()

    def next_month(self) -> None:
        """Navigate to the next month."""
        if self._month == 12:
            self._month = 1
            self._year += 1
        else:
            self._month += 1
        self._refresh()

    def _refresh(self) -> None:
        """Rebuild the calendar grid and details."""
        entries = self._compute_entries()
        self._render_header(entries)
        self._render_details(entries)

    def _render_header(self, entries: list[CalendarEntry]) -> None:
        """Render month title and calendar grid.

        Args:
            entries: List of calendar entries for this month.
        """
        month_name = calendar.month_name[self._month]
        title = f"{month_name} {self._year}"

        # Build day lookup
        day_entries: dict[int, list[CalendarEntry]] = {}
        for entry in entries:
            day_entries.setdefault(entry.day.day, []).append(entry)

        cal = calendar.Calendar(firstweekday=0)
        weeks = cal.monthdayscalendar(self._year, self._month)

        lines = [
            f"{'[<] Prev':20s}{title:^20s}{'Next [>]':>20s}",
            "",
            "  Mo   Tu   We   Th   Fr   Sa   Su",
        ]
        for week in weeks:
            cells: list[str] = []
            for day in week:
                if day == 0:
                    cells.append("     ")
                elif day in day_entries:
                    has_pending = any(e.pending for e in day_entries[day])
                    marker = _PENDING if has_pending else _GENERATED
                    cells.append(f" {day:>2}{marker} ")
                else:
                    cells.append(f" {day:>2}  ")
            lines.append("".join(cells))

        lines.append("")
        lines.append(f"  {_PENDING} Pending   {_GENERATED} Generated")

        header = self.query_one("#cal-header", Static)
        header.update("\n".join(lines))

    def _render_details(self, entries: list[CalendarEntry]) -> None:
        """Render the transaction list below the calendar.

        Args:
            entries: List of calendar entries for this month.
        """
        if not entries:
            details = self.query_one("#cal-details", Static)
            details.update("\n  No recurring transactions this month.")
            return

        entries.sort(key=lambda e: (e.day, e.rule.description))

        lines: list[str] = []
        current_day: date | None = None
        for entry in entries:
            if entry.day != current_day:
                current_day = entry.day
                sep = "\u2500" * 40
                lines.append(f"\n  {current_day.isoformat()} {sep}")
            marker = _PENDING if entry.pending else _GENERATED
            amount = entry.amount_str
            period = entry.rule.period_expr
            lines.append(f"  {marker} {entry.rule.description:<24s} {amount:>12s}  {period}")

        details = self.query_one("#cal-details", Static)
        details.update("\n".join(lines))

    def _compute_entries(self) -> list[CalendarEntry]:
        """Compute all recurring entries for the current month.

        Returns:
            List of CalendarEntry instances for the displayed month.
        """
        _, last_day = calendar.monthrange(self._year, self._month)
        month_start = date(self._year, self._month, 1)
        month_end = date(self._year, self._month, last_day)

        entries: list[CalendarEntry] = []

        for rule in self._rules:
            if not rule.start_date:
                continue

            try:
                rule_start = date.fromisoformat(rule.start_date)
            except ValueError:
                continue

            if rule_start > month_end:
                continue

            if rule.end_date:
                try:
                    rule_end = date.fromisoformat(rule.end_date)
                    if rule_end < month_start:
                        continue
                except ValueError:
                    pass

            occ_end = month_end
            if rule.end_date:
                try:
                    occ_end = min(occ_end, date.fromisoformat(rule.end_date))
                except ValueError:
                    pass

            if rule.period_expr in SUPPORTED_PERIODS:
                occurrences = _generate_occurrences(rule_start, rule.period_expr, occ_end)
            else:
                occurrences = _get_occurrence_dates_hledger(rule, rule_start, occ_end)

            month_occurrences = [d for d in occurrences if d.month == self._month and d.year == self._year]

            generated_dates = self._get_generated_dates(rule)

            for occ in month_occurrences:
                entries.append(CalendarEntry(
                    day=occ,
                    rule=rule,
                    pending=occ.isoformat() not in generated_dates,
                ))

        return entries

    def _get_generated_dates(self, rule: RecurringRule) -> set[str]:
        """Load dates of already-generated transactions for a rule.

        Args:
            rule: The recurring rule.

        Returns:
            Set of ISO date strings.
        """
        try:
            txns = load_transactions(
                self._journal_file, query=f"tag:rule-id={rule.rule_id}"
            )
            return {txn.date for txn in txns}
        except HledgerError:
            return set()
