"""Screen showing all transactions for a single account."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Label, Static

from hledger_textual.hledger import escape_for_hledger, load_account_directives, save_account_directive
from hledger_textual.widgets.transactions_table import TransactionsTable


class AccountTransactionsScreen(Screen):
    """Full-screen drill-down showing every transaction that touches an account.

    Reuses :class:`~hledger_textual.widgets.transactions_table.TransactionsTable`
    with a pinned account query so the layout, columns, ordering, and filter
    bar are identical to the main Transactions view.
    """

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("slash", "filter", "Filter", show=True, priority=True),
        Binding("e", "edit", "Edit", show=True, priority=True),
        Binding("enter", "edit", "Edit", show=False),
        Binding("d", "delete", "Delete", show=True, priority=True),
        Binding("n", "edit_note", "Note", show=True, priority=True),
        Binding("r", "refresh", "Refresh", show=True, priority=True),
    ]

    def __init__(
        self,
        account: str,
        balance: str = "",
        journal_file: Path | None = None,
        *,
        date_query: str | None = None,
    ) -> None:
        """Initialise the screen.

        Args:
            account: Full account name (e.g. ``'assets:bank:checking'``).
            balance: Pre-formatted current balance string for display.
            journal_file: Path to the hledger journal file.
            date_query: Optional hledger date query (e.g. ``'date:2026-01'``)
                to restrict the transactions to a specific period.
        """
        super().__init__()
        self.account = account
        self.balance = balance
        self.journal_file = journal_file
        self._date_query = date_query

    def compose(self) -> ComposeResult:
        """Create the screen layout."""
        with Horizontal(id="acctxn-header"):
            yield Label(f"← {self.account}", id="acctxn-title")
            yield Label(self.balance, id="acctxn-balance")

        fixed_query = f"acct:^{escape_for_hledger(self.account)}$"
        if self._date_query:
            fixed_query = f"{fixed_query} {self._date_query}"
        yield TransactionsTable(self.journal_file, fixed_query=fixed_query)

        with Vertical(id="acctxn-bottom"):
            yield Static("", id="acctxn-note")
            yield Static(
                "\\[Esc] Back  \\[/] Search  \\[e] Edit  \\[d] Delete"
                "  \\[n] Note  \\[r] Refresh  \\[?] Help",
                id="acctxn-footer",
            )

    def on_mount(self) -> None:
        """Load and display account metadata after mount."""
        if not self.balance:
            self.query_one("#acctxn-balance", Label).display = False
        self._refresh_metadata()

    def _refresh_metadata(self) -> None:
        """Load account directive metadata and update the note section."""
        directives = load_account_directives(self.journal_file)
        directive = directives.get(self.account)
        note_widget = self.query_one("#acctxn-note", Static)
        if directive and directive.comment:
            note_widget.update(f" Note: {directive.comment}")
            note_widget.display = True
        else:
            note_widget.update("")
            note_widget.display = False

    @property
    def _table(self) -> TransactionsTable:
        return self.query_one(TransactionsTable)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_back(self) -> None:
        """Close the filter panel if open, otherwise pop this screen."""
        if not self._table.dismiss_filter():
            self.app.pop_screen()

    def action_filter(self) -> None:
        """Show the filter panel."""
        self._table.show_filter()

    def action_edit(self) -> None:
        """Open the form to edit the selected transaction."""
        self._table.do_edit()

    def action_delete(self) -> None:
        """Delete the selected transaction (with confirmation)."""
        self._table.do_delete()

    def action_edit_note(self) -> None:
        """Open a dialog to edit the account note/comment."""
        from hledger_textual.screens.account_note_form import AccountNoteModal

        directives = load_account_directives(self.journal_file)
        directive = directives.get(self.account)
        current_note = directive.comment if directive else ""

        def on_result(note: str | None) -> None:
            if note is not None:
                save_account_directive(self.journal_file, self.account, note)
                self._refresh_metadata()
                self.notify("Note saved", timeout=2)

        self.app.push_screen(
            AccountNoteModal(self.account, current_note), callback=on_result
        )

    def on_transactions_table_journal_changed(
        self, event: TransactionsTable.JournalChanged
    ) -> None:
        """Reload the transactions table after a journal mutation (edit/delete)."""
        self._table.reload()

    def action_refresh(self) -> None:
        """Reload transactions from the journal."""
        self._table.do_refresh()
        self._refresh_metadata()
