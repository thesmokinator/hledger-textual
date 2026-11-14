"""Step 1 of the import wizard: column-to-field mapping."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Label, Select, Static

from hledger_textual.screens.import_wizard.state import WizardState
from hledger_textual.widgets.constants import FIELD_OPTIONS


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
            "Map each column to a journal field:",
            id="wizard-mapping-hint",
        )
        yield Vertical(id="wizard-mapping-container")
        yield Static("", id="wizard-mapping-error", classes="wizard-error")

    async def populate_mapping(self) -> None:
        """Build the column mapping widgets from the shared state."""
        container = self.query_one("#wizard-mapping-container", Vertical)
        await container.remove_children()
        self.clear_error()

        for i, col_name in enumerate(self._state.column_names):
            sample_val = ""
            if self._state.sample_rows and i < len(self._state.sample_rows[0]):
                sample_val = self._state.sample_rows[0][i]

            initial = (
                self._state.field_mapping[i] if i < len(self._state.field_mapping) else ""
            )
            suggested = (
                bool(initial)
                and i < len(self._state.auto_suggested)
                and self._state.auto_suggested[i]
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
            if suggested:
                row.compose_add_child(
                    Static("[suggested]", classes="mapping-suggested",
                           id=f"mapping-suggested-{i}")
                )
            await container.mount(row)

    @on(Select.Changed)
    def _on_mapping_select_changed(self, event: Select.Changed) -> None:
        """Clear the suggestion badge once the user touches a Select.

        Args:
            event: The Select change event.
        """
        select_id = event.select.id or ""
        if not select_id.startswith("mapping-select-"):
            return
        try:
            idx = int(select_id[len("mapping-select-"):])
        except ValueError:
            return
        new_value = "" if event.value == Select.BLANK else str(event.value)
        if idx < len(self._state.field_mapping):
            if self._state.field_mapping[idx] == new_value:
                # Mount-time sync of the initial value, not a user change.
                return
            self._state.field_mapping[idx] = new_value
        if idx < len(self._state.auto_suggested):
            self._state.auto_suggested[idx] = False
        try:
            badge = self.query_one(f"#mapping-suggested-{idx}", Static)
        except Exception:
            return
        badge.remove()

    def set_error(self, message: str) -> None:
        """Show an inline validation error below the mapping rows.

        Args:
            message: The error text to display.
        """
        self.query_one("#wizard-mapping-error", Static).update(
            f"[red]⛔ {message}[/red]"
        )

    def clear_error(self) -> None:
        """Hide the inline validation error."""
        try:
            self.query_one("#wizard-mapping-error", Static).update("")
        except Exception:
            pass
