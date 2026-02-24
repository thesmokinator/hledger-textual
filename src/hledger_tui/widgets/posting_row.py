"""Reusable posting row widget for the transaction form."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.suggester import SuggestFromList
from textual.widget import Widget
from textual.widgets import Input, Label

from hledger_tui.widgets.autocomplete_input import AutocompleteInput


class PostingRow(Widget):
    """A single posting row with account (with autocomplete), amount, and commodity inputs."""

    def __init__(
        self,
        label: str = "Account:",
        account: str = "",
        amount: str = "",
        commodity: str = "",
        row_index: int = 0,
        account_suggestions: list[str] | None = None,
    ) -> None:
        """Initialize the posting row.

        Args:
            label: Label for this posting row.
            account: Initial account name.
            amount: Initial amount string.
            commodity: Initial commodity symbol.
            row_index: Index of this row.
            account_suggestions: List of account names for autocomplete.
        """
        super().__init__()
        self.initial_label = label
        self.initial_account = account
        self.initial_amount = amount
        self.initial_commodity = commodity
        self.row_index = row_index
        self.account_suggestions = account_suggestions or []

    def compose(self) -> ComposeResult:
        """Create the posting row layout."""
        suggester = (
            SuggestFromList(self.account_suggestions, case_sensitive=False)
            if self.account_suggestions
            else None
        )

        with Horizontal(classes="posting-row"):
            yield Label(self.initial_label, classes="posting-label")
            yield AutocompleteInput(
                value=self.initial_account,
                placeholder="e.g. expenses:food",
                classes="account-input",
                id=f"account-{self.row_index}",
                suggester=suggester,
            )
            yield Input(
                value=self.initial_amount,
                placeholder="Amount",
                classes="amount-input",
                id=f"amount-{self.row_index}",
            )
            yield Input(
                value=self.initial_commodity,
                placeholder="€",
                classes="commodity-input",
                id=f"commodity-{self.row_index}",
            )

    @property
    def account(self) -> str:
        """Get the current account value."""
        return self.query_one(f"#account-{self.row_index}", Input).value.strip()

    @property
    def amount(self) -> str:
        """Get the current amount value."""
        return self.query_one(f"#amount-{self.row_index}", Input).value.strip()

    @property
    def commodity(self) -> str:
        """Get the current commodity value."""
        return self.query_one(f"#commodity-{self.row_index}", Input).value.strip()
