"""Git sync confirmation modal screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class SyncConfirmModal(ModalScreen[bool]):
    """A modal dialog to confirm git sync (commit + pull + push)."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        """Create the modal layout."""
        with Vertical(id="sync-dialog"):
            yield Label("Git Sync", id="sync-title")
            yield Label(
                "Are you sure you want to sync your repository and data?",
                id="sync-summary",
            )
            with Horizontal(id="sync-buttons"):
                yield Button("Sync", variant="primary", id="btn-sync")
                yield Button("Cancel", variant="default", id="btn-sync-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-sync":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        """Cancel sync."""
        self.dismiss(False)
