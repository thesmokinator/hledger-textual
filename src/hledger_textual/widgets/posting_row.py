"""Reusable posting row widget for the transaction form."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.suggester import SuggestFromList
from textual.widget import Widget
from textual.widgets import Input, Label

from hledger_textual.models import Amount
from hledger_textual.widgets.amount_input import AmountInput
from hledger_textual.widgets.autocomplete_input import AutocompleteInput


class PostingRow(Widget):
    """A single posting row with account (with autocomplete) and amount inputs.

    The default commodity is displayed as a read-only label next to the amount
    field. Users can override it by including the currency or commodity directly
    in the amount string (e.g. ``€50.00``, ``-5 XEON @@ €742.55``).
    """

    def __init__(
        self,
        label: str = "Account:",
        account: str = "",
        amount: str = "",
        commodity: str = "",
        row_index: int = 0,
        account_suggestions: list[str] | None = None,
        initial_amounts: list[Amount] | None = None,
    ) -> None:
        """Initialize the posting row.

        Args:
            label: Label for this posting row.
            account: Initial account name.
            amount: Initial amount string.
            commodity: Default commodity shown as a label (e.g. ``€``).
            row_index: Index of this row.
            account_suggestions: List of account names for autocomplete.
            initial_amounts: The original :class:`Amount` objects from which
                *amount* was derived, when editing an existing transaction.
                When the user does not modify *amount*, the form reuses these
                objects verbatim at save time so that locale-specific styles
                (European digit grouping, decimal mark, etc.) are preserved
                rather than lost to the default US parser.
        """
        super().__init__()
        self.initial_label = label
        self.initial_account = account
        self.initial_amount = amount
        self.initial_commodity = commodity
        self.row_index = row_index
        self.account_suggestions = account_suggestions or []
        self.initial_amounts = initial_amounts

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
            yield AmountInput(
                value=self.initial_amount,
                classes="amount-input",
                id=f"amount-{self.row_index}",
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
        """Get the default commodity (static label value)."""
        return self.initial_commodity
