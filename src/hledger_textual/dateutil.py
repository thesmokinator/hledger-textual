"""Date arithmetic utilities."""

from __future__ import annotations

import calendar
from datetime import date


def prev_month(d: date) -> date:
    """Return the first day of the month before *d*.

    Args:
        d: A date whose month to decrement.

    Returns:
        A new date set to the first of the previous month.
    """
    month, year = d.month - 1, d.year
    if month < 1:
        month, year = 12, year - 1
    return d.replace(year=year, month=month, day=1)


def next_month(d: date) -> date:
    """Return the first day of the month after *d*.

    Args:
        d: A date whose month to increment.

    Returns:
        A new date set to the first of the next month.
    """
    month, year = d.month + 1, d.year
    if month > 12:
        month, year = 1, year + 1
    return d.replace(year=year, month=month, day=1)


def add_months(d: date, months: int) -> date:
    """Return *d* shifted by *months* months, clamping day to the last valid day.

    Args:
        d: The starting date.
        months: Number of months to add (may be negative).

    Returns:
        A new date shifted by the given number of months.
    """
    total_months = d.year * 12 + (d.month - 1) + months
    year = total_months // 12
    month = total_months % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    return d.replace(year=year, month=month, day=min(d.day, max_day))


def add_years(d: date, years: int) -> date:
    """Return *d* shifted by *years* years, clamping day to the last valid day.

    Args:
        d: The starting date.
        years: Number of years to add (may be negative).

    Returns:
        A new date shifted by the given number of years.
    """
    year = d.year + years
    max_day = calendar.monthrange(year, d.month)[1]
    return d.replace(year=year, day=min(d.day, max_day))
