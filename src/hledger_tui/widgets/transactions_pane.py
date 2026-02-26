"""Transactions list pane widget (full CRUD)."""

from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget

from hledger_tui.models import Transaction
from hledger_tui.widgets.transactions_table import TransactionsTable


class TransactionsPane(Widget):
    """Widget showing all transactions with add / edit / delete actions.

    Composes a :class:`~hledger_tui.widgets.transactions_table.TransactionsTable`
    for the shared filter bar and DataTable, and adds journal-mutation bindings
    on top.
    """

    BINDINGS = [
        Binding("a", "add", "Add", show=True, priority=True),
        Binding("e", "edit", "Edit", show=True, priority=True),
        Binding("enter", "edit", "Edit", show=False),
        Binding("d", "delete", "Delete", show=True, priority=True),
        Binding("slash", "filter", "Search", show=True, priority=True),
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("escape", "dismiss_filter", "Dismiss filter", show=False),
        Binding("left", "prev_month", "Previous month", show=False, priority=True),
        Binding("right", "next_month", "Next month", show=False, priority=True),
    ]

    def __init__(self, journal_file: Path, **kwargs) -> None:
        """Initialise the pane.

        Args:
            journal_file: Path to the hledger journal file.
        """
        super().__init__(**kwargs)
        self.journal_file = journal_file

    def compose(self) -> ComposeResult:
        """Render the shared transactions table."""
        yield TransactionsTable(self.journal_file)

    def on_show(self) -> None:
        """Re-focus the table when the pane becomes visible."""
        self.query_one(TransactionsTable).on_show()

    @property
    def _table(self) -> TransactionsTable:
        return self.query_one(TransactionsTable)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        """Reload transactions from the journal."""
        self._table.do_refresh()

    def action_filter(self) -> None:
        """Show the filter panel."""
        self._table.show_filter()

    def action_dismiss_filter(self) -> None:
        """Hide the search bar and reset all filters."""
        self._table.dismiss_filter()

    def action_prev_month(self) -> None:
        """Navigate to the previous month."""
        self._table.prev_month()

    def action_next_month(self) -> None:
        """Navigate to the next month."""
        self._table.next_month()

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
        self._table.do_edit()

    def action_delete(self) -> None:
        """Delete the selected transaction (with confirmation)."""
        self._table.do_delete()

    # ------------------------------------------------------------------
    # Mutation helpers (add is local — only needed in the main view)
    # ------------------------------------------------------------------

    @work(thread=True)
    def _do_append(self, transaction: Transaction) -> None:
        """Append a transaction to the journal and reload."""
        from hledger_tui.journal import JournalError, append_transaction

        try:
            append_transaction(self.journal_file, transaction)
            self.app.call_from_thread(self._table.reload)
            self.app.call_from_thread(self.notify, "Transaction added", timeout=3)
        except JournalError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )
