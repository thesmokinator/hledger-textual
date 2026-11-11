"""Pilot tests for the saved-filters browser modal (85% push)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable

from hledger_textual.screens.saved_filters import SavedFiltersModal


class _SavedApp(App):
    """Minimal app that pushes SavedFiltersModal on mount."""

    def compose(self) -> ComposeResult:
        from textual.widgets import Label

        yield Label("base")

    async def on_mount(self) -> None:
        self.push_screen(SavedFiltersModal())


@pytest.fixture
def filters_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at a temp path seeded with two filters."""
    from hledger_textual.config import save_filter

    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    save_filter("food", "expenses:food")
    save_filter("rent", "expenses:rent")
    return config_file


@pytest.fixture
def empty_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at an empty temp path."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    return config_file


class TestSavedFiltersModal:
    """Empty state, populated table, apply, delete and cancel paths."""

    async def test_empty_table_shows_placeholder(self, empty_config: Path) -> None:
        """No saved filters renders the placeholder row."""
        app = _SavedApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, SavedFiltersModal)
            table = app.screen.query_one("#saved-filters-table", DataTable)
            assert table.row_count == 1

    async def test_populated_table_lists_filters(self, filters_config: Path) -> None:
        """Each saved filter gets a table row keyed by name."""
        app = _SavedApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#saved-filters-table", DataTable)
            assert table.row_count == 2

    async def test_row_selected_applies_query(self, filters_config: Path) -> None:
        """Selecting a row dismisses with the stored query."""
        app = _SavedApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, SavedFiltersModal)
            dismissed: list = []
            modal.dismiss = dismissed.append  # type: ignore[method-assign]
            event = SimpleNamespace(
                row_key=SimpleNamespace(value="food"),
            )
            modal.on_data_table_row_selected(event)
            assert dismissed == ["expenses:food"]

    async def test_placeholder_row_does_not_apply(self, empty_config: Path) -> None:
        """The placeholder row never dismisses the modal."""
        app = _SavedApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, SavedFiltersModal)
            dismissed: list = []
            modal.dismiss = dismissed.append  # type: ignore[method-assign]
            event = SimpleNamespace(
                row_key=SimpleNamespace(value="__empty__"),
            )
            modal.on_data_table_row_selected(event)
            assert dismissed == []

    async def test_delete_removes_filter(self, filters_config: Path) -> None:
        """'d' deletes the highlighted filter and refreshes the table."""
        from hledger_textual.config import load_saved_filters

        app = _SavedApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#saved-filters-table", DataTable)
            assert table.row_count == 2
            await pilot.press("d")
            await pilot.pause()
            assert load_saved_filters() == {"rent": "expenses:rent"}

    async def test_escape_cancels(self, filters_config: Path) -> None:
        """Escape closes without applying."""
        app = _SavedApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, SavedFiltersModal)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, SavedFiltersModal)
