"""Shared account suggestion setup for form screens."""

from __future__ import annotations

from pathlib import Path

from textual.suggester import SuggestFromList

from hledger_textual.hledger import HledgerError, load_accounts
from hledger_textual.widgets.autocomplete_input import AutocompleteInput


class FormAccountSuggestionsMixin:
    """Load journal accounts and optionally attach autocomplete suggestions."""

    journal_file: Path
    accounts: list[str]

    def _configure_account_suggestions(self, *widget_ids: str) -> None:
        """Load accounts into ``self.accounts`` and apply them to widget ids."""
        try:
            accounts = load_accounts(self.journal_file)
        except HledgerError:
            accounts = []

        self.accounts = accounts
        if not accounts:
            return

        suggester = SuggestFromList(accounts, case_sensitive=False)
        for widget_id in widget_ids:
            self.query_one(f"#{widget_id}", AutocompleteInput).suggester = suggester
