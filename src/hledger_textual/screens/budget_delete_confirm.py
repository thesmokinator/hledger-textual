"""Delete confirmation modal for budget rules."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from hledger_textual.models import BudgetRule


class BudgetDeleteConfirmModal(ModalScreen[bool]):
    """A modal dialog to confirm budget rule deletion."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, rule: BudgetRule) -> None:
        """Initialize the modal.

        Args:
            rule: The budget rule to confirm deletion of.
        """
        super().__init__()
        self.rule = rule

    def compose(self) -> ComposeResult:
        """Create the modal layout."""
        summary = f"{self.rule.account}  {self.rule.amount.format()}"

        with Vertical(id="budget-delete-dialog"):
            yield Label("Delete Budget Rule?", id="budget-delete-title")
            yield Static(summary, id="budget-delete-summary")
            with Horizontal(id="budget-delete-buttons"):
                yield Button("Delete", variant="error", id="btn-budget-delete")
                yield Button("Cancel", variant="default", id="btn-budget-del-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-budget-delete":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        """Cancel deletion."""
        self.dismiss(False)
