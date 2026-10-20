"""Move transaction confirmation modal screen."""

from __future__ import annotations

from datetime import date

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from hledger_textual.dateutil import describe_iso_date_error, shift_date_months
from hledger_textual.models import Transaction
from hledger_textual.widgets.date_input import DateInput


class MoveConfirmModal(ModalScreen[str | None]):
    """A modal dialog for moving a transaction to a different date.

    The user can press Left/Right arrows to shift by one month at a time,
    or type a custom date directly. Dismisses with the new date string
    or ``None`` if cancelled.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("left", "prev_month", "Previous month", priority=True),
        Binding("right", "next_month", "Next month", priority=True),
    ]

    def __init__(self, transaction: Transaction) -> None:
        """Initialize the modal.

        Args:
            transaction: The transaction being moved.
        """
        super().__init__()
        self.transaction = transaction
        try:
            self._original_date = date.fromisoformat(transaction.date)
        except ValueError:
            self._original_date = date.today()
        self._new_date = shift_date_months(self._original_date, 1)

    def compose(self) -> ComposeResult:
        """Create the modal layout."""
        txn = self.transaction
        status = f" {txn.status.symbol}" if txn.status.symbol else ""
        summary = f"{txn.date}{status} {txn.description}"

        with Vertical(id="move-dialog"):
            yield Label("Move Transaction", id="move-title")
            yield Static(summary, id="move-summary")
            with Horizontal(id="move-date-row"):
                yield Static(
                    "\u25c4", id="move-btn-prev", classes="move-arrow"
                )
                yield DateInput(
                    value=self._new_date.isoformat(),
                    id="move-date-input",
                )
                yield Static(
                    "\u25ba", id="move-btn-next", classes="move-arrow"
                )
            with Horizontal(id="move-buttons"):
                yield Button("Cancel", variant="default", id="btn-move-cancel")
                yield Button("Move", variant="primary", id="btn-move-confirm")

    def _update_date(self) -> None:
        """Update the date input with the current new date."""
        self.query_one("#move-date-input", DateInput).value = (
            self._new_date.isoformat()
        )

    def action_prev_month(self) -> None:
        """Shift the target date one month backward."""
        self._new_date = shift_date_months(self._new_date, -1)
        self._update_date()

    def action_next_month(self) -> None:
        """Shift the target date one month forward."""
        self._new_date = shift_date_months(self._new_date, 1)
        self._update_date()

    def on_click(self, event) -> None:
        """Handle clicks on the arrow labels."""
        widget_id = getattr(event.widget, "id", None)
        if widget_id == "move-btn-prev":
            self.action_prev_month()
        elif widget_id == "move-btn-next":
            self.action_next_month()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-move-confirm":
            new_date = self.query_one("#move-date-input", DateInput).value.strip()
            if not new_date:
                self.notify("Date is required", severity="error", timeout=3)
                return
            date_error = describe_iso_date_error(new_date)
            if date_error:
                self.notify(f"Invalid date: {date_error}", severity="error", timeout=4)
                return
            self.dismiss(new_date)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel the move."""
        self.dismiss(None)
