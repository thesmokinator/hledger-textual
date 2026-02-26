"""Accounts list pane widget."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import DataTable, Input

from hledger_tui.hledger import HledgerError, load_account_balances
from hledger_tui.widgets import distribute_column_widths


class AccountsPane(Widget):
    """Widget showing all accounts with their current balances."""

    BINDINGS = [
        Binding("enter", "view_account", "View", show=True, priority=True),
        Binding("slash", "filter", "Filter", show=True, priority=True),
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("escape", "dismiss_filter", "Dismiss filter", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    def __init__(self, journal_file: Path, **kwargs) -> None:
        """Initialize the pane.

        Args:
            journal_file: Path to the hledger journal file.
        """
        super().__init__(**kwargs)
        self.journal_file = journal_file
        self._balances: list[tuple[str, str]] = []
        self.filter_text: str = ""

    def compose(self) -> ComposeResult:
        """Create the pane layout."""
        with Horizontal(classes="filter-bar"):
            yield Input(
                placeholder="Filter by account name...",
                id="acc-filter-input",
                disabled=True,
            )
        yield DataTable(id="accounts-table")

    _ACCOUNTS_FIXED = {1: 20}

    def on_mount(self) -> None:
        """Set up the DataTable and load account balances."""
        table = self.query_one("#accounts-table", DataTable)
        table.cursor_type = "row"
        table.add_column("Account", width=20)
        table.add_column("Balance", width=self._ACCOUNTS_FIXED[1])
        self._load_balances()
        table.focus()

    def on_show(self) -> None:
        """Restore focus to the table when the pane becomes visible."""
        self.query_one("#accounts-table", DataTable).focus()

    def on_resize(self) -> None:
        """Recalculate column widths when the pane is resized."""
        table = self.query_one("#accounts-table", DataTable)
        distribute_column_widths(table, self._ACCOUNTS_FIXED)

    def _load_balances(self) -> None:
        """Load account balances from hledger and populate the table."""
        try:
            self._balances = load_account_balances(self.journal_file)
        except HledgerError as exc:
            self.notify(str(exc), severity="error", timeout=8)
            self._balances = []
        self._update_table()

    def _update_table(self) -> None:
        """Refresh the DataTable with current (possibly filtered) balances."""
        table = self.query_one("#accounts-table", DataTable)
        table.clear()
        for account, balance in self._filtered_balances():
            table.add_row(account, balance, key=account)

    def _filtered_balances(self) -> list[tuple[str, str]]:
        """Return balances filtered by the current filter text."""
        if not self.filter_text:
            return self._balances
        term = self.filter_text.lower()
        return [
            (account, balance)
            for account, balance in self._balances
            if term in account.lower()
        ]

    # --- Actions ---

    def action_view_account(self) -> None:
        """Push the account-transactions detail screen for the selected account."""
        table = self.query_one("#accounts-table", DataTable)
        if table.row_count == 0:
            return

        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        account = row_key.value if row_key else None
        if not account:
            return

        balance = next(
            (bal for acc, bal in self._balances if acc == account), ""
        )

        from hledger_tui.screens.account_transactions import AccountTransactionsScreen

        self.app.push_screen(
            AccountTransactionsScreen(account, balance, self.journal_file)
        )

    def action_refresh(self) -> None:
        """Reload account balances from the journal."""
        self._load_balances()
        self.notify("Refreshed", timeout=2)

    def action_filter(self) -> None:
        """Show/focus the filter input."""
        filter_bar = self.query_one(".filter-bar")
        filter_bar.add_class("visible")
        filter_input = self.query_one("#acc-filter-input", Input)
        filter_input.disabled = False
        filter_input.focus()

    def action_dismiss_filter(self) -> None:
        """Hide the filter input and clear the filter."""
        filter_bar = self.query_one(".filter-bar")
        if filter_bar.has_class("visible"):
            filter_bar.remove_class("visible")
            filter_input = self.query_one("#acc-filter-input", Input)
            filter_input.value = ""
            filter_input.disabled = True
            self.filter_text = ""
            self._update_table()
            self.query_one("#accounts-table", DataTable).focus()

    def action_cursor_down(self) -> None:
        """Move cursor down in the table."""
        self.query_one("#accounts-table", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up in the table."""
        self.query_one("#accounts-table", DataTable).action_cursor_up()

    # --- Event handlers ---

    @on(Input.Changed, "#acc-filter-input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        """Filter accounts as the user types."""
        self.filter_text = event.value
        self._update_table()
