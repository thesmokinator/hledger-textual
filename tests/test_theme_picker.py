"""Tests for the ThemePickerModal screen."""

from __future__ import annotations

from pathlib import Path

import pytest

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import OptionList

from hledger_tui.config import save_theme
from hledger_tui.screens.theme_picker import THEMES, ThemePickerModal
from hledger_tui.widgets.info_pane import InfoPane
from tests.conftest import has_hledger


class _ThemeApp(App):
    """Minimal app with the t binding for testing the theme picker dialog."""

    BINDINGS = [
        Binding("t", "pick_theme", "Theme"),
    ]

    def __init__(self, journal_file: Path) -> None:
        """Initialize with a journal file path."""
        super().__init__()
        self._journal_file = journal_file

    def compose(self) -> ComposeResult:
        """Compose a single InfoPane."""
        yield InfoPane(self._journal_file)

    def action_pick_theme(self) -> None:
        """Open the theme picker dialog."""
        def on_theme_selected(theme: str | None) -> None:
            if theme is not None:
                self.theme = theme
                save_theme(theme)
                self.query_one(InfoPane).apply_theme(theme)

        self.push_screen(ThemePickerModal(), callback=on_theme_selected)


@pytest.fixture
def theme_journal(tmp_path: Path) -> Path:
    """A minimal journal for theme picker testing."""
    journal = tmp_path / "test.journal"
    journal.write_text(
        "2026-01-01 * Test\n"
        "    expenses:misc  €10.00\n"
        "    assets:bank\n"
    )
    return journal


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestThemePickerModal:
    """Tests for the ThemePickerModal."""

    async def test_t_key_opens_modal(self, theme_journal: Path, monkeypatch):
        """Pressing t opens the ThemePickerModal with all themes."""
        monkeypatch.setattr(
            "tests.test_theme_picker.save_theme", lambda t: None
        )
        app = _ThemeApp(theme_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            assert any(
                isinstance(s, ThemePickerModal) for s in app.screen_stack
            )
            option_list = app.screen.query_one("#theme-list", OptionList)
            assert option_list.option_count == len(THEMES)

    async def test_escape_dismisses_without_change(self, theme_journal: Path, monkeypatch):
        """Pressing Escape closes the dialog without changing theme."""
        monkeypatch.setattr(
            "tests.test_theme_picker.save_theme", lambda t: None
        )
        app = _ThemeApp(theme_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            original_theme = app.theme
            await pilot.press("t")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.theme == original_theme
            assert not any(
                isinstance(s, ThemePickerModal) for s in app.screen_stack
            )

    async def test_selecting_theme_applies_it(self, theme_journal: Path, monkeypatch):
        """Selecting a theme from the list applies it to the app."""
        monkeypatch.setattr(
            "tests.test_theme_picker.save_theme", lambda t: None
        )
        app = _ThemeApp(theme_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            # Navigate to "nord" (index 2) and select it
            option_list = app.screen.query_one("#theme-list", OptionList)
            option_list.highlighted = 2
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.theme == "nord"
