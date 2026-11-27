"""Per-year budget totals derived from monthly rows (issue #282).

Year totals sum the displayed monthly :class:`BudgetRow`s, so they can
never disagree with the month columns (no second query, no rounding
drift).  Commodity is the first non-empty month commodity; mixed-commodity
years are summed numerically under that commodity.
"""

from __future__ import annotations

from decimal import Decimal

from hledger_textual.models import BudgetRow


def _year_of(period: str) -> str:
    """Return the calendar year of a ``YYYY-MM`` period label."""
    return period.split("-")[0]


def group_months_by_year(periods: list[str]) -> list[tuple[str, list[int]]]:
    """Group month-period indices by calendar year, preserving order.

    Args:
        periods: Ordered ``YYYY-MM`` period labels.

    Returns:
        ``(year, indices)`` pairs in first-seen order.
    """
    groups: list[tuple[str, list[int]]] = []
    index_by_year: dict[str, int] = {}
    for i, period in enumerate(periods):
        year = _year_of(period)
        if year in index_by_year:
            groups[index_by_year[year]][1].append(i)
        else:
            index_by_year[year] = len(groups)
            groups.append((year, [i]))
    return groups


def sum_year_row(account: str, rows: list[BudgetRow]) -> BudgetRow:
    """Sum monthly rows into one year-total row.

    Args:
        account: Account name for the total row.
        rows: The year's monthly rows in order.
    """
    actual = sum((r.actual for r in rows), Decimal("0"))
    budget = sum((r.budget for r in rows), Decimal("0"))
    commodity = next((r.commodity for r in rows if r.commodity), "")
    return BudgetRow(
        account=account, actual=actual, budget=budget, commodity=commodity
    )


def year_columns(periods: list[str]) -> list[tuple]:
    """Return the render column spec with year totals interleaved.

    Each year group contributes its month columns followed by one
    ``("year", label, indices)`` total column.

    Args:
        periods: Ordered ``YYYY-MM`` period labels.
    """
    spec: list[tuple] = []
    for year, indices in group_months_by_year(periods):
        spec.extend(("month", i) for i in indices)
        spec.append(("year", year, indices))
    return spec
