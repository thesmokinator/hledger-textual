"""Pure rendering helpers for the reports pane.

These functions turn :class:`ReportData` into DataTable-ready rows and
styled text without touching any widget, so they can be unit-tested in
isolation from UI events.
"""

from __future__ import annotations

import re
from decimal import Decimal

from rich.text import Text

from hledger_textual.amountutil import parse_amount_string
from hledger_textual.models import ReportData, ReportRow
from hledger_textual.widgets.constants import TREE_INDENT
from hledger_textual.widgets.formatting import (
    fmt_amount_str,
    fmt_single_amount_str,
    get_commodity_name,
    split_raw_commodities,
)

_ONLY_SEPS = re.compile(r'^[\s=\-\+\|]+$')
_STANDALONE_ZERO = re.compile(r'(?<![\d.])0(?![\d.])')

MULTI_COMMODITY_MARKER = "◆ "
"""Prefix marking flat-mode accounts whose amounts span several commodities."""


def format_custom_output(raw: str, *, skip_title: bool = False) -> Text:
    """Apply Rich styling to raw hledger text output.

    Improvements applied:

    - ``||`` and ``++`` replaced with Unicode box-drawing characters (``│`` / ``┼``)
    - Separator lines (``===`` / ``---``) are dimmed
    - Standalone zero values are dimmed
    - The report title (first non-empty, non-indented line) is rendered bold,
      unless ``skip_title`` is ``True`` in which case it is omitted entirely.
      Lines that start with whitespace are treated as data rows, not titles.
    - Total rows (lines after the ``---`` separator) are rendered bold yellow

    Args:
        raw: Raw stdout string from hledger.
        skip_title: When ``True``, the first non-empty, non-indented line (the
            hledger-generated title) is dropped from the output.  Use this when
            the report name is already displayed in a separate header widget.
            Lines that start with whitespace (data rows from simple commands
            like ``bal``) are never treated as titles.

    Returns:
        A :class:`rich.text.Text` ready for use in a :class:`~textual.widgets.Static`.
    """
    result = Text(no_wrap=False)
    lines = raw.splitlines()
    after_total_sep = False
    title_done = False

    for line in lines:
        display = line.replace('++', '┼').replace('||', '│')

        # Title: first non-empty line.  Hledger titles (e.g. "Balance
        # Sheet 2026-03-31") never start with whitespace, whereas data
        # rows from simple commands like ``bal`` are indented for amount
        # alignment.  Only treat the line as a title when it starts at
        # column 0; otherwise fall through to normal data handling.
        if not title_done:
            if display.strip():
                title_done = True
                if not display[0].isspace():
                    if not skip_title:
                        result.append(display + "\n", style="bold")
                    continue
                # First non-empty line is indented → data row, fall through
            else:
                if not skip_title:
                    result.append("\n")
                continue

        # Separator lines: only =, -, +, |, and spaces
        if _ONLY_SEPS.match(line):
            if line.strip() and '-' in line and '=' not in line:
                after_total_sep = True
            result.append(display + "\n", style="dim")
            continue

        # Total rows (after the --- separator)
        if after_total_sep:
            result.append(display + "\n", style="bold yellow")
            continue

        # Regular data line: dim standalone zero values
        line_text = Text(no_wrap=False)
        pos = 0
        for m in _STANDALONE_ZERO.finditer(display):
            if m.start() > pos:
                line_text.append(display[pos:m.start()])
            line_text.append("0", style="dim")
            pos = m.end()
        if pos < len(display):
            line_text.append(display[pos:])
        line_text.append("\n")
        result.append_text(line_text)

    return result


def merge_investments(is_data: ReportData, inv_data: ReportData) -> ReportData:
    """Append investment rows as a new section to an Income Statement report.

    Args:
        is_data: The original Income Statement report data.
        inv_data: Investment balance report data.

    Returns:
        A new :class:`ReportData` with the investment rows appended.
    """
    merged_rows = list(is_data.rows)

    n_periods = len(is_data.period_headers)
    merged_rows.append(ReportRow(
        account="Investments",
        amounts=[""] * n_periods,
        is_section_header=True,
    ))

    for row in inv_data.rows:
        if not row.is_section_header and not row.is_total:
            account = row.account
            if ":" in account:
                account = account.rsplit(":", 1)[-1]
            merged_rows.append(ReportRow(
                account=account,
                amounts=row.amounts,
            ))

    return ReportData(
        title=is_data.title,
        period_headers=is_data.period_headers,
        rows=merged_rows,
    )



def _has_multi_commodity(amounts: list[str]) -> bool:
    """Check whether any amount in the list spans multiple commodities."""
    return any(", " in amt for amt in amounts)


def _make_account_text(row: ReportRow) -> Text:
    """Build the Rich Text for the account column of a data row."""
    if row.is_section_header:
        return Text.from_markup(f"[bold cyan]{row.account}[/bold cyan]", emoji=False)
    if row.is_total:
        return Text.from_markup(f"[bold yellow]{row.account}[/bold yellow]", emoji=False)
    return Text(TREE_INDENT * row.depth + row.account)


def build_report_rows(
    data: ReportData,
    *,
    tree_mode: bool,
    stacked_currency: bool,
) -> tuple[list[tuple[list[str | Text], bool]], list[ReportRow | None], list[str]]:
    """Build DataTable rows for a built-in report.

    Args:
        data: The report data to render.
        tree_mode: Whether account names are tree-indented fragments whose
            full path must be recomputed from depth.
        stacked_currency: Whether multi-currency amounts are expanded into
            one row per commodity.

    Returns:
        A tuple of ``(rows, table_rows, full_paths)``: each row is a
        ``(cells, auto_height)`` pair ready for ``DataTable.add_row``;
        ``table_rows`` and ``full_paths`` are parallel to the rendered rows
        (``None`` / ``""`` for spacer rows).
    """
    n_cols = len(data.period_headers) + 1
    empty_row: list[str | Text] = [""] * n_cols
    rows: list[tuple[list[str | Text], bool]] = []
    table_rows: list[ReportRow | None] = []
    full_paths: list[str] = []
    path_stack: list[str] = []

    for idx, row in enumerate(data.rows):
        if row.is_section_header and idx > 0:
            rows.append((list(empty_row), False))
            table_rows.append(None)
            full_paths.append("")
        elif row.is_total:
            rows.append((list(empty_row), False))
            table_rows.append(None)
            full_paths.append("")

        # Compute full account path for tree mode
        if row.is_section_header or row.is_total:
            full_path = ""
            if row.is_section_header:
                path_stack.clear()
        else:
            if tree_mode:
                while len(path_stack) > row.depth:
                    path_stack.pop()
                if path_stack:
                    full_path = f"{path_stack[-1]}:{row.account}"
                else:
                    full_path = row.account
                if len(path_stack) == row.depth:
                    path_stack.append(full_path)
                else:
                    path_stack[row.depth] = full_path
            else:
                full_path = row.account

        account_text = _make_account_text(row)

        if (
            not tree_mode
            and not stacked_currency
            and not row.is_section_header
            and not row.is_total
            and _has_multi_commodity(row.amounts)
        ):
            account_text = Text(MULTI_COMMODITY_MARKER) + account_text

        # --- Stacked multi-currency mode ---
        if (
            stacked_currency
            and not row.is_section_header
            and not row.is_total
            and _has_multi_commodity(row.amounts)
        ):
            n_periods = len(data.period_headers)
            period_splits: list[list[str]] = [
                split_raw_commodities(amt) for amt in row.amounts
            ]

            # Group raw sub-amounts by commodity name across all periods
            # and compute each commodity's total absolute value for sorting.
            commodity_sum: dict[str, Decimal] = {}
            commodity_periods: dict[str, dict[int, str]] = {}

            for p_idx, split_items in enumerate(period_splits):
                for raw_amt in split_items:
                    name = get_commodity_name(raw_amt)
                    if not name:
                        continue
                    if name not in commodity_periods:
                        commodity_periods[name] = {}
                        commodity_sum[name] = Decimal("0")
                    commodity_periods[name][p_idx] = raw_amt
                    try:
                        qty, _ = parse_amount_string(raw_amt)
                        commodity_sum[name] += abs(qty)
                    except ValueError:
                        pass

            # Sort commodities by total absolute value (descending).
            sorted_commodities = sorted(
                commodity_periods.keys(),
                key=lambda c: commodity_sum[c],
                reverse=True,
            )

            # One row per commodity.
            for c_idx, commodity in enumerate(sorted_commodities):
                p_map = commodity_periods[commodity]
                if c_idx == 0:
                    # Primary row — full account name.
                    row_cells: list[str | Text] = [account_text]
                else:
                    # Child row — dimmed commodity name, indented.
                    row_cells = [Text(f"  {commodity}", style="dim")]

                for p_idx in range(n_periods):
                    raw = p_map.get(p_idx, "")
                    row_cells.append(fmt_single_amount_str(raw, accounting=True) if raw else "")

                while len(row_cells) < n_periods + 1:
                    row_cells.append("")
                rows.append((row_cells, False))
                table_rows.append(row)
                full_paths.append(full_path)

            continue

        # --- Single-currency or non-stacked path ---
        cells: list[str | Text] = [account_text]
        for amt in row.amounts:
            formatted = fmt_amount_str(amt, accounting=True)
            if row.is_total:
                cells.append(f"[bold]{formatted}[/bold]")
            else:
                cells.append(formatted)

        while len(cells) < len(data.period_headers) + 1:
            cells.append("")

        rows.append((cells, True))
        table_rows.append(row)
        full_paths.append(full_path)

    return rows, table_rows, full_paths
