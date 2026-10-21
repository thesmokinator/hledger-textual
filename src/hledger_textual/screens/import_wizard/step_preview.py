"""Step 0 of the import wizard: CSV preview with separator/header options."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Label, Select, Static

from hledger_textual.screens.import_wizard.state import WizardState
from hledger_textual.widgets.constants import HEADER_OPTIONS, SEPARATOR_OPTIONS



class PreviewStep(Vertical):
    """CSV preview step: separator/header selects plus a preview table."""

    def __init__(self, state: WizardState) -> None:
        """Initialize the step.

        Args:
            state: The shared wizard state.
        """
        super().__init__(id="wizard-step-0", classes="wizard-step")
        self._state = state

    def compose(self) -> ComposeResult:
        """Create the preview layout."""
        yield Static("CSV Preview", classes="wizard-step-title")
        with Horizontal(classes="form-field form-field--required"):
            yield Label("Separator:*")
            yield Select(
                options=SEPARATOR_OPTIONS,
                value=",",
                id="wizard-separator",
            )
        with Horizontal(classes="form-field form-field--required"):
            yield Label("Header row:*")
            yield Select(
                options=HEADER_OPTIONS,
                value="yes",
                id="wizard-header",
            )
        yield DataTable(id="wizard-csv-preview")

    def populate_preview(self) -> None:
        """Fill the CSV preview DataTable from the shared state."""
        table = self.query_one("#wizard-csv-preview", DataTable)
        table.clear(columns=True)
        table.cursor_type = "none"

        if not self._state.column_names and not self._state.sample_rows:
            return

        for col_name in self._state.column_names:
            table.add_column(col_name, width=max(len(col_name) + 2, 12))

        for row in self._state.sample_rows[:10]:
            # Pad row if shorter than columns
            padded = row + [""] * (len(self._state.column_names) - len(row))
            table.add_row(*padded[: len(self._state.column_names)])
