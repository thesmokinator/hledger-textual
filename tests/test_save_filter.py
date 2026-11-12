"""Pilot tests for the save-filter modal (85% push)."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from hledger_textual.app import HledgerTuiApp  # noqa: F401  (keeps import style)
from hledger_textual.screens.save_filter import SaveFilterModal


class _SaveApp(App):
    """Minimal app that pushes SaveFilterModal on mount."""

    def __init__(self, query: str) -> None:
        super().__init__()
        self._query = query

    def compose(self) -> ComposeResult:
        from textual.widgets import Label

        yield Label("base")

    async def on_mount(self) -> None:
        self.push_screen(SaveFilterModal(self._query))


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at a temp path."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    return config_file


class TestSaveFilterModal:
    """Save, empty-name no-op, and cancel paths."""

    async def test_submit_saves_filter(
        self, isolated_config: Path
    ) -> None:
        """Enter with a name persists the query under that name."""
        from textual.widgets import Input

        from hledger_textual.config import load_saved_filters

        app = _SaveApp("date:2026")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, SaveFilterModal)
            app.screen.query_one("#save-filter-name-input", Input).value = "mine"
            await pilot.press("enter")
            await pilot.pause()
        assert load_saved_filters() == {"mine": "date:2026"}

    async def test_empty_name_saves_nothing(
        self, isolated_config: Path
    ) -> None:
        """Enter with a blank name does not persist or dismiss."""
        from textual.widgets import Input

        from hledger_textual.config import load_saved_filters

        app = _SaveApp("date:2026")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, SaveFilterModal)
            app.screen.query_one("#save-filter-name-input", Input).value = "   "
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, SaveFilterModal)
        assert load_saved_filters() == {}

    async def test_escape_cancels_without_saving(
        self, isolated_config: Path
    ) -> None:
        """Escape closes the modal without persisting."""
        from textual.widgets import Input

        from hledger_textual.config import load_saved_filters

        app = _SaveApp("date:2026")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, SaveFilterModal)
            app.screen.query_one("#save-filter-name-input", Input).value = "nope"
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, SaveFilterModal)
        assert load_saved_filters() == {}
