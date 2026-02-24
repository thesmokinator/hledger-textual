"""Shared transactions table widget with an integrated filter bar."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label

from hledger_tui.hledger import HledgerError, load_accounts, load_transactions
from hledger_tui.models import Transaction
from hledger_tui.widgets.autocomplete_input import AutocompleteInput

_PERIOD_BUTTONS = [
    ("This month", "thismonth"),
    ("7d", "7"),
    ("15d", "15"),
    ("30d", "30"),
    ("60d", "60"),
    ("90d", "90"),
    ("1y", "365"),
    ("All", "all"),
]


def _period_query(period_id: str) -> str:
    """Return an hledger date query string for the given period identifier.

    Args:
        period_id: One of the period identifiers from ``_PERIOD_BUTTONS``.

    Returns:
        An hledger query fragment, e.g. ``'date:thismonth'``, ``'date:2024-01-01..'``,
        or an empty string for "all time".
    """
    if period_id == "thismonth":
        return "date:thismonth"
    if period_id == "all":
        return ""
    start = date.today() - timedelta(days=int(period_id))
    return f"date:{start.isoformat()}.."


class TransactionsTable(Widget):
    """Transactions DataTable with an integrated two-row filter bar.

    Used both in :class:`~hledger_tui.widgets.transactions_pane.TransactionsPane`
    (full CRUD) and in
    :class:`~hledger_tui.screens.account_transactions.AccountTransactionsScreen`
    (drill-down, read-only) so both views share identical columns, filters, and
    ordering.

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
        # When pinned to a specific account show all time by default so the
        # user immediately sees every transaction for that account.
        self._initial_period_id: str = "all" if fixed_query else "thismonth"
        self._date_query: str = _period_query(self._initial_period_id)
        self._account_filter: str = ""
        self._desc_filter: str = ""
        self._all_transactions: list[Transaction] = []

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Create the filter bar and table layout."""
        with Vertical(classes="filter-bar"):
            with Horizontal(classes="filter-inputs-row"):
                yield Label("Desc:", classes="filter-label")
                yield Input(
                    placeholder="search...",
                    id="txn-desc-input",
                    disabled=True,
                )
                yield Label("Account:", classes="filter-label")
                yield AutocompleteInput(
                    placeholder="account...",
                    id="txn-acct-input",
                    disabled=True,
                )
            with Horizontal(classes="period-buttons"):
                for label, period_id in _PERIOD_BUTTONS:
                    classes = "-active" if period_id == self._initial_period_id else ""
                    yield Button(label, id=f"period-{period_id}", classes=classes)
        yield DataTable(id="transactions-table")

    def on_mount(self) -> None:
        """Set up the DataTable columns and start loading."""
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.show_row_labels = False
        table.add_columns("Date", "St", "Description", "Accounts", "Amount")
        self._load_transactions()
        self._load_accounts()
        table.focus()

    def on_show(self) -> None:
        """Re-focus the table whenever this widget becomes visible."""
        self.query_one(DataTable).focus()

    def on_resize(self) -> None:
        """Recalculate column widths when the widget is resized."""
        self._distribute_column_widths()

    # ------------------------------------------------------------------
    # Public interface (for parent widgets / screens)
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Trigger a full reload from the journal (call after mutations)."""
        self._load_transactions()

    def show_filter(self) -> None:
        """Show the filter panel and move focus to the description input."""
        filter_bar = self.query_one(".filter-bar")
        filter_bar.add_class("visible")
        desc_input = self.query_one("#txn-desc-input", Input)
        desc_input.disabled = False
        acct_input = self.query_one("#txn-acct-input", AutocompleteInput)
        acct_input.disabled = False
        desc_input.focus()

    def dismiss_filter(self) -> bool:
        """Hide the filter panel and reset all user-set filters.

        Returns:
            ``True`` if the panel was open and has been closed,
            ``False`` if it was already hidden (so the caller can decide to
            take a different action, e.g. pop a screen).
        """
        filter_bar = self.query_one(".filter-bar")
        if not filter_bar.has_class("visible"):
            return False
        filter_bar.remove_class("visible")
        desc_input = self.query_one("#txn-desc-input", Input)
        desc_input.value = ""
        desc_input.disabled = True
        acct_input = self.query_one("#txn-acct-input", AutocompleteInput)
        acct_input.value = ""
        acct_input.disabled = True
        self._desc_filter = ""
        self._account_filter = ""
        for btn in self.query(".period-buttons Button"):
            btn.remove_class("-active")
        self.query_one(f"#period-{self._initial_period_id}", Button).add_class("-active")
        self._date_query = _period_query(self._initial_period_id)
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
            for q in [self._fixed_query, self._date_query, self._account_filter_query()]
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

    def _account_filter_query(self) -> str:
        """Return the hledger account query fragment, or empty string."""
        return f"acct:{self._account_filter}" if self._account_filter else ""

    def _set_transactions(self, txns: list[Transaction]) -> None:
        """Store loaded transactions and apply the current description filter."""
        self._all_transactions = txns
        self._apply_desc_filter()

    def _apply_desc_filter(self) -> None:
        """Filter by description client-side and refresh the table."""
        if not self._desc_filter:
            visible = self._all_transactions
        else:
            term = self._desc_filter.lower()
            visible = [
                t for t in self._all_transactions if term in t.description.lower()
            ]
        self._update_table(visible)

    def _update_table(self, transactions: list[Transaction]) -> None:
        """Repopulate the DataTable with *transactions*.

        Args:
            transactions: The rows to display.
        """
        table = self.query_one(DataTable)
        table.clear()
        for txn in transactions:
            accounts = " · ".join(p.account for p in txn.postings)
            table.add_row(
                txn.date,
                txn.status.symbol,
                txn.description,
                accounts,
                txn.total_amount,
                key=str(txn.index),
            )
        self._distribute_column_widths()

    def _distribute_column_widths(self) -> None:
        """Set column widths proportionally to fill the available width."""
        table = self.query_one(DataTable)
        available = self.size.width
        if available <= 0:
            return

        cols = table.ordered_columns
        if len(cols) != 5:
            return

        padding_per_col = 2  # DataTable default cell_padding is 1 per side
        total_overhead = len(cols) * padding_per_col
        usable = available - total_overhead

        date_w = 12
        st_w = 3
        amount_w = 16
        fixed = date_w + st_w + amount_w
        remaining = max(usable - fixed, 20)

        desc_w = remaining * 2 // 5
        accts_w = remaining - desc_w

        widths = [date_w, st_w, desc_w, accts_w, amount_w]
        for col, w in zip(cols, widths):
            col.auto_width = False
            col.width = w

        table.refresh(layout=True)

    @work(thread=True)
    def _load_accounts(self) -> None:
        """Load account names for the autocomplete suggester."""
        try:
            accounts = load_accounts(self.journal_file)
        except HledgerError:
            accounts = []
        self.app.call_from_thread(self._set_account_suggester, accounts)

    def _set_account_suggester(self, accounts: list[str]) -> None:
        """Attach *accounts* as suggestions to the account input."""
        from textual.suggester import SuggestFromList

        self.query_one("#txn-acct-input", AutocompleteInput).suggester = (
            SuggestFromList(accounts, case_sensitive=False)
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @on(Input.Changed, "#txn-desc-input")
    def on_desc_changed(self, event: Input.Changed) -> None:
        """Filter by description in real-time as the user types."""
        self._desc_filter = event.value
        self._apply_desc_filter()

    @on(Input.Submitted, "#txn-acct-input")
    def on_acct_submitted(self, event: Input.Submitted) -> None:
        """Reload with the typed account filter when the user presses Enter."""
        self._account_filter = event.value
        self._load_transactions()

    @on(Button.Pressed, ".period-buttons Button")
    def on_period_pressed(self, event: Button.Pressed) -> None:
        """Switch the active period and reload when a period button is clicked."""
        event.stop()
        for btn in self.query(".period-buttons Button"):
            btn.remove_class("-active")
        event.button.add_class("-active")
        period_id = event.button.id.removeprefix("period-")
        self._date_query = _period_query(period_id)
        self._load_transactions()
