"""Date arithmetic utilities."""

from __future__ import annotations

import calendar
import re
from datetime import date

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_iso_date(value: str) -> bool:
    """Return True if value is a syntactically valid YYYY-MM-DD date.

    Args:
        value: The date string to validate.

    Returns:
        True if value matches YYYY-MM-DD AND represents a real calendar date.
    """
    if not _ISO_DATE_RE.match(value):
        return False
    try:
        year, month, day = value.split("-")
        date(int(year), int(month), int(day))
        return True
    except ValueError:
        return False


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


def shift_date_months(d: date, months: int) -> date:
    """Shift a date by *months* months, clamping the day to the target month's last day.

    Args:
        d: The date to shift.
        months: Number of months to shift (positive = forward, negative = backward).

    Returns:
        A new date with the month shifted and the day clamped.
    """
    total_months = d.year * 12 + (d.month - 1) + months
    year = total_months // 12
    month = total_months % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, max_day))
