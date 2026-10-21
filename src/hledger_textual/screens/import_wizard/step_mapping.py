"""Step 1 of the import wizard: column-to-field mapping."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Label, Select, Static

from hledger_textual.screens.import_wizard.state import WizardState

FIELD_OPTIONS = [
    ("(skip)", ""),
    ("date", "date"),
    ("date2", "date2"),
    ("status", "status"),
    ("code", "code"),
    ("description", "description"),
    ("comment", "comment"),
    ("amount", "amount"),
    ("amount-in", "amount-in"),
    ("amount-out", "amount-out"),
    ("currency", "currency"),
    ("account1", "account1"),
    ("account2", "account2"),
]


class MappingStep(VerticalScroll):
    """Column mapping step: one field Select per CSV column."""

    def __init__(self, state: WizardState) -> None:
        """Initialize the step.

        Args:
            state: The shared wizard state.
        """
        super().__init__(id="wizard-step-1", classes="wizard-step")
        self._state = state

    def compose(self) -> ComposeResult:
        """Create the mapping layout."""
        yield Static("Column Mapping", classes="wizard-step-title")
        yield Static(
            "Map each CSV column to a journal field:",
            id="wizard-mapping-hint",
        )
        yield Vertical(id="wizard-mapping-container")

    async def populate_mapping(self) -> None:
        """Build the column mapping widgets from the shared state."""
        container = self.query_one("#wizard-mapping-container", Vertical)
        await container.remove_children()

        for i, col_name in enumerate(self._state.column_names):
            sample_val = ""
            if self._state.sample_rows and i < len(self._state.sample_rows[0]):
                sample_val = self._state.sample_rows[0][i]

            initial = (
                self._state.field_mapping[i] if i < len(self._state.field_mapping) else ""
            )

            row = Horizontal(classes="mapping-row", id=f"mapping-row-{i}")
            label = Label(f'"{col_name}"', classes="mapping-label")
            select = Select(
                options=FIELD_OPTIONS,
                value=initial,
                id=f"mapping-select-{i}",
                classes="mapping-select",
            )
            sample = Static(f"  {sample_val}", classes="mapping-sample")
            row.compose_add_child(label)
            row.compose_add_child(select)
            row.compose_add_child(sample)
            container.mount(row)
