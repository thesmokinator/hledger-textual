"""Tests for the AutocompleteInput widget."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.suggester import SuggestFromList
from textual.widgets import Input

from hledger_textual.widgets.autocomplete_input import AutocompleteInput


class AutocompleteApp(App):
    """Minimal app to test AutocompleteInput."""

    def __init__(self, suggestions: list[str]) -> None:
        super().__init__()
        self.suggestions = suggestions

    def compose(self) -> ComposeResult:
        yield AutocompleteInput(
            id="ac-input",
            suggester=SuggestFromList(self.suggestions, case_sensitive=False),
        )
        yield Input(id="other-input", placeholder="Other field")


class TestAutocompleteInput:
    """Tests for Tab-to-accept autocomplete."""

    async def test_tab_accepts_suggestion(self):
        app = AutocompleteApp(["expenses:food:groceries", "expenses:office"])
        async with app.run_test(size=(80, 10)) as pilot:
            ac = app.query_one("#ac-input", AutocompleteInput)
            ac.focus()
            # Type enough to trigger a suggestion
            app.query_one("#ac-input", AutocompleteInput).value = "expenses:f"
            await pilot.pause()
            # The suggester should suggest "expenses:food:groceries"
            # Give it time to compute
            await pilot.pause()

            # Press tab to accept
            await pilot.press("tab")
            await pilot.pause()

            assert ac.value == "expenses:food:groceries"

    async def test_tab_moves_focus_without_suggestion(self):
        app = AutocompleteApp(["expenses:food:groceries"])
        async with app.run_test(size=(80, 10)) as pilot:
            ac = app.query_one("#ac-input", AutocompleteInput)
            ac.focus()
            # No text, no suggestion
            await pilot.pause()
            await pilot.press("tab")
            await pilot.pause()

            # Focus should have moved to the other input
            assert app.focused.id == "other-input"

    async def test_tab_moves_focus_when_suggestion_matches_value(self):
        app = AutocompleteApp(["expenses:food:groceries"])
        async with app.run_test(size=(80, 10)) as pilot:
            ac = app.query_one("#ac-input", AutocompleteInput)
            ac.focus()
            ac.value = "expenses:food:groceries"
            await pilot.pause()
            await pilot.pause()

            await pilot.press("tab")
            await pilot.pause()

            # Suggestion already matches, so Tab should move focus
            assert app.focused.id == "other-input"

    async def test_case_insensitive_suggestion(self):
        app = AutocompleteApp(["Assets:Bank:Checking"])
        async with app.run_test(size=(80, 10)) as pilot:
            ac = app.query_one("#ac-input", AutocompleteInput)
            ac.focus()
            ac.value = "assets"
            await pilot.pause()
            await pilot.pause()

            await pilot.press("tab")
            await pilot.pause()

            assert ac.value == "Assets:Bank:Checking"
