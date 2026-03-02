"""Delete confirmation modal for recurring rules."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from hledger_textual.models import RecurringRule


class RecurringDeleteConfirmModal(ModalScreen[bool]):
    """A modal dialog to confirm recurring rule deletion."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, rule: RecurringRule) -> None:
        """Initialize the modal.

        Args:
            rule: The recurring rule to confirm deletion of.
        """
        super().__init__()
        self.rule = rule

    def compose(self) -> ComposeResult:
        """Create the modal layout."""
        summary = f"{self.rule.period_expr}  {self.rule.description}"

        with Vertical(id="recurring-delete-dialog"):
            yield Label("Delete Recurring Rule?", id="recurring-delete-title")
            yield Static(summary, id="recurring-delete-summary")
            with Horizontal(id="recurring-delete-buttons"):
                yield Button("Delete", variant="error", id="btn-recurring-delete")
                yield Button("Cancel", variant="default", id="btn-recurring-del-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-recurring-delete":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        """Cancel deletion."""
        self.dismiss(False)
