"""Screen showing all transactions for a single account."""

from __future__ import annotations

import re
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Label, Static

from hledger_tui.widgets.transactions_table import TransactionsTable


class AccountTransactionsScreen(Screen):
    """Full-screen drill-down showing every transaction that touches an account.

    Reuses :class:`~hledger_tui.widgets.transactions_table.TransactionsTable`
    with a pinned account query so the layout, columns, ordering, and filter
    bar are identical to the main Transactions view.
    """

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("slash", "filter", "Filter", show=True, priority=True),
        Binding("e", "edit", "Edit", show=True, priority=True),
        Binding("enter", "edit", "Edit", show=False),
        Binding("d", "delete", "Delete", show=True, priority=True),
        Binding("r", "refresh", "Refresh", show=True, priority=True),
    ]

    def __init__(
        self,
        account: str,
        balance: str,
        journal_file: Path,
    ) -> None:
        """Initialise the screen.

        Args:
            account: Full account name (e.g. ``'assets:bank:checking'``).
            balance: Pre-formatted current balance string for display.
            journal_file: Path to the hledger journal file.
        """
        super().__init__()
        self.account = account
        self.balance = balance
        self.journal_file = journal_file

    def compose(self) -> ComposeResult:
        """Create the screen layout."""
        with Horizontal(id="acctxn-header"):
            yield Label(f"← {self.account}", id="acctxn-title")
            yield Label(self.balance, id="acctxn-balance")

        fixed_query = f"acct:^{re.escape(self.account)}$"
        yield TransactionsTable(self.journal_file, fixed_query=fixed_query)

        yield Static(
            "\\[Esc] Back  \\[/] Filter  \\[e] Edit  \\[d] Delete  \\[r] Refresh",
            id="acctxn-footer",
        )

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

    def action_refresh(self) -> None:
        """Reload transactions from the journal."""
        self._table.do_refresh()
