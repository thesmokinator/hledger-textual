"""Main transactions list screen."""

from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Label, Static

from hledger_tui.hledger import HledgerError, load_transactions
from hledger_tui.models import Transaction, TransactionStatus


class TransactionsScreen(Screen):
    """Screen showing all transactions in a DataTable."""

    BINDINGS = [
        Binding("a", "add", "Add", show=True, priority=True),
        Binding("e", "edit", "Edit", show=True, priority=True),
        Binding("enter", "edit", "Edit", show=False),
        Binding("d", "delete", "Delete", show=True, priority=True),
        Binding("slash", "filter", "Filter", show=True, priority=True),
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("escape", "dismiss_filter", "Dismiss filter", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("q", "quit", "Quit", show=True, priority=True),
    ]

    def __init__(self, journal_file: Path) -> None:
        """Initialize the screen.

        Args:
            journal_file: Path to the hledger journal file.
        """
        super().__init__()
        self.journal_file = journal_file
        self.transactions: list[Transaction] = []
        self.filter_text: str = ""

    def compose(self) -> ComposeResult:
        """Create the screen layout."""
        with Horizontal(id="header-bar"):
            yield Label("hledger-tui", id="header-title")
            yield Label(str(self.journal_file), id="header-file")

        with Horizontal(id="filter-bar"):
            yield Input(
                placeholder="Filter by description or account...",
                id="filter-input",
                disabled=True,
            )

        yield DataTable(id="transactions-table")

        yield Static(
            "\\[a] Add  \\[e] Edit  \\[d] Delete  \\[/] Filter  \\[r] Refresh  \\[q] Quit",
            id="footer-bar",
        )

    def on_mount(self) -> None:
        """Set up the DataTable and load transactions."""
        table = self.query_one("#transactions-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Date", "Status", "Description", "Amount")
        self._load_transactions()
        table.focus()

    def _load_transactions(self) -> None:
        """Load transactions from the journal and populate the table."""
        try:
            self.transactions = load_transactions(self.journal_file)
        except HledgerError as exc:
            self.notify(str(exc), severity="error", timeout=8)
            self.transactions = []

        self._update_table()

    def _update_table(self) -> None:
        """Refresh the DataTable with current (possibly filtered) transactions."""
        table = self.query_one("#transactions-table", DataTable)
        table.clear()

        for txn in self._filtered_transactions():
            status_symbol = txn.status.symbol
            table.add_row(
                txn.date,
                status_symbol,
                txn.description,
                txn.total_amount,
                key=str(txn.index),
            )

    def _filtered_transactions(self) -> list[Transaction]:
        """Return transactions filtered by the current filter text."""
        if not self.filter_text:
            return self.transactions

        term = self.filter_text.lower()
        results = []
        for txn in self.transactions:
            if term in txn.description.lower():
                results.append(txn)
                continue
            for posting in txn.postings:
                if term in posting.account.lower():
                    results.append(txn)
                    break

        return results

    def _get_selected_transaction(self) -> Transaction | None:
        """Get the currently selected transaction from the table."""
        table = self.query_one("#transactions-table", DataTable)
        if table.row_count == 0:
            return None

        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        key_str = row_key.value if row_key else None
        if key_str is None:
            return None

        index = int(key_str)
        for txn in self.transactions:
            if txn.index == index:
                return txn
        return None

    # --- Actions ---

    def action_refresh(self) -> None:
        """Reload transactions from the journal."""
        self._load_transactions()
        self.notify("Refreshed", timeout=2)

    def action_filter(self) -> None:
        """Show/focus the filter input."""
        filter_bar = self.query_one("#filter-bar")
        filter_bar.add_class("visible")
        filter_input = self.query_one("#filter-input", Input)
        filter_input.disabled = False
        filter_input.focus()

    def action_dismiss_filter(self) -> None:
        """Hide the filter input and clear the filter."""
        filter_bar = self.query_one("#filter-bar")
        if filter_bar.has_class("visible"):
            filter_bar.remove_class("visible")
            filter_input = self.query_one("#filter-input", Input)
            filter_input.value = ""
            filter_input.disabled = True
            self.filter_text = ""
            self._update_table()
            self.query_one("#transactions-table", DataTable).focus()

    def action_cursor_down(self) -> None:
        """Move cursor down in the table."""
        table = self.query_one("#transactions-table", DataTable)
        table.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up in the table."""
        table = self.query_one("#transactions-table", DataTable)
        table.action_cursor_up()

    def action_add(self) -> None:
        """Open the form to add a new transaction."""
        from hledger_tui.screens.transaction_form import TransactionFormScreen

        def on_save(result: Transaction | None) -> None:
            if result is not None:
                self._do_append(result)

        self.app.push_screen(
            TransactionFormScreen(journal_file=self.journal_file),
            callback=on_save,
        )

    def action_edit(self) -> None:
        """Open the form to edit the selected transaction."""
        txn = self._get_selected_transaction()
        if txn is None:
            self.notify("No transaction selected", severity="warning", timeout=3)
            return

        from hledger_tui.screens.transaction_form import TransactionFormScreen

        def on_save(result: Transaction | None) -> None:
            if result is not None:
                self._do_replace(txn, result)

        self.app.push_screen(
            TransactionFormScreen(
                journal_file=self.journal_file,
                transaction=txn,
            ),
            callback=on_save,
        )

    def action_delete(self) -> None:
        """Delete the selected transaction (with confirmation)."""
        txn = self._get_selected_transaction()
        if txn is None:
            self.notify("No transaction selected", severity="warning", timeout=3)
            return

        from hledger_tui.screens.delete_confirm import DeleteConfirmModal

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._do_delete(txn)

        self.app.push_screen(DeleteConfirmModal(txn), callback=on_confirm)

    def action_quit(self) -> None:
        """Quit the application."""
        self.app.exit()

    # --- Mutation helpers ---

    @work(thread=True)
    def _do_append(self, transaction: Transaction) -> None:
        """Append a transaction and reload."""
        from hledger_tui.journal import JournalError, append_transaction

        try:
            append_transaction(self.journal_file, transaction)
            self.app.call_from_thread(self._load_transactions)
            self.app.call_from_thread(
                self.notify, "Transaction added", timeout=3
            )
        except JournalError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    @work(thread=True)
    def _do_replace(
        self, original: Transaction, updated: Transaction
    ) -> None:
        """Replace a transaction and reload."""
        from hledger_tui.journal import JournalError, replace_transaction

        try:
            replace_transaction(self.journal_file, original, updated)
            self.app.call_from_thread(self._load_transactions)
            self.app.call_from_thread(
                self.notify, "Transaction updated", timeout=3
            )
        except JournalError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    @work(thread=True)
    def _do_delete(self, transaction: Transaction) -> None:
        """Delete a transaction and reload."""
        from hledger_tui.journal import JournalError, delete_transaction

        try:
            delete_transaction(self.journal_file, transaction)
            self.app.call_from_thread(self._load_transactions)
            self.app.call_from_thread(
                self.notify, "Transaction deleted", timeout=3
            )
        except JournalError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    # --- Event handlers ---

    @on(Input.Changed, "#filter-input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        """Filter transactions as the user types."""
        self.filter_text = event.value
        self._update_table()
