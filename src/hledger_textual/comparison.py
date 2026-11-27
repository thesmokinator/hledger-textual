"""Year-over-year comparison columns for financial reports (issue #278).

Pure computation over :class:`ReportData` display strings: the trailing
``Δ`` column is last-column minus first-column per commodity, ``Δ%`` the
corresponding growth rate (``"—"`` when the base is zero or unparseable).
Balance-sheet yearly columns already carry end-of-period balances from
hledger itself (``bs -Y``); nothing here sums or averages columns.
"""

from __future__ import annotations

from decimal import Decimal

from hledger_textual.hledger import _parse_budget_amount
from hledger_textual.models import ReportData, ReportRow
from hledger_textual.widgets.formatting import fmt_amount, split_raw_commodities

#: Placeholder shown when a growth rate cannot be computed.
NO_GROWTH = "—"


def parse_cell(cell: str) -> dict[str, Decimal]:
    """Parse a report amount cell into per-commodity quantities.

    Args:
        cell: A display string such as ``"€3,480.00"``,
            ``"10 XDWD, €2,500.00"``, ``"0"`` or ``""``.

    Returns:
        Mapping of commodity to quantity; empty cells and zeroes map to
        an empty dict, unparseable fragments are skipped.
    """
    quantities: dict[str, Decimal] = {}
    for part in split_raw_commodities(cell):
        qty, commodity = _parse_budget_amount(part)
        if not commodity or qty == 0:
            continue
        quantities[commodity] = quantities.get(commodity, Decimal("0")) + qty
    return quantities


def _signed(commodity: str, qty: Decimal) -> str:
    """Render *qty* with an explicit ``+``/``-`` sign before the commodity."""
    if qty == 0:
        return fmt_amount(Decimal("0"), commodity)
    sign = "+" if qty > 0 else "-"
    return f"{sign}{fmt_amount(abs(qty), commodity)}"


def format_delta(first: str, last: str) -> str:
    """Return the ``Δ`` display string for *last* minus *first*.

    Args:
        first: Display string of the earliest comparison column.
        last: Display string of the latest comparison column.
    """
    before = parse_cell(first)
    after = parse_cell(last)
    parts = [
        _signed(commodity, after.get(commodity, Decimal("0")) - before.get(commodity, Decimal("0")))
        for commodity in dict.fromkeys([*before, *after])
    ]
    return ", ".join(parts) if parts else fmt_amount(Decimal("0"), "")


def format_growth(first: str, last: str) -> str:
    """Return the ``Δ%`` display string for *last* vs *first*.

    Args:
        first: Display string of the earliest comparison column.
        last: Display string of the latest comparison column.
    """
    before = parse_cell(first)
    after = parse_cell(last)
    commodities = dict.fromkeys([*before, *after])
    if not commodities:
        return NO_GROWTH
    parts = []
    for commodity in commodities:
        base = before.get(commodity, Decimal("0"))
        new = after.get(commodity, Decimal("0"))
        if base == 0:
            return NO_GROWTH
        pct = (new - base) / abs(base) * 100
        parts.append(f"{pct:+.1f}%")
    return ", ".join(parts)


def append_comparison_columns(data: ReportData) -> ReportData:
    """Return a copy of *data* with trailing ``Δ`` / ``Δ%`` columns.

    Rows with no amounts (section headers) receive blank cells; a single
    comparison column yields no trailing columns.  The input is not mutated.

    Args:
        data: The yearly (or quarterly) report to extend.
    """
    if len(data.period_headers) < 2:
        return data
    headers = [*data.period_headers, "Δ", "Δ%"]
    rows = []
    for row in data.rows:
        if not any(cell.strip() for cell in row.amounts):
            rows.append(
                ReportRow(
                    account=row.account,
                    amounts=[*row.amounts, "", ""],
                    is_section_header=row.is_section_header,
                    is_total=row.is_total,
                    depth=row.depth,
                )
            )
            continue
        first, last = row.amounts[0], row.amounts[-1]
        rows.append(
            ReportRow(
                account=row.account,
                amounts=[*row.amounts, format_delta(first, last), format_growth(first, last)],
                is_section_header=row.is_section_header,
                is_total=row.is_total,
                depth=row.depth,
            )
        )
    return ReportData(title=data.title, period_headers=headers, rows=rows)
