"""Step 4 of the import wizard: review and save the generated rules."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static, TextArea

from hledger_textual.screens.import_wizard.state import WizardState


class ReviewStep(Vertical):
    """Review step: the generated rules file in an editable text area."""

    def __init__(self, state: WizardState) -> None:
        """Initialize the step.

        Args:
            state: The shared wizard state.
        """
        super().__init__(id="wizard-step-4", classes="wizard-step")
        self._state = state

    def compose(self) -> ComposeResult:
        """Create the review layout."""
        yield Static("Review & Save", classes="wizard-step-title")
        yield TextArea(id="wizard-raw-editor")
