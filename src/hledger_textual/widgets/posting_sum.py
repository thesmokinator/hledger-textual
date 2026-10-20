"""Running-balance summary for the posting rows of a form (issue #142)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from decimal import Decimal

from hledger_textual.widgets.formatting import fmt_amount
from hledger_textual.widgets.posting_row import PostingRow

# Parse an amount string with the row's commodity into (quantity, commodity).
AmountParser = Callable[[str, str], tuple[Decimal, str] | None]


def collect_posting_totals(
    rows: Iterable[PostingRow],
    parse: AmountParser,
) -> tuple[dict[str, Decimal], bool]:
    """Sum the amounts of the posting rows per commodity.

    Rows without an account are ignored (they are not postings yet), as are
    rows with an empty amount.  A row whose amount cannot be parsed makes the
    summary "incomplete" but does not stop the other rows from being summed.

    Args:
        rows: The posting rows of the form.
        parse: Callable parsing ``(amount_text, commodity)`` into
            ``(quantity, commodity)``, or None when the text is invalid.

    Returns:
        A ``(totals, incomplete)`` tuple where *totals* maps commodity to the
        running sum and *incomplete* is True when at least one amount could
        not be parsed.
    """
    totals: dict[str, Decimal] = {}
    incomplete = False
    for row in rows:
        # A freshly mounted row may not have its inputs yet.
        if not getattr(row, "is_ready", True):
            continue
        if not row.account:
            continue
        text = row.amount
        if not text:
            continue
        parsed = parse(text, row.commodity)
        if parsed is None:
            incomplete = True
            continue
        quantity, commodity = parsed
        totals[commodity] = totals.get(commodity, Decimal("0")) + quantity
    return totals, incomplete


def format_posting_sum(
    totals: dict[str, Decimal],
    incomplete: bool,
    default_commodity: str,
) -> str:
    """Render the running-balance line shown under the posting rows.

    Balanced commodities are green with a check mark, unbalanced ones red
    with a cross; if any amount is unparsable the line ends with a muted
    ``incomplete`` marker.

    Args:
        totals: Running sum per commodity.
        incomplete: Whether at least one amount could not be parsed.
        default_commodity: Commodity used to show a zero sum before the first
            amount is typed.

    Returns:
        Rich markup for the summary line.
    """
    parts: list[str] = []
    for commodity, total in totals.items():
        label = fmt_amount(total, commodity)
        if total == 0:
            parts.append(f"[green]{label} \u2713[/green]")
        else:
            parts.append(f"[red]{label} \u2717[/red]")
    if incomplete:
        parts.append("[dim]incomplete[/dim]")
    if not parts:
        parts.append(f"[green]{fmt_amount(Decimal('0'), default_commodity)} \u2713[/green]")
    return "Sum: " + ", ".join(parts)
