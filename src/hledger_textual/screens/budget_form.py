"""Budget rule form modal for creating and editing budget rules."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Button, Input, Label, Static

from hledger_textual.hledger import HledgerError, load_accounts
from hledger_textual.models import Amount, AmountStyle, BudgetRule
from hledger_textual.widgets.amount_input import AmountInput
from hledger_textual.widgets.autocomplete_input import AutocompleteInput


class BudgetFormScreen(ModalScreen[BudgetRule | None]):
    """Centered modal form for creating or editing a budget rule."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        journal_file: Path,
        rule: BudgetRule | None = None,
    ) -> None:
        """Initialize the form modal.

        Args:
            journal_file: Path to the journal file.
            rule: Existing budget rule to edit, or None for new.
        """
        super().__init__()
        self.journal_file = journal_file
        self.rule = rule

    @property
    def is_edit(self) -> bool:
        """Whether this form is editing an existing rule."""
        return self.rule is not None

    def compose(self) -> ComposeResult:
        """Create the modal form layout."""
        title = "Edit Budget Rule" if self.is_edit else "New Budget Rule"

        with Vertical(id="budget-form-dialog"):
            yield Static(title, id="budget-form-title")

            with Horizontal(classes="form-field"):
                yield Label("Account:")
                yield AutocompleteInput(
                    value=self.rule.account if self.is_edit else "",
                    placeholder="e.g. Expenses:Groceries",
                    id="budget-input-account",
                )

            with Horizontal(classes="form-field"):
                yield Label("Amount:")
                yield AmountInput(
                    value=f"{self.rule.amount.quantity:.2f}" if self.is_edit else "",
                    id="budget-input-amount",
                )

            with Horizontal(classes="form-field"):
                yield Label("Commodity:")
                yield Input(
                    value=self.rule.amount.commodity if self.is_edit else "\u20ac",
                    placeholder="\u20ac",
                    id="budget-input-commodity",
                )

            with Horizontal(id="budget-form-buttons"):
                yield Button("Cancel", id="btn-budget-cancel")
                yield Button("Save", id="btn-budget-save")

    def on_mount(self) -> None:
        """Load accounts for autocomplete."""
        try:
            accounts = load_accounts(self.journal_file)
        except HledgerError:
            accounts = []

        if accounts:
            self.query_one("#budget-input-account", AutocompleteInput).suggester = (
                SuggestFromList(accounts, case_sensitive=False)
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-budget-save":
            self._save()
        elif event.button.id == "btn-budget-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel the form."""
        self.dismiss(None)

    def _save(self) -> None:
        """Validate and save the budget rule."""
        account = self.query_one("#budget-input-account", Input).value.strip()
        amount_str = self.query_one("#budget-input-amount", Input).value.strip()
        commodity = self.query_one("#budget-input-commodity", Input).value.strip()

        if not account:
            self.notify("Account is required", severity="error", timeout=3)
            return

        if not amount_str:
            self.notify("Amount is required", severity="error", timeout=3)
            return

        try:
            quantity = Decimal(amount_str)
        except InvalidOperation:
            self.notify(f"Invalid amount: {amount_str}", severity="error", timeout=3)
            return

        if quantity <= 0:
            self.notify("Amount must be positive", severity="error", timeout=3)
            return

        if not commodity:
            commodity = "\u20ac"

        style = AmountStyle(
            commodity_side="L",
            commodity_spaced=False,
            precision=max(
                abs(quantity.as_tuple().exponent)
                if isinstance(quantity.as_tuple().exponent, int)
                else 2,
                2,
            ),
        )

        rule = BudgetRule(
            account=account,
            amount=Amount(commodity=commodity, quantity=quantity, style=style),
        )
        self.dismiss(rule)
