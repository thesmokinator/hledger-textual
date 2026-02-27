"""Shared transactions table widget with month navigation and search."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import DataTable, Input, Static

from hledger_tui.hledger import HledgerError, expand_search_query, load_transactions
from hledger_tui.models import Transaction
from hledger_tui.widgets import distribute_column_widths
from hledger_tui.widgets.pane_toolbar import PaneToolbar


class TransactionsTable(Widget):
    """Transactions DataTable with month navigation and an hledger-query search bar.

    Month navigation (◄/►) lets the user browse one calendar month at a time.
    The search bar (toggled with ``/``) accepts raw hledger query syntax
    (``desc:grocery``, ``acct:food``, ``amt:>100``) and searches the entire
    journal.

    Args:
        journal_file: Path to the hledger journal file.
        fixed_query: An hledger query fragment that is **always** appended to
            every load request and is never cleared by the filter reset.  Use
            this to pin the widget to a specific account, e.g.
            ``'acct:^assets:bank$'``.
    """

    def __init__(
        self,
        journal_file: Path,
        fixed_query: str | None = None,
        **kwargs,
    ) -> None:
        """Initialise the widget."""
        super().__init__(**kwargs)
        self.journal_file = journal_file
        self._fixed_query = fixed_query
        self._current_month: date = date.today().replace(day=1)
        self._date_query: str = "" if fixed_query else self._month_query()
        self._search_query: str = ""
        self._all_transactions: list[Transaction] = []

    # ------------------------------------------------------------------
    # Month helpers
    # ------------------------------------------------------------------

    def _month_query(self) -> str:
        """Return hledger date query for the current month."""
        return f"date:{self._current_month.strftime('%Y-%m')}"

    def _period_label(self) -> str:
        """Return a human-readable label for the current month."""
        return self._current_month.strftime("%B %Y")

    def _update_period_label(self) -> None:
        """Refresh the month label widget."""
        self.query_one("#txn-period-label", Static).update(self._period_label())

    def prev_month(self) -> None:
        """Navigate to the previous month and reload."""
        m = self._current_month
        month, year = m.month - 1, m.year
        if month < 1:
            month, year = 12, year - 1
        self._current_month = m.replace(year=year, month=month)
        self._date_query = self._month_query()
        self._update_period_label()
        self._load_transactions()

    def next_month(self) -> None:
        """Navigate to the next month and reload."""
        m = self._current_month
        month, year = m.month + 1, m.year
        if month > 12:
            month, year = 1, year + 1
        self._current_month = m.replace(year=year, month=month)
        self._date_query = self._month_query()
        self._update_period_label()
        self._load_transactions()

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Create the month nav, search bar, and table layout."""
        with PaneToolbar():
            if not self._fixed_query:
                with Horizontal(id="txn-period-nav", classes="period-nav"):
                    yield Static(
                        "\u25c4 Prev", id="txn-btn-prev-month", classes="period-btn"
                    )
                    yield Static(self._period_label(), id="txn-period-label")
                    yield Static(
                        "Next \u25ba", id="txn-btn-next-month", classes="period-btn"
                    )
            with Vertical(classes="filter-bar"):
                yield Input(
                    placeholder="Search... (e.g. d:grocery, ac:food, am:>100)",
                    id="txn-search-input",
                    disabled=True,
                )
        yield DataTable(id="transactions-table")

    # Date, Status, Accounts, Amount fixed; Description flex
    _TXN_FIXED = {0: 12, 1: 8, 3: 30, 4: 22}

    def on_mount(self) -> None:
        """Set up the DataTable columns and start loading."""
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.show_row_labels = False
        table.add_column("Date", width=self._TXN_FIXED[0])
        table.add_column("Status", width=self._TXN_FIXED[1])
        table.add_column("Description", width=20)
        table.add_column("Accounts", width=self._TXN_FIXED[3])
        table.add_column("Amount", width=self._TXN_FIXED[4])
        self._load_transactions()
        table.focus()

    def on_show(self) -> None:
        """Re-focus the table whenever this widget becomes visible."""
        self.query_one(DataTable).focus()

    def on_resize(self) -> None:
        """Recalculate column widths when the widget is resized."""
        table = self.query_one(DataTable)
        distribute_column_widths(table, self._TXN_FIXED)

    # ------------------------------------------------------------------
    # Public interface (for parent widgets / screens)
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Trigger a full reload from the journal (call after mutations)."""
        self._load_transactions()

    def show_filter(self) -> None:
        """Show the search bar and hide the month navigation."""
        nav = self.query("#txn-period-nav")
        if nav:
            nav.first().add_class("hidden")
        filter_bar = self.query_one(".filter-bar")
        filter_bar.add_class("visible")
        search_input = self.query_one("#txn-search-input", Input)
        search_input.disabled = False
        search_input.focus()

    def dismiss_filter(self) -> bool:
        """Hide the search bar and restore month navigation.

        Returns:
            ``True`` if the panel was open and has been closed,
            ``False`` if it was already hidden.
        """
        filter_bar = self.query_one(".filter-bar")
        if not filter_bar.has_class("visible"):
            return False
        filter_bar.remove_class("visible")
        search_input = self.query_one("#txn-search-input", Input)
        search_input.value = ""
        search_input.disabled = True
        self._search_query = ""
        # Restore month filter
        self._current_month = date.today().replace(day=1)
        nav = self.query("#txn-period-nav")
        if nav:
            self._date_query = self._month_query()
            self._update_period_label()
            nav.first().remove_class("hidden")
        else:
            self._date_query = ""
        self._load_transactions()
        self.query_one(DataTable).focus()
        return True

    def get_selected_transaction(self) -> Transaction | None:
        """Return the transaction corresponding to the currently highlighted row."""
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        key_str = row_key.value if row_key else None
        if key_str is None:
            return None
        index = int(key_str)
        for txn in self._all_transactions:
            if txn.index == index:
                return txn
        return None

    # ------------------------------------------------------------------
    # CRUD actions (reusable by any parent widget / screen)
    # ------------------------------------------------------------------

    def do_refresh(self) -> None:
        """Reload transactions from the journal and notify the user."""
        self.reload()
        self.notify("Refreshed", timeout=2)

    def do_edit(self) -> None:
        """Open the form to edit the currently selected transaction."""
        txn = self.get_selected_transaction()
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

    def do_delete(self) -> None:
        """Delete the selected transaction (with confirmation)."""
        txn = self.get_selected_transaction()
        if txn is None:
            self.notify("No transaction selected", severity="warning", timeout=3)
            return

        from hledger_tui.screens.delete_confirm import DeleteConfirmModal

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._do_delete(txn)

        self.app.push_screen(DeleteConfirmModal(txn), callback=on_confirm)

    @work(thread=True)
    def _do_replace(self, original: Transaction, updated: Transaction) -> None:
        """Replace a transaction in the journal and reload."""
        from hledger_tui.journal import JournalError, replace_transaction

        try:
            replace_transaction(self.journal_file, original, updated)
            self.app.call_from_thread(self.reload)
            self.app.call_from_thread(self.notify, "Transaction updated", timeout=3)
        except JournalError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    @work(thread=True)
    def _do_delete(self, transaction: Transaction) -> None:
        """Delete a transaction from the journal and reload."""
        from hledger_tui.journal import JournalError, delete_transaction

        try:
            delete_transaction(self.journal_file, transaction)
            self.app.call_from_thread(self.reload)
            self.app.call_from_thread(self.notify, "Transaction deleted", timeout=3)
        except JournalError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    # ------------------------------------------------------------------
    # Internal loading / filtering
    # ------------------------------------------------------------------

    @work(thread=True, exclusive=True)
    def _load_transactions(self) -> None:
        """Load transactions from hledger in a background thread."""
        parts = [
            q
            for q in [self._fixed_query, self._date_query, self._search_query]
            if q
        ]
        query = " ".join(parts) or None
        try:
            txns = load_transactions(self.journal_file, query=query, reverse=True)
        except HledgerError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )
            txns = []
        self.app.call_from_thread(self._set_transactions, txns)

    def _set_transactions(self, txns: list[Transaction]) -> None:
        """Store loaded transactions and refresh the table."""
        self._all_transactions = txns
        self._update_table(txns)

    def _update_table(self, transactions: list[Transaction]) -> None:
        """Repopulate the DataTable with *transactions*."""
        table = self.query_one(DataTable)
        table.clear()
        for txn in transactions:
            accounts = " \u00b7 ".join(p.account for p in txn.postings)
            table.add_row(
                txn.date,
                txn.status.symbol,
                txn.description,
                accounts,
                txn.total_amount,
                key=str(txn.index),
            )
        table = self.query_one(DataTable)
        distribute_column_widths(table, self._TXN_FIXED)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @on(Input.Submitted, "#txn-search-input")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        """Execute the search query when the user presses Enter."""
        self._search_query = expand_search_query(event.value)
        if self._search_query:
            self._date_query = ""  # search entire journal
        self._load_transactions()

    def on_click(self, event) -> None:
        """Handle clicks on the month navigation arrows."""
        widget_id = getattr(event.widget, "id", None)
        if widget_id == "txn-btn-prev-month":
            self.prev_month()
        elif widget_id == "txn-btn-next-month":
            self.next_month()
