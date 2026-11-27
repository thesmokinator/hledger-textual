"""Budget multi-period overview screen."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Select, Static
from textual.containers import Vertical

from hledger_textual.dateutil import prev_month as _prev_month
from hledger_textual.hledger import HledgerError, load_multi_period_budget_report
from hledger_textual.models import BudgetRule
from hledger_textual.widgets.constants import BUDGET_OVERVIEW_PERIOD_OPTIONS
from hledger_textual.widgets.pane_mixin import get_period


def _months_range(end: date, n: int) -> tuple[str, str]:
    """Return (start, end) period strings for *n* months ending at *end*.

    Args:
        end: The last month (first day of month).
        n: Number of months to include.

    Returns:
        A ``(start_str, end_str)`` tuple in ``YYYY-MM`` format.
    """
    start = end
    for _ in range(n - 1):
        start = _prev_month(start)
    return start.strftime("%Y-%m"), end.strftime("%Y-%m")


class BudgetOverviewScreen(ModalScreen[None]):
    """Modal showing budget vs actual across the last N months.

    Each row is an account from the budget rules; each column is a calendar
    month.  Cells are colour-coded by usage percentage (green / yellow / red).
    """

    BINDINGS = [
        Binding("escape,o", "dismiss_screen", "Close", show=True),
        Binding("x", "export_overview", "Export", show=True),
    ]

    def __init__(self, journal_file: Path, rules: list[BudgetRule]) -> None:
        """Initialise the overview screen.

        Args:
            journal_file: Path to the main hledger journal file.
            rules: Current list of budget rules (used for account ordering).
        """
        super().__init__()
        self.journal_file = journal_file
        self._rules = rules
        self._num_periods: int = 3
        self._last_periods: list[str] = []
        self._last_rows: dict[str, list] = {}

    def compose(self) -> ComposeResult:
        """Create the screen layout."""
        with Vertical(id="budget-overview-dialog"):
            yield Label("Budget Overview", id="budget-overview-title")
            yield Select(
                BUDGET_OVERVIEW_PERIOD_OPTIONS,
                value=3,
                allow_blank=False,
                id="budget-overview-periods",
            )
            yield Static("", id="budget-overview-status")
            yield DataTable(id="budget-overview-table")

    def on_mount(self) -> None:
        """Set up table columns and load data."""
        table = self.query_one("#budget-overview-table", DataTable)
        table.cursor_type = "row"
        table.show_cursor = False
        self._load_data()

    @on(Select.Changed, "#budget-overview-periods")
    def on_period_changed(self, event: Select.Changed) -> None:
        """Reload data when the period selection changes."""
        self._num_periods = int(event.value)
        self._load_data()

    @work(thread=True, exclusive=True)
    def _load_data(self) -> None:
        """Load multi-period budget data and populate the table.

        The window ends at the anchor month of the app's shared period
        selection (issue #263), so the overview follows the pane's month.
        """
        period = get_period(self)
        end = period.begin.replace(day=1) if period.begin else date.today().replace(day=1)
        start_str, end_str = _months_range(end, self._num_periods)
        try:
            periods, rows = load_multi_period_budget_report(
                self.journal_file, start_str, end_str
            )
        except HledgerError as exc:
            self.app.call_from_thread(self._show_load_error, str(exc))
            return
        self.app.call_from_thread(self._populate_table, periods, rows)

    def _show_load_error(self, msg: str) -> None:
        """Display an error message in the status label."""
        self.query_one("#budget-overview-status", Static).update(f"[red]Error: {msg}[/red]")

    def _budget_cell(self, budget_row, markup: bool = True) -> str:
        """Render one budget cell with usage colours.

        Args:
            budget_row: The :class:`BudgetRow` for the cell.
            markup: Wrap in usage colour markup; plain text when False
                (used for CSV export).
        """
        usage = budget_row.usage_pct
        commodity = budget_row.commodity
        actual_str = f"{commodity}{budget_row.actual:.2f}"
        if not budget_row.budget or not markup:
            return actual_str
        if usage > 100:
            return f"[red]{actual_str}[/red]"
        if usage >= 75:
            return f"[yellow]{actual_str}[/yellow]"
        return f"[green]{actual_str}[/green]"

    def get_export_data(self):
        """Return an ExportData with month and year-total columns.

        Mirrors the on-screen table: one column per month plus a total
        column per calendar year.  Cells are plain text (no colour markup).

        Returns:
            An ExportData instance, or None when no data was loaded.
        """
        from hledger_textual.budget_yearly import sum_year_row, year_columns
        from hledger_textual.export import ExportData

        periods = getattr(self, "_last_periods", None)
        rows = getattr(self, "_last_rows", None)
        if not periods or not rows:
            return None
        spec = year_columns(periods)
        headers = ["Account"]
        for entry in spec:
            if entry[0] == "month":
                headers.append(periods[entry[1]])
            else:
                headers.append(entry[1])
        data_rows: list[list[str]] = []
        for account, period_rows in rows.items():
            cells = [account]
            for entry in spec:
                if entry[0] == "month":
                    idx = entry[1]
                    br = period_rows[idx] if idx < len(period_rows) else None
                    cells.append(
                        self._budget_cell(br, markup=False)
                        if br is not None
                        else ""
                    )
                else:
                    months = [
                        period_rows[i]
                        for i in entry[2]
                        if i < len(period_rows)
                    ]
                    cells.append(
                        self._budget_cell(
                            sum_year_row(account, months), markup=False
                        )
                        if months
                        else ""
                    )
            data_rows.append(cells)
        return ExportData.from_rows("Budget Overview", headers, data_rows, "budget-overview")

    def _populate_table(
        self,
        periods: list[str],
        rows: dict[str, list],
    ) -> None:
        """Populate the DataTable with loaded data.

        Args:
            periods: Ordered list of period labels.
            rows: Mapping of account name to per-period BudgetRow list.
        """
        if not self.is_attached:
            return

        table = self.query_one("#budget-overview-table", DataTable)
        table.clear(columns=True)

        status = self.query_one("#budget-overview-status", Static)
        status.update("")

        if not periods or not rows:
            status.update("[dim]No budget data available for this range.[/dim]")
            self._last_periods = []
            self._last_rows = {}
            return

        self._last_periods = periods
        self._last_rows = rows

        # Add columns: Account + one per period, with a year total after
        # each December (issue #282).
        from hledger_textual.budget_yearly import sum_year_row, year_columns

        spec = year_columns(periods)
        table.add_column("Account", width=28)
        for entry in spec:
            if entry[0] == "month":
                table.add_column(periods[entry[1]], width=14)
            else:
                table.add_column(entry[1], width=14)

        # Determine account order: rules order first, then any extras from hledger
        rule_accounts = [r.account for r in self._rules]
        extra = [a for a in rows if a not in rule_accounts]
        account_order = rule_accounts + extra

        for account in account_order:
            if account not in rows:
                continue
            period_rows = rows[account]
            cells: list[str] = [account]
            for entry in spec:
                if entry[0] == "month":
                    idx = entry[1]
                    br = period_rows[idx] if idx < len(period_rows) else None
                    cells.append(self._budget_cell(br) if br is not None else "")
                else:
                    _, _year, idxs = entry
                    months = [
                        period_rows[i] for i in idxs if i < len(period_rows)
                    ]
                    if not months:
                        cells.append("")
                    else:
                        cells.append(self._budget_cell(sum_year_row(account, months)))
            # Pad if hledger returned fewer periods for this account
            while len(cells) < len(spec) + 1:
                cells.append("")
            table.add_row(*cells, key=account)

    def action_export_overview(self) -> None:
        """Export the overview table (months + year totals) to CSV or PDF."""
        from hledger_textual.config import load_export_dir
        from hledger_textual.export import default_filename, export_csv, export_pdf

        data = self.get_export_data()
        if data is None:
            self.notify("Nothing to export yet", severity="warning", timeout=3)
            return

        from hledger_textual.screens.export_modal import ExportModal

        def on_result(result: tuple[str, str, str] | None) -> None:
            if result is None:
                return
            fmt, fname, directory = result
            from pathlib import Path as _Path

            path = _Path(directory).expanduser().resolve() / fname
            try:
                if fmt == "pdf":
                    export_pdf(data, path)
                else:
                    export_csv(data, path)
            except Exception as exc:
                self.notify(f"Export failed: {exc}", severity="error", timeout=8)
                return
            self.notify(f"Exported to {path}", timeout=5)

        self.app.push_screen(
            ExportModal(
                default_filename=default_filename("budget-overview", "csv"),
                default_directory=str(load_export_dir()),
            ),
            callback=on_result,
        )

    def action_dismiss_screen(self) -> None:
        """Close the overview screen."""
        self.dismiss(None)
