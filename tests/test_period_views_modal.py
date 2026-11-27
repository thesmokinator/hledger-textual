"""Tests for the period presets modal and save-view modal (issue #277)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable

from hledger_textual.screens.period_presets import PeriodPresetsModal
from hledger_textual.screens.save_period_view import SavePeriodViewModal


@pytest.fixture
def views_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at a temp path seeded with two period views."""
    from hledger_textual.config import save_period_view

    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    save_period_view("FY2024", "2024")
    save_period_view("Q3", "2024-07..2024-09")
    return config_file


@pytest.fixture
def empty_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at an empty temp path."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    return config_file


@pytest.fixture
def bad_view_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Seed a view whose expression no longer parses."""
    from hledger_textual.config import save_period_view

    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    save_period_view("Broken", "not-a-period")
    return config_file


class _PresetsApp(App):
    """Minimal app that pushes PeriodPresetsModal on mount."""

    def __init__(self, today: date) -> None:
        super().__init__()
        self._today = today

    def compose(self) -> ComposeResult:
        from textual.widgets import Label

        yield Label("base")

    async def on_mount(self) -> None:
        self.push_screen(PeriodPresetsModal(today=self._today))


def _select(modal: PeriodPresetsModal, key: str) -> None:
    """Drive row selection without a pilot."""
    modal.on_data_table_row_selected(
        SimpleNamespace(row_key=SimpleNamespace(value=key))
    )


class TestPeriodPresetsModal:
    """Preset rows, view rows, apply, delete and fallback paths."""

    async def test_empty_views_still_lists_all_presets(
        self, empty_config: Path
    ) -> None:
        app = _PresetsApp(date(2024, 6, 15))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#period-presets-table", DataTable)
            assert table.row_count == 7

    async def test_views_appended_after_presets(self, views_config: Path) -> None:
        app = _PresetsApp(date(2024, 6, 15))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#period-presets-table", DataTable)
            assert table.row_count == 7 + 2

    async def test_enter_on_preset_dismisses_selection(
        self, empty_config: Path
    ) -> None:
        from hledger_textual.period import year_selection

        app = _PresetsApp(date(2024, 6, 15))
        async with app.run_test() as pilot:
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, PeriodPresetsModal)
            dismissed: list = []
            modal.dismiss = dismissed.append  # type: ignore[method-assign]
            _select(modal, "preset:this-year")
            assert len(dismissed) == 1
            expected = year_selection(2024)
            assert (dismissed[0].begin, dismissed[0].end) == (
                expected.begin,
                expected.end,
            )

    async def test_enter_on_view_parses_stored_expression(
        self, views_config: Path
    ) -> None:
        app = _PresetsApp(date(2024, 6, 15))
        async with app.run_test() as pilot:
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, PeriodPresetsModal)
            dismissed: list = []
            modal.dismiss = dismissed.append  # type: ignore[method-assign]
            _select(modal, "view:FY2024")
            assert len(dismissed) == 1
            assert dismissed[0].period_expr == "2024"

    async def test_unparseable_view_falls_back_to_all_time(
        self, bad_view_config: Path
    ) -> None:
        app = _PresetsApp(date(2024, 6, 15))
        async with app.run_test() as pilot:
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, PeriodPresetsModal)
            dismissed: list = []
            modal.dismiss = dismissed.append  # type: ignore[method-assign]
            _select(modal, "view:Broken")
            assert len(dismissed) == 1
            assert dismissed[0].kind == "all"

    async def test_rename_flow_renames_view(
        self, views_config: Path
    ) -> None:
        from textual.widgets import Input

        from hledger_textual.config import load_period_views
        from hledger_textual.screens.save_period_view import SavePeriodViewModal

        app = _PresetsApp(date(2024, 6, 15))
        async with app.run_test() as pilot:
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, PeriodPresetsModal)
            table = modal.query_one("#period-presets-table", DataTable)
            table.move_cursor(row=7)  # first view row: FY2024
            await pilot.pause()
            modal.action_rename_selected()
            await pilot.pause()
            save_modal = app.screen
            assert isinstance(save_modal, SavePeriodViewModal)
            assert (
                save_modal.query_one("#save-period-view-name-input", Input).value
                == "FY2024"
            )
            save_modal.on_input_submitted(SimpleNamespace(value="FY25"))
            await pilot.pause()
            views = load_period_views()
            assert views.get("FY25") == "2024"
            assert "FY2024" not in views

    async def test_delete_removes_view_only(
        self, views_config: Path
    ) -> None:
        from hledger_textual.config import load_period_views

        app = _PresetsApp(date(2024, 6, 15))
        async with app.run_test() as pilot:
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, PeriodPresetsModal)
            table = modal.query_one("#period-presets-table", DataTable)
            # Move cursor to a view row: presets first, then views.
            table.move_cursor(row=7)
            await pilot.pause()
            modal.action_delete_selected()
            await pilot.pause()
            assert "FY2024" not in load_period_views()
            assert table.row_count == 7 + 1

    async def test_delete_on_preset_row_is_noop(
        self, views_config: Path
    ) -> None:
        from hledger_textual.config import load_period_views

        app = _PresetsApp(date(2024, 6, 15))
        async with app.run_test() as pilot:
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, PeriodPresetsModal)
            before = load_period_views()
            modal.action_delete_selected()  # cursor starts on first preset row
            await pilot.pause()
            assert load_period_views() == before


class _SaveViewApp(App):
    """Minimal app that pushes SavePeriodViewModal on mount."""

    def __init__(self, expr: str, initial_name: str = "") -> None:
        super().__init__()
        self._expr = expr
        self._initial_name = initial_name

    def compose(self) -> ComposeResult:
        from textual.widgets import Label

        yield Label("base")

    async def on_mount(self) -> None:
        self.push_screen(
            SavePeriodViewModal(
                current_expr=self._expr, initial_name=self._initial_name
            )
        )


class TestSavePeriodViewModal:
    """Save flow persists the expression and dismisses the entered name."""

    async def test_submit_saves_and_dismisses_name(
        self, empty_config: Path
    ) -> None:
        from hledger_textual.config import load_period_views

        app = _SaveViewApp("2024")
        async with app.run_test() as pilot:
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, SavePeriodViewModal)
            dismissed: list = []
            modal.dismiss = dismissed.append  # type: ignore[method-assign]
            await pilot.click("#save-period-view-name-input")
            await pilot.press(*"FY2024")
            await pilot.press("enter")
            await pilot.pause()
            assert load_period_views() == {"FY2024": "2024"}
            assert dismissed == ["FY2024"]

    async def test_blank_name_saves_nothing(
        self, empty_config: Path
    ) -> None:
        from hledger_textual.config import load_period_views

        app = _SaveViewApp("2024")
        async with app.run_test() as pilot:
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, SavePeriodViewModal)
            dismissed: list = []
            modal.dismiss = dismissed.append  # type: ignore[method-assign]
            modal.on_input_submitted(SimpleNamespace(value="   "))
            await pilot.pause()
            assert load_period_views() == {}
            assert dismissed == []

    async def test_initial_name_prefills_input(
        self, empty_config: Path
    ) -> None:
        from textual.widgets import Input

        app = _SaveViewApp("2024", initial_name="FY2024")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, SavePeriodViewModal)
            assert (
                app.screen.query_one("#save-period-view-name-input", Input).value
                == "FY2024"
            )
