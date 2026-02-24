"""Delete confirmation modal screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from hledger_tui.models import Transaction


class DeleteConfirmModal(ModalScreen[bool]):
    """A modal dialog to confirm transaction deletion."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, transaction: Transaction) -> None:
        """Initialize the modal.

        Args:
            transaction: The transaction to confirm deletion of.
        """
        super().__init__()
        self.transaction = transaction

    def compose(self) -> ComposeResult:
        """Create the modal layout."""
        txn = self.transaction
        status = f" {txn.status.symbol}" if txn.status.symbol else ""
        summary = f"{txn.date}{status} {txn.description}"
        postings_summary = "\n".join(
            f"  {p.account}" for p in txn.postings
        )

        with Vertical(id="delete-dialog"):
            yield Label("Delete Transaction?", id="delete-title")
            yield Static(
                f"{summary}\n{postings_summary}",
                id="delete-summary",
            )
            with Horizontal(id="delete-buttons"):
                yield Button("Delete", variant="error", id="btn-delete")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-delete":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        """Cancel deletion."""
        self.dismiss(False)
