"""All-time threshold warning with single-year offer (issue #280)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.period import all_selection, year_selection
from hledger_textual.widgets.pane_mixin import set_period
from hledger_textual.widgets.transactions_table import TransactionsTable
from tests.conftest import has_hledger, wait_until

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


@pytest.fixture
def tiny_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at a temp path with threshold = 1."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("all_time_threshold = 1\n", encoding="utf-8")
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    return config_file


@pytest.fixture
def empty_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at an empty temp path."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    return config_file


@pytest.fixture
def two_year_journal(tmp_path: Path) -> Path:
    """Two transactions in different years."""
    journal = tmp_path / "two.journal"
    journal.write_text(
        "2022-05-01 Old\n"
        "    expenses:food  €10.00\n"
        "    assets:cash\n"
        "\n"
        "2024-07-01 New\n"
        "    expenses:food  €20.00\n"
        "    assets:cash\n"
    )
    return journal


def _rows(app: HledgerTuiApp) -> int:
    """Row count of the transactions table, -1 while not mounted."""
    try:
        from textual.widgets import DataTable

        return app.screen.query_one("#transactions-table", DataTable).row_count
    except Exception:
        return -1


class TestAllTimeThresholdConfig:
    """load_all_time_threshold reads a positive int, default 20000."""

    def test_default(self, empty_config: Path) -> None:
        from hledger_textual.config import load_all_time_threshold

        assert load_all_time_threshold() == 20000

    def test_custom(self, tiny_config: Path) -> None:
        from hledger_textual.config import load_all_time_threshold

        assert load_all_time_threshold() == 1

    def test_invalid_falls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from hledger_textual.config import load_all_time_threshold

        for bad in ["0", "-5", '"many"', "true"]:
            config_file = tmp_path / "config.toml"
            config_file.write_text(f"all_time_threshold = {bad}\n", encoding="utf-8")
            monkeypatch.setattr(
                "hledger_textual.config._CONFIG_PATH", config_file
            )
            assert load_all_time_threshold() == 20000, bad


class TestAllTimeWarning:
    """Over-threshold all-time loads show the modal instead of loading."""

    async def test_modal_appears_instead_of_loading(
        self, two_year_journal: Path, tiny_config: Path
    ) -> None:
        from hledger_textual.screens.all_time_confirm import AllTimeModal

        app = HledgerTuiApp(journal_file=two_year_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(TransactionsTable)
            set_period(table, all_selection())
            await pilot.press("3")
            await wait_until(
                pilot,
                lambda: isinstance(app.screen, AllTimeModal),
                timeout=60.0,
            )
            assert _rows(app) == -1 or _rows(app) == 0

    async def test_choosing_year_scopes_to_it(
        self, two_year_journal: Path, tiny_config: Path
    ) -> None:
        from types import SimpleNamespace

        from hledger_textual.screens.all_time_confirm import AllTimeModal

        app = HledgerTuiApp(journal_file=two_year_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(TransactionsTable)
            set_period(table, all_selection())
            await pilot.press("3")
            await wait_until(
                pilot, lambda: isinstance(app.screen, AllTimeModal), timeout=60.0
            )
            modal = app.screen
            assert isinstance(modal, AllTimeModal)
            modal.on_data_table_row_selected(
                SimpleNamespace(row_key=SimpleNamespace(value="view:2024"))
            )
            # The landing month already shows 1 row: wait for the period
            # switch itself, then for the year load.
            await wait_until(
                pilot,
                lambda: app.period_selection == year_selection(2024),
                timeout=60.0,
            )
            await wait_until(pilot, lambda: _rows(app) == 1, timeout=60.0)

    async def test_load_all_anyway_proceeds_without_reasking(
        self, two_year_journal: Path, tiny_config: Path
    ) -> None:
        from types import SimpleNamespace

        from hledger_textual.screens.all_time_confirm import AllTimeModal

        app = HledgerTuiApp(journal_file=two_year_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(TransactionsTable)
            set_period(table, all_selection())
            await pilot.press("3")
            await wait_until(
                pilot, lambda: isinstance(app.screen, AllTimeModal), timeout=60.0
            )
            app.screen.on_data_table_row_selected(
                SimpleNamespace(row_key=SimpleNamespace(value="__all__"))
            )
            await wait_until(pilot, lambda: _rows(app) == 2, timeout=60.0)
            # Leaving and re-entering all-time does not re-ask (same count).
            await pilot.press("1")
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=2.0)
            assert not isinstance(app.screen, AllTimeModal)
            assert _rows(app) == 2

    async def test_under_threshold_loads_directly(
        self, two_year_journal: Path, empty_config: Path
    ) -> None:
        from hledger_textual.screens.all_time_confirm import AllTimeModal

        app = HledgerTuiApp(journal_file=two_year_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(TransactionsTable)
            set_period(table, all_selection())
            await pilot.press("3")
            await wait_until(pilot, lambda: _rows(app) == 2, timeout=60.0)
            assert not isinstance(app.screen, AllTimeModal)
