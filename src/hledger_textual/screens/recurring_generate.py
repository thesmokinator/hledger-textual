"""Generation confirmation modal for recurring transactions."""

from __future__ import annotations

from datetime import date

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label, Static

from hledger_textual.models import RecurringRule


class RecurringGenerateScreen(ModalScreen[bool]):
    """A modal dialog showing pending recurring transactions for confirmation."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        pending: list[tuple[RecurringRule, list[date]]],
    ) -> None:
        """Initialize the modal.

        Args:
            pending: List of (rule, dates) tuples for pending generations.
        """
        super().__init__()
        self.pending = pending

    def compose(self) -> ComposeResult:
        """Create the modal layout."""
        total = sum(len(dates) for _, dates in self.pending)

        with Vertical(id="recurring-generate-dialog"):
            yield Label(
                "Generate Recurring Transactions",
                id="recurring-generate-title",
            )

            yield DataTable(id="recurring-generate-table")

            yield Static(
                f"{total} transaction{'s' if total != 1 else ''} will be added to your journal",
                id="recurring-generate-summary",
            )

            with Horizontal(id="recurring-generate-buttons"):
                yield Button("Cancel", variant="default", id="btn-recurring-gen-cancel")
                yield Button("Generate All", variant="success", id="btn-recurring-generate")

    def on_mount(self) -> None:
        """Populate the preview table."""
        table = self.query_one("#recurring-generate-table", DataTable)
        table.cursor_type = "none"
        table.add_column("Period", width=16)
        table.add_column("Description", width=24)
        table.add_column("Date", width=12)
        table.add_column("Amount", width=14)

        for rule, dates in self.pending:
            # Get the primary amount for display
            amount_str = ""
            if rule.postings and rule.postings[0].amounts:
                amount_str = rule.postings[0].amounts[0].format()

            for d in dates:
                table.add_row(
                    rule.period_expr,
                    rule.description,
                    d.isoformat(),
                    amount_str,
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-recurring-generate":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        """Cancel generation."""
        self.dismiss(False)
