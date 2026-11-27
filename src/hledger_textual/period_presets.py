"""Named period presets applied through the shared period state (issue #277).

Presets are pure date arithmetic over :class:`PeriodSelection`: given a
reference *today* they return the selection every pane should scope to.
Calendar-year semantics only; fiscal-year offsets belong to issue #279.
"""

from __future__ import annotations

from datetime import date

from hledger_textual.dateutil import prev_month
from hledger_textual.period import (
    PeriodSelection,
    all_selection,
    month_range_selection,
    month_selection,
    range_selection,
    year_selection,
)

#: (preset id, human label) in menu order.
PRESET_DEFS: tuple[tuple[str, str], ...] = (
    ("this-month", "This month"),
    ("last-month", "Last month"),
    ("this-year", "This year"),
    ("last-year", "Last year"),
    ("last-12-months", "Last 12 months"),
    ("ytd", "Year to date"),
    ("all", "All time"),
)


def preset_this_month(today: date) -> PeriodSelection:
    """Return the calendar month containing *today*."""
    return month_selection(today)


def preset_last_month(today: date) -> PeriodSelection:
    """Return the calendar month before *today*'s month."""
    return month_selection(prev_month(today))


def preset_this_year(today: date) -> PeriodSelection:
    """Return the calendar year containing *today*."""
    return year_selection(today.year)


def preset_last_year(today: date) -> PeriodSelection:
    """Return the calendar year before *today*'s year."""
    return year_selection(today.year - 1)


def preset_last_12_months(today: date) -> PeriodSelection:
    """Return the 12-month window ending in *today*'s month (inclusive)."""
    first_month = today.replace(day=1)
    for _ in range(11):
        first_month = prev_month(first_month)
    return month_range_selection(first_month, today)


def preset_ytd(today: date) -> PeriodSelection:
    """Return the year-to-date range (Jan 1 through *today*)."""
    return range_selection(date(today.year, 1, 1), today)


def preset_all_time(today: date) -> PeriodSelection:
    """Return the unbounded selection covering the whole journal."""
    del today  # accepted for a uniform signature
    return all_selection()


_PRESET_FNS = {
    "this-month": preset_this_month,
    "last-month": preset_last_month,
    "this-year": preset_this_year,
    "last-year": preset_last_year,
    "last-12-months": preset_last_12_months,
    "ytd": preset_ytd,
    "all": preset_all_time,
}

__all__ = ["PRESET_DEFS", "get_preset", "list_presets"]


def get_preset(preset_id: str, today: date | None = None) -> PeriodSelection:
    """Return the selection for *preset_id* anchored at *today*.

    Args:
        preset_id: One of the ids in :data:`PRESET_DEFS`.
        today: Reference date; defaults to today.

    Raises:
        KeyError: If *preset_id* is not a known preset.
    """
    try:
        fn = _PRESET_FNS[preset_id]
    except KeyError:
        raise KeyError(f"Unknown period preset: {preset_id!r}") from None
    return fn(today or date.today())


def list_presets() -> list[tuple[str, str]]:
    """Return the preset catalogue as ``(id, label)`` pairs in menu order."""
    return list(PRESET_DEFS)
