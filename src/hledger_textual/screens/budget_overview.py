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

    def compose(self) -> ComposeResult:
        """Create the screen layout."""
        with Vertical(id="budget-overview-dialog"):
            yield Label("Budget Overview", id="budget-overview-title")
            yield Select(
                [("3 months", 3), ("6 months", 6), ("12 months", 12)],
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
        """Load multi-period budget data and populate the table."""
        end = date.today().replace(day=1)
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
            return

        # Add columns: Account + one per period
        table.add_column("Account", width=28)
        for p in periods:
            table.add_column(p, width=14)

        # Determine account order: rules order first, then any extras from hledger
        rule_accounts = [r.account for r in self._rules]
        extra = [a for a in rows if a not in rule_accounts]
        account_order = rule_accounts + extra

        for account in account_order:
            if account not in rows:
                continue
            period_rows = rows[account]
            cells: list[str] = [account]
            for br in period_rows:
                usage = br.usage_pct
                commodity = br.commodity
                actual_str = f"{commodity}{br.actual:.2f}"
                if br.budget:
                    if usage > 100:
                        cells.append(f"[red]{actual_str}[/red]")
                    elif usage >= 75:
                        cells.append(f"[yellow]{actual_str}[/yellow]")
                    else:
                        cells.append(f"[green]{actual_str}[/green]")
                else:
                    cells.append(actual_str)
            # Pad if hledger returned fewer periods for this account
            while len(cells) < len(periods) + 1:
                cells.append("")
            table.add_row(*cells, key=account)

    def action_dismiss_screen(self) -> None:
        """Close the overview screen."""
        self.dismiss(None)
