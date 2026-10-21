"""Step 3 of the import wizard: conditional categorization rules."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.suggester import SuggestFromList
from textual.widgets import Button, Input, Static

from hledger_textual.screens.import_wizard.state import WizardState
from hledger_textual.widgets.autocomplete_input import AutocompleteInput


class RulesStep(VerticalScroll):
    """Conditional rules step: description-pattern to account assignments."""

    def __init__(self, state: WizardState) -> None:
        """Initialize the step.

        Args:
            state: The shared wizard state.
        """
        super().__init__(id="wizard-step-3", classes="wizard-step")
        self._state = state

    def compose(self) -> ComposeResult:
        """Create the conditional rules layout."""
        yield Static("Categorization Rules", classes="wizard-step-title")
        yield Static(
            "When description matches... assign to account:",
            id="wizard-conditional-hint",
        )
        yield Vertical(id="wizard-conditional-container")
        with Horizontal(id="wizard-conditional-buttons"):
            yield Button("\\[+] Add rule", id="btn-wizard-add-rule")
            yield Button("\\[-] Remove last", id="btn-wizard-remove-rule")
        yield Static(
            "Optional. Unmatched transactions use expenses:unknown / income:unknown.",
            id="wizard-conditional-note",
        )

    def add_conditional_rule(self, pattern: str = "", account2: str = "") -> None:
        """Add a conditional rule row.

        Args:
            pattern: Initial description pattern for the row.
            account2: Initial target account for the row.
        """
        container = self.query_one("#wizard-conditional-container", Vertical)
        idx = self._state.conditional_rule_count

        row = Horizontal(classes="conditional-rule-row", id=f"cond-rule-{idx}")
        pattern_input = Input(
            value=pattern,
            placeholder="pattern (e.g. grocery|food)",
            id=f"cond-pattern-{idx}",
            classes="cond-pattern",
        )
        acct_input = AutocompleteInput(
            value=account2,
            placeholder="account (e.g. expenses:groceries)",
            id=f"cond-account-{idx}",
            classes="cond-account",
        )
        acct_input.suggester = SuggestFromList(
            self._state.accounts, case_sensitive=False
        )

        container.mount(row)
        row.mount(pattern_input)
        row.mount(acct_input)
        self._state.conditional_rule_count += 1

    def remove_last_conditional_rule(self) -> bool:
        """Remove the last conditional rule row.

        Returns:
            True when a row was removed, False when there was none.
        """
        container = self.query_one("#wizard-conditional-container", Vertical)
        children = list(container.children)
        if children:
            children[-1].remove()
            self._state.conditional_rule_count -= 1
            return True
        return False
