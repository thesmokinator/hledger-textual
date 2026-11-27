"""Shared period selection owned by the app and used by every pane.

Each pane used to keep its own time anchor (``_current_month`` pinned to
today, a reports window that always ended today, ...), so data outside the
current year was hard to reach and panes disagreed about "now".  This module
defines the single :class:`PeriodSelection` value the app owns; panes derive
their scope from it instead of private anchors (issue #263).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from hledger_textual.dateutil import next_month, prev_month
from hledger_textual.fiscal import fiscal_year_begin, fiscal_year_end_exclusive

#: Kinds of period selection.
PeriodKind = Literal["month", "range", "all"]

_YEAR_RE = re.compile(r"^(\d{4})$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{1,2})$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")

#: Human-facing aliases accepted by :func:`parse_period`.
_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


@dataclass(frozen=True)
class PeriodSelection:
    """A period the whole app is scoped to.

    ``begin``/``end`` follow hledger semantics: ``end`` is **exclusive**.
    ``None`` bounds mean unbounded (used by the ``"all"`` kind).
    """

    kind: PeriodKind
    begin: date | None
    end: date | None
    label: str

    @property
    def period_expr(self) -> str:
        """Return the hledger period expression selecting this period.

        Examples: ``2024-03``, ``2024-01..2024-06``, ``2024-03-05..2024-04-02``.
        Empty string for the unbounded ``"all"`` selection.
        """
        if self.kind == "all" or (self.begin is None and self.end is None):
            return ""
        if self.begin is None:
            return f"..{self._format_inclusive_end()}"
        if self.kind == "month":
            return self._format_inclusive_begin()
        if self.end is None:
            # Open-ended range: everything from the begin bound onwards.
            return f"{self._format_inclusive_begin()}.."
        return self._format_inclusive_span()

    def query(self) -> str:
        """Return the hledger date query for this period (``date:...``)."""
        expr = self.period_expr
        return f"date:{expr}" if expr else ""

    def hledger_args(self) -> tuple[str, ...]:
        """Return the ``-p`` argument tuple scoping hledger to this period."""
        expr = self.period_expr
        return ("-p", expr) if expr else ()

    @staticmethod
    def _format_bound(bound: date) -> str:
        """Format a period bound with the coarsest unambiguous granularity.

        Month-aligned bounds (first day of a month) are rendered as
        ``YYYY-MM`` so queries stay readable; anything else keeps the full
        ``YYYY-MM-DD`` form.
        """
        if bound.day == 1:
            return bound.strftime("%Y-%m")
        return bound.isoformat()

    def _format_inclusive_begin(self) -> str:
        """Format the begin bound as an inclusive hledger expression.

        A month-aligned begin renders as ``YYYY-MM`` (hledger treats it as
        the whole month); any other day keeps ``YYYY-MM-DD``.
        """
        assert self.begin is not None
        return self._format_bound(self.begin)

    def _format_inclusive_end(self) -> str:
        """Format the (exclusive) end bound as an inclusive hledger expression."""
        assert self.end is not None
        if self.end.day == 1:
            return prev_month(self.end).strftime("%Y-%m")
        return (self.end - timedelta(days=1)).isoformat()

    def _format_inclusive_span(self) -> str:
        """Format begin/end (exclusive) as an inclusive hledger span.

        Month-aligned spans collapse to month or year granularity:
        ``2024-01..2024-06`` for a Jan–Jun span, ``2024`` when the span
        covers exactly one calendar year.  Day-precise spans render both
        bounds as inclusive dates.
        """
        assert self.begin is not None and self.end is not None
        if self.begin.day == 1 and self.end.day == 1:
            # Exclusive end at the first of a month -> inclusive month span.
            last_month = prev_month(self.end)
            begin_month = self.begin.year * 12 + self.begin.month - 1
            end_month = last_month.year * 12 + last_month.month - 1
            if begin_month == end_month:
                return self.begin.strftime("%Y-%m")
            if self.begin.month == 1 and last_month.month == 12:
                if last_month.year == self.begin.year:
                    return str(self.begin.year)
                return f"{self.begin.year}..{last_month.year}"
            return (
                f"{self.begin.strftime('%Y-%m')}..{last_month.strftime('%Y-%m')}"
            )
        # Day-precise: hledger's end bound is inclusive, ours is exclusive.
        return f"{self.begin.isoformat()}..{(self.end - timedelta(days=1)).isoformat()}"

    def contains(self, day: date) -> bool:
        """Return True if *day* falls inside this period.

        Args:
            day: The date to test.
        """
        if self.kind == "all":
            return True
        if self.begin is not None and day < self.begin:
            return False
        if self.end is not None and day >= self.end:
            return False
        return True

    def overlaps_months(self, month: date) -> bool:
        """Return True if the calendar month containing *month* intersects this period.

        Args:
            month: Any date inside the month to test (day is ignored).
        """
        if self.kind == "all":
            return True
        month_start = month.replace(day=1)
        month_end = next_month(month_start)
        if self.end is not None and self.end <= month_start:
            return False
        if self.begin is not None and self.begin >= month_end:
            return False
        return True

    def overlaps_span(self, first_date: date | None, last_date: date | None) -> bool:
        """Return True if this period can contain transactions in the journal span.

        Used by the period picker to reject selections that would show an
        empty view (issue #266).  Unbounded sides (and an unknown span) are
        treated as "possibly contains", never as an error.

        Args:
            first_date: First transaction date of the journal, or None.
            last_date: Last transaction date of the journal, or None.
        """
        if self.kind == "all":
            return True
        if first_date is None or last_date is None:
            return True
        if self.end is not None and self.end <= first_date:
            return False
        if self.begin is not None and self.begin > last_date:
            return False
        return True


def month_selection(month: date) -> PeriodSelection:
    """Build a selection covering the calendar month containing *month*.

    Args:
        month: Any date inside the target month (the day is ignored).
    """
    month_start = month.replace(day=1)
    return PeriodSelection(
        kind="month",
        begin=month_start,
        end=next_month(month_start),
        label=month_start.strftime("%B %Y"),
    )


def range_selection(begin: date, end: date) -> PeriodSelection:
    """Build a selection for the inclusive date range ``begin..end``.

    The stored end bound is exclusive (first day after *end*).  A range that
    starts on the first of a month and ends on that month's last day is
    normalised to a month selection so labels and queries stay compact.

    Args:
        begin: First day included in the period.
        end: Last day included in the period.
    """
    if begin > end:
        begin, end = end, begin
    exclusive_end = end + timedelta(days=1)
    if begin.day == 1 and exclusive_end == next_month(begin):
        return month_selection(begin)
    label = (
        f"{begin.isoformat()} \u2192 {end.isoformat()}"
        if begin != end
        else begin.isoformat()
    )
    return PeriodSelection(
        kind="range", begin=begin, end=exclusive_end, label=label
    )


def month_range_selection(first_month: date, last_month: date) -> PeriodSelection:
    """Build a selection covering the inclusive span of calendar months.

    Args:
        first_month: Any date inside the first month of the span.
        last_month: Any date inside the last month of the span.
    """
    if first_month > last_month:
        first_month, last_month = last_month, first_month
    begin = first_month.replace(day=1)
    end_last = last_month.replace(day=1)
    exclusive_end = next_month(end_last)
    return PeriodSelection(
        kind="range",
        begin=begin,
        end=exclusive_end,
        label=_month_range_label(begin, exclusive_end),
    )


def _month_range_label(begin: date, end_exclusive: date) -> str:
    """Return the human label for a month-aligned range.

    A Jan–Dec span of one calendar year is labelled ``2024``; any other span
    names its first and last inclusive months.

    Args:
        begin: First day of the first month of the span.
        end_exclusive: Exclusive end bound (first day after the last month).
    """
    last_month = prev_month(end_exclusive)
    if begin.month == 1 and last_month.month == 12 and begin.year == last_month.year:
        return str(begin.year)
    return f"{begin.strftime('%b %Y')} \u2192 {last_month.strftime('%b %Y')}"


def year_selection(year: int) -> PeriodSelection:
    """Build a selection covering the whole calendar *year*.

    Args:
        year: The calendar year to cover.
    """
    return month_range_selection(date(year, 1, 1), date(year, 12, 1))


def fiscal_year_selection(year: int, start_month: int = 1) -> PeriodSelection:
    """Build a selection covering fiscal year *year* (issue #279).

    The year is labelled by the calendar year it starts in: with an April
    start, ``fiscal_year_selection(2024, 4)`` spans April 2024 through
    March 2025.  A January start matches :func:`year_selection` exactly.

    Args:
        year: Fiscal year label (the calendar year it starts in).
        start_month: First month of the fiscal year (1–12).
    """
    begin = fiscal_year_begin(year, start_month)
    last = prev_month(fiscal_year_end_exclusive(year, start_month))
    return month_range_selection(begin, last)


def all_selection() -> PeriodSelection:
    """Build the unbounded selection covering the whole journal."""
    return PeriodSelection(kind="all", begin=None, end=None, label="All time")


def current_month_selection(today: date | None = None) -> PeriodSelection:
    """Build the selection for the current calendar month.

    Args:
        today: Reference date; defaults to today.
    """
    return month_selection(today or date.today())


def shift_months(selection: PeriodSelection, months: int) -> PeriodSelection:
    """Shift a selection by *months* calendar months.

    Month-aligned selections shift by whole months; day-precise ranges shift
    begin and end keeping their length.  The unbounded ``"all"`` selection is
    returned unchanged.

    Args:
        selection: The selection to shift.
        months: Number of months to shift (negative = backwards).
    """
    if selection.kind == "all" or selection.begin is None:
        return selection
    if selection.kind == "month":
        return month_selection(_shift_month_anchor(selection.begin, months))
    begin = _shift_date_months(selection.begin, months)
    if selection.end is None:
        return PeriodSelection(
            kind="range", begin=begin, end=None, label=selection.label
        )
    length = (selection.end - selection.begin).days
    end = begin + timedelta(days=length)
    if selection.begin.day == 1 and selection.end.day == 1:
        # Month-aligned: recompute the label so the shifted window stays honest.
        label = _month_range_label(begin, end)
    else:
        label = selection.label
    return PeriodSelection(kind="range", begin=begin, end=end, label=label)


def shift_years(selection: PeriodSelection, years: int) -> PeriodSelection:
    """Shift a selection by *years* calendar years.

    Args:
        selection: The selection to shift.
        years: Number of years to shift (negative = backwards).
    """
    return shift_months(selection, years * 12)


def _shift_month_anchor(anchor: date, months: int) -> date:
    """Shift a month anchor by *months*, returning the first of the target month."""
    total = anchor.year * 12 + (anchor.month - 1) + months
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


def _shift_date_months(d: date, months: int) -> date:
    """Shift a date by *months*, clamping the day to the target month's last day."""
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    max_day = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(d.day, max_day))


def parse_period(text: str, today: date | None = None) -> PeriodSelection | None:
    """Parse a user-supplied period expression into a :class:`PeriodSelection`.

    Accepted formats (issue #266/#268):

    - ``2024`` — the whole year
    - ``2024-03`` (or ``2024-3``) — one month
    - ``2024-01..2024-06`` — a month span
    - ``2024-03-05..2024-04-02`` — a day range
    - ``this month`` / ``last month`` / ``next month``
    - ``this year`` / ``last year`` / ``next year``
    - ``ytd`` — from the first of January to today
    - ``all`` — the whole journal

    Args:
        text: The period expression typed by the user.
        today: Reference date for relative periods; defaults to today.

    Returns:
        The parsed selection, or ``None`` when *text* is not a valid period.
    """
    text = text.strip().lower()
    if not text:
        return None
    today = today or date.today()

    if text in ("all", "all time"):
        return all_selection()
    if text in ("this month", "current month"):
        return month_selection(today)
    if text == "last month":
        return month_selection(prev_month(today))
    if text == "next month":
        return month_selection(next_month(today))
    if text in ("this year", "current year"):
        return year_selection(today.year)
    if text == "last year":
        return year_selection(today.year - 1)
    if text == "next year":
        return year_selection(today.year + 1)
    if text == "ytd":
        return range_selection(date(today.year, 1, 1), today)

    if ".." in text:
        begin_text, _, end_text = text.partition("..")
        begin = _parse_bound(begin_text)
        end = _parse_bound(end_text)
        if begin is None or end is None:
            return None
        if begin > end:
            begin, end = end, begin
        # "2024-01..2024-06" is a month span; "2024..2025" a year span.
        if _YEAR_RE.match(begin_text.strip()) and _YEAR_RE.match(end_text.strip()):
            return year_range(int(begin_text), int(end_text))
        if _MONTH_RE.match(begin_text.strip()) and _MONTH_RE.match(end_text.strip()):
            return month_range_selection(begin, end)
        return range_selection(begin, end)

    year_match = _YEAR_RE.match(text)
    if year_match:
        return year_selection(int(year_match.group(1)))

    month_match = _MONTH_RE.match(text)
    if month_match:
        year, month = int(month_match.group(1)), int(month_match.group(2))
        if not 1 <= month <= 12:
            return None
        return month_selection(date(year, month, 1))

    date_match = _DATE_RE.match(text)
    if date_match:
        year, month, day = (int(part) for part in date_match.groups())
        try:
            single = date(year, month, day)
        except ValueError:
            return None
        return range_selection(single, single)

    return _parse_month_name(text, today)


def year_range(first_year: int, last_year: int) -> PeriodSelection:
    """Build a selection covering whole calendar years ``first..last`` inclusive.

    Args:
        first_year: First calendar year of the span.
        last_year: Last calendar year of the span.
    """
    if first_year > last_year:
        first_year, last_year = last_year, first_year
    begin = date(first_year, 1, 1)
    exclusive_end = date(last_year + 1, 1, 1)
    label = (
        f"{first_year}" if first_year == last_year else f"{first_year} \u2192 {last_year}"
    )
    return PeriodSelection(
        kind="range", begin=begin, end=exclusive_end, label=label
    )


def _parse_month_name(text: str, today: date) -> PeriodSelection | None:
    """Parse a bare English month name (``march``, ``mar 2024``)."""
    match = re.match(r"^([a-z]+)(?:\s+(\d{4}))?$", text)
    if not match:
        return None
    name, year_text = match.groups()
    month = _MONTH_NAMES.get(name)
    if month is None:
        return None
    year = int(year_text) if year_text else today.year
    return month_selection(date(year, month, 1))


def period_from_flags(
    period: str | None, begin: str | None, end: str | None
) -> PeriodSelection:
    """Build the initial period from the CLI flags ``-p``/``-b``/``-e`` (issue #268).

    ``-b``/``-e`` take precedence over ``-p`` when given (matching hledger,
    where explicit bounds override the period expression's bounds).  Bounds
    accept ``YYYY``, ``YYYY-MM`` and ``YYYY-MM-DD``; ``--end`` is **exclusive**,
    exactly like hledger's ``-e``.

    Args:
        period: Value of ``-p/--period`` (may be None).
        begin: Value of ``-b/--begin`` (may be None).
        end: Value of ``-e/--end`` (may be None).

    Returns:
        The selection covering the requested period.

    Raises:
        ValueError: If a flag value cannot be parsed.
    """
    if begin or end:
        begin_date = _parse_bound(begin) if begin else None
        end_date = _parse_bound(end) if end else None
        if begin and begin_date is None:
            raise ValueError(f"Invalid --begin value: {begin!r}")
        if end and end_date is None:
            raise ValueError(f"Invalid --end value: {end!r}")
        if begin_date is not None and end_date is not None:
            if begin_date > end_date:
                begin_date, end_date = end_date, begin_date
            if begin_date.day == 1 and end_date.day == 1:
                label = _month_range_label(begin_date, end_date)
            else:
                label = (
                    f"{begin_date.isoformat()} \u2192 "
                    f"{(end_date - timedelta(days=1)).isoformat()}"
                )
            return PeriodSelection(
                kind="range", begin=begin_date, end=end_date, label=label
            )
        if begin_date is not None:
            return PeriodSelection(
                kind="range",
                begin=begin_date,
                end=None,
                label=f"from {begin_date.isoformat()}",
            )
        return PeriodSelection(
            kind="range",
            begin=None,
            end=end_date,
            label=f"to {(end_date - timedelta(days=1)).isoformat()}",
        )
    if period:
        selection = parse_period(period)
        if selection is None:
            raise ValueError(f"Invalid period: {period!r}")
        return selection
    raise ValueError("No period flags given")


def _parse_bound(text: str) -> date | None:
    """Parse one side of a ``..`` period expression.

    Accepts ``YYYY``, ``YYYY-MM`` and ``YYYY-MM-DD``; year and month bounds
    resolve to their first day.
    """
    text = text.strip()
    year_match = _YEAR_RE.match(text)
    if year_match:
        return date(int(year_match.group(1)), 1, 1)
    month_match = _MONTH_RE.match(text)
    if month_match:
        year, month = int(month_match.group(1)), int(month_match.group(2))
        if not 1 <= month <= 12:
            return None
        return date(year, month, 1)
    date_match = _DATE_RE.match(text)
    if date_match:
        year, month, day = (int(part) for part in date_match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None
