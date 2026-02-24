"""Screen showing all transactions for a single account."""

from __future__ import annotations

import re
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Label, Static

from hledger_tui.hledger import HledgerError, load_transactions
from hledger_tui.models import Transaction


class AccountTransactionsScreen(Screen):
    """Full-screen drill-down showing every transaction that touches an account."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    def __init__(
        self,
        account: str,
        balance: str,
        journal_file: Path,
    ) -> None:
        """Initialise the screen.

        Args:
            account: Full account name (e.g. 'assets:bank:checking').
            balance: Pre-formatted current balance string for display.
            journal_file: Path to the hledger journal file.
        """
        super().__init__()
        self.account = account
        self.balance = balance
        self.journal_file = journal_file
        self.transactions: list[Transaction] = []

    def compose(self) -> ComposeResult:
        """Create the screen layout."""
        with Horizontal(id="acctxn-header"):
            yield Label(f"← {self.account}", id="acctxn-title")
            yield Label(self.balance, id="acctxn-balance")

        yield DataTable(id="acctxn-table")

        yield Static(
            "\\[Esc] Back  \\[j/k] Navigate",
            id="acctxn-footer",
        )

    def on_mount(self) -> None:
        """Set up the DataTable and start loading transactions."""
        table = self.query_one("#acctxn-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Date", "St", "Description", "Amount")
        self._load()
        table.focus()

    # --- Data loading ---

    @work(thread=True)
    def _load(self) -> None:
        """Load transactions for this account in a background thread."""
        query = f"acct:^{re.escape(self.account)}$"
        try:
            transactions = load_transactions(self.journal_file, query=query)
        except HledgerError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )
            return
        self.app.call_from_thread(self._populate, transactions)

    def _populate(self, transactions: list[Transaction]) -> None:
        """Populate the DataTable with the loaded transactions."""
        self.transactions = transactions
        table = self.query_one("#acctxn-table", DataTable)
        table.clear()
        for txn in transactions:
            amount = self._posting_amount(txn)
            table.add_row(
                txn.date,
                txn.status.symbol,
                txn.description,
                amount,
                key=str(txn.index),
            )

    def _posting_amount(self, txn: Transaction) -> str:
        """Return the formatted amount for the posting belonging to this account.

        When the same account appears more than once in a transaction (split
        postings), the amounts are summed per commodity.
        """
        totals: dict[str, object] = {}  # commodity -> Amount
        for posting in txn.postings:
            if posting.account != self.account:
                continue
            for amount in posting.amounts:
                if amount.commodity in totals:
                    from hledger_tui.models import Amount
                    prev = totals[amount.commodity]
                    totals[amount.commodity] = Amount(
                        commodity=amount.commodity,
                        quantity=prev.quantity + amount.quantity,  # type: ignore[union-attr]
                        style=amount.style,
                    )
                else:
                    totals[amount.commodity] = amount

        if not totals:
            return ""
        return "  ".join(a.format() for a in totals.values())  # type: ignore[union-attr]

    # --- Actions ---

    def action_back(self) -> None:
        """Pop this screen and return to the accounts list."""
        self.app.pop_screen()

    def action_cursor_down(self) -> None:
        """Move the cursor down one row."""
        self.query_one("#acctxn-table", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move the cursor up one row."""
        self.query_one("#acctxn-table", DataTable).action_cursor_up()
