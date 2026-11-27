"""Fiscal year boundaries for non-calendar year starts (issue #279).

hledger has no fiscal-year flag, so the offset lives here: a fiscal year
is labelled by the calendar year it starts in (``FY2024`` runs April 2024
through March 2025 when the start month is April).
"""

from __future__ import annotations

from datetime import date

from hledger_textual.period import PeriodSelection, range_selection


def fiscal_year_of(day: date, start_month: int) -> int:
    """Return the fiscal year label containing *day*.

    Args:
        day: The date to classify.
        start_month: First month of the fiscal year (1–12).
    """
    if day.month >= start_month:
        return day.year
    return day.year - 1


def fiscal_year_begin(year: int, start_month: int) -> date:
    """Return the first day of fiscal year *year*.

    Args:
        year: Fiscal year label (the calendar year it starts in).
        start_month: First month of the fiscal year (1–12).
    """
    return date(year, start_month, 1)


def fiscal_year_end_exclusive(year: int, start_month: int) -> date:
    """Return the exclusive end bound of fiscal year *year*.

    Args:
        year: Fiscal year label (the calendar year it starts in).
        start_month: First month of the fiscal year (1–12).
    """
    total = year * 12 + (start_month - 1) + 12
    end_year, end_month = divmod(total, 12)
    return date(end_year, end_month + 1, 1)


def fiscal_ytd(today: date, start_month: int) -> PeriodSelection:
    """Return the year-to-date selection for a fiscal year start.

    Spans the first day of the current fiscal year through *today*.

    Args:
        today: Reference date (the end of the range).
        start_month: First month of the fiscal year (1–12).
    """
    return range_selection(
        fiscal_year_begin(fiscal_year_of(today, start_month), start_month),
        today,
    )
