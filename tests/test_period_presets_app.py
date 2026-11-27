"""App-level wiring for period presets: bindings, palette, shared state (#277)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hledger_textual.app import HledgerTuiApp


@pytest.fixture
def tmp_journal(tmp_path: Path) -> Path:
    """An (empty) journal path so the app can mount without hledger data."""
    journal = tmp_path / "empty.journal"
    journal.write_text("")
    return journal


@pytest.fixture
def empty_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at an empty temp path."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    return config_file


def _bindings(app: HledgerTuiApp) -> dict[str, str]:
    """Map binding key to action name for the app's BINDINGS."""
    return {b.key: b.action for b in app.BINDINGS}


class TestPresetBindings:
    """p/P are registered and discoverable (footer + command palette)."""

    def test_p_opens_presets(self, tmp_journal: Path) -> None:
        app = HledgerTuiApp(journal_file=tmp_journal)
        assert _bindings(app).get("p") == "period_presets"

    def test_shift_p_saves_view(self, tmp_journal: Path) -> None:
        app = HledgerTuiApp(journal_file=tmp_journal)
        assert _bindings(app).get("P") == "save_period_view"

    async def test_p_opens_presets_modal(
        self, tmp_journal: Path, empty_config: Path
    ) -> None:
        from hledger_textual.screens.period_presets import PeriodPresetsModal

        app = HledgerTuiApp(journal_file=tmp_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
            assert isinstance(app.screen, PeriodPresetsModal)

    async def test_applying_preset_updates_shared_state(
        self, tmp_journal: Path, empty_config: Path
    ) -> None:
        from hledger_textual.period import year_selection

        app = HledgerTuiApp(journal_file=tmp_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_period_presets()
            await pilot.pause()
            modal = app.screen
            modal.on_data_table_row_selected(
                SimpleNamespace(row_key=SimpleNamespace(value="preset:this-year"))
            )
            await pilot.pause()
            expected = year_selection(modal._today.year)
            assert app.period_selection is not None
            assert (app.period_selection.begin, app.period_selection.end) == (
                expected.begin,
                expected.end,
            )

    async def test_shift_p_saves_current_selection(
        self, tmp_journal: Path, empty_config: Path
    ) -> None:
        from hledger_textual.config import load_period_views
        from hledger_textual.period import year_selection
        from hledger_textual.screens.save_period_view import SavePeriodViewModal

        app = HledgerTuiApp(journal_file=tmp_journal)
        app.period_selection = year_selection(2024)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Drive the action directly: deterministic regardless of input focus.
            app.action_save_period_view()
            await pilot.pause()
            assert isinstance(app.screen, SavePeriodViewModal)
            app.screen.on_input_submitted(SimpleNamespace(value="FY2024"))
            await pilot.pause()
            assert load_period_views() == {"FY2024": "2024"}
