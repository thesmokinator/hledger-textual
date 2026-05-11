"""Custom report form modal for creating and editing custom hledger reports."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from hledger_textual.models import CustomReport

_EXAMPLES: list[tuple[str, str]] = [
    ("balance --tree", "Full balance tree"),
    ("balance expenses --tree", "Expenses tree"),
    ("balance expenses --tree -M", "Monthly expenses tree"),
    ("balance income --tree", "Income tree"),
    ("balance assets --tree", "Assets tree"),
    ("register expenses -M", "Monthly expense register"),
    ("register income -M", "Monthly income register"),
    ("incomestatement -M", "Monthly income statement"),
    ("balancesheet", "Balance sheet"),
]


class CustomReportFormScreen(ModalScreen[CustomReport | None]):
    """Centered modal form for creating or editing a custom report."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, report: CustomReport | None = None) -> None:
        """Initialize the form modal.

        Args:
            report: Existing custom report to edit, or None for new.
        """
        super().__init__()
        self.report = report

    @property
    def is_edit(self) -> bool:
        """Whether this form is editing an existing report."""
        return self.report is not None

    def compose(self) -> ComposeResult:
        """Create the modal form layout."""
        title = "Edit Custom Report" if self.is_edit else "New Custom Report"

        with Vertical(id="custom-report-form-dialog"):
            yield Static(title, id="custom-report-form-title")

            with Horizontal(classes="form-field form-field--required"):
                yield Label("Name:*")
                yield Input(
                    value=self.report.name if self.is_edit else "",
                    placeholder="e.g. Monthly expenses tree",
                    id="custom-report-input-name",
                )

            with Horizontal(classes="form-field form-field--required"):
                yield Label("Command:*")
                yield Input(
                    value=self.report.command if self.is_edit else "",
                    placeholder="e.g. balance expenses --tree -M",
                    id="custom-report-input-command",
                )

            yield Label("Examples (click to fill command):", id="custom-report-examples-label")
            yield OptionList(
                *[Option(f"{cmd}  [{desc}]", id=cmd) for cmd, desc in _EXAMPLES],
                id="custom-report-examples",
            )

            yield Static("* required", classes="form-required-footer")

            with Horizontal(id="custom-report-form-buttons"):
                yield Button("Cancel", variant="default", id="btn-custom-report-cancel")
                yield Button("Save", variant="primary", id="btn-custom-report-save")

    @on(OptionList.OptionSelected, "#custom-report-examples")
    def on_example_selected(self, event: OptionList.OptionSelected) -> None:
        """Fill the Command input when an example is selected."""
        if event.option.id:
            self.query_one("#custom-report-input-command", Input).value = event.option.id

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-custom-report-save":
            self._save()
        elif event.button.id == "btn-custom-report-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel the form."""
        self.dismiss(None)

    def _save(self) -> None:
        """Validate and save the custom report."""
        name = self.query_one("#custom-report-input-name", Input).value.strip()
        command = self.query_one("#custom-report-input-command", Input).value.strip()

        if not name:
            self.notify("Name is required", severity="error", timeout=3)
            return

        if not command:
            self.notify("Command is required", severity="error", timeout=3)
            return

        self.dismiss(CustomReport(name=name, command=command))
