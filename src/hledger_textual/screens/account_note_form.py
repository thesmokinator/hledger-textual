"""Modal dialog for editing an account note/comment."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea

from hledger_textual.screens._dirty_guard import DirtyGuardMixin


class AccountNoteModal(DirtyGuardMixin, ModalScreen[str | None]):
    """A simple modal to edit the note attached to an account directive."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, account: str, current_note: str) -> None:
        """Initialize the modal.

        Args:
            account: The full account name.
            current_note: The current note text (may be empty).
        """
        super().__init__()
        self._account = account
        self._current_note = current_note

    def compose(self) -> ComposeResult:
        """Create the modal layout."""
        with Vertical(id="note-dialog"):
            yield Label(f"Note for {self._account}", id="note-title")
            yield TextArea(
                self._current_note,
                id="note-input",
            )
            with Horizontal(id="note-buttons"):
                yield Button("Cancel", variant="default", id="btn-note-cancel")
                yield Button("Save", variant="primary", id="btn-note-save")

    def on_mount(self) -> None:
        """Focus the text area on mount."""
        self.query_one("#note-input", TextArea).focus()
        self.call_after_refresh(self.capture_initial_state)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-note-save":
            note = self.query_one("#note-input", TextArea).text.strip()
            self.dismiss(note)
        else:
            self.action_cancel()
