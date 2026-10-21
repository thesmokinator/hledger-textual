"""Step 2 of the import wizard: basic rules settings."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, Static

from hledger_textual.config import load_default_commodity
from hledger_textual.screens.import_wizard.state import WizardState
from hledger_textual.widgets.autocomplete_input import AutocompleteInput


class SettingsStep(Vertical):
    """Settings step: rules name, bank account, currency, date format."""

    def __init__(self, state: WizardState) -> None:
        """Initialize the step.

        Args:
            state: The shared wizard state.
        """
        super().__init__(id="wizard-step-2", classes="wizard-step")
        self._state = state

    def compose(self) -> ComposeResult:
        """Create the settings layout."""
        yield Static("Settings", classes="wizard-step-title")
        with Horizontal(classes="form-field form-field--required"):
            yield Label("Rules name:*")
            yield Input(
                placeholder="e.g. UniCredit Checking",
                id="wizard-rules-name",
            )
        with Horizontal(classes="form-field form-field--required"):
            yield Label("Bank account:*")
            yield AutocompleteInput(
                placeholder="e.g. assets:bank:checking",
                id="wizard-account1",
            )
        with Horizontal(classes="form-field form-field--required"):
            yield Label("Currency:*")
            yield Input(
                value=load_default_commodity(),
                id="wizard-currency",
            )
        with Horizontal(classes="form-field form-field--required"):
            yield Label("Date format:*")
            yield Input(
                id="wizard-date-format",
            )
