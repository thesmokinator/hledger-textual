"""Modal screen for saving the current period as a named view."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from hledger_textual.config import save_period_view


class SavePeriodViewModal(ModalScreen[str | None]):
    """Prompt for a name and persist the active period selection.

    Dismisses with the saved name on Enter, or with ``None`` when closed
    without saving.
    """

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Cancel", show=True),
    ]

    def __init__(
        self, current_expr: str, initial_name: str = "", **kwargs
    ) -> None:
        """Initialise the modal.

        Args:
            current_expr: The period expression to save (``""`` = All time).
            initial_name: Prefilled name (used when renaming a view).
        """
        super().__init__(**kwargs)
        self._current_expr = current_expr
        self._initial_name = initial_name

    def compose(self) -> ComposeResult:
        """Render the save dialog."""
        with Vertical(id="save-period-view-dialog"):
            yield Static("Save Period View", id="save-period-view-title")
            yield Static(
                f"Period: {self._current_expr or 'All time'}",
                id="save-period-view-expr",
            )
            yield Input(
                placeholder="View name… (press Enter to save)",
                id="save-period-view-name-input",
            )
            yield Static(
                "Enter: save  ·  Escape: cancel",
                id="save-period-view-hint",
            )

    def on_mount(self) -> None:
        """Prefill the name input and focus it."""
        name_input = self.query_one("#save-period-view-name-input", Input)
        name_input.value = self._initial_name
        name_input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Save the view and close the modal."""
        name = event.value.strip()
        if not name:
            return
        save_period_view(name, self._current_expr)
        self.dismiss(name)

    def action_dismiss_modal(self) -> None:
        """Close without saving."""
        self.dismiss(None)
