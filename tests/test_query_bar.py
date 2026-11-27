"""Query bar modal, bindings and footer wiring (issue #281)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.widgets import Static

from hledger_textual.app import HledgerTuiApp
from hledger_textual.screens.query_bar import QueryBarModal
from tests.conftest import has_hledger, wait_until

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


@pytest.fixture
def bar_journal(tmp_path: Path) -> Path:
    """Current-month journal with food and salary postings."""
    today = date.today()
    d1 = today.replace(day=1).isoformat()
    d2 = today.replace(day=2).isoformat()
    journal = tmp_path / "bar.journal"
    journal.write_text(
        f"{d1} * Grocery shopping\n"
        "    expenses:food              €40.80\n"
        "    assets:bank:checking\n"
        "\n"
        f"{d2} Salary\n"
        "    assets:bank:checking     €3000.00\n"
        "    income:salary\n"
    )
    return journal


@pytest.fixture
def empty_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at an empty temp path."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    return config_file


def _txn_rows(app: HledgerTuiApp) -> int:
    """Row count of the transactions table, -1 while not mounted."""
    try:
        from textual.widgets import DataTable

        return app.screen.query_one("#transactions-table", DataTable).row_count
    except Exception:
        return -1


class TestQueryBarBindings:
    """Q opens the bar, X clears with one action, footer shows state."""

    async def test_Q_opens_query_bar(
        self, bar_journal: Path, empty_config: Path
    ) -> None:
        app = HledgerTuiApp(journal_file=bar_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("Q")
            await pilot.pause()
            assert isinstance(app.screen, QueryBarModal)

    async def test_valid_submit_applies_and_filters(
        self, bar_journal: Path, empty_config: Path
    ) -> None:
        app = HledgerTuiApp(journal_file=bar_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await wait_until(pilot, lambda: _txn_rows(app) == 2)
            app.action_query_bar()
            await pilot.pause()
            assert isinstance(app.screen, QueryBarModal)
            app.screen.on_input_submitted(SimpleNamespace(value="expenses:food"))
            await pilot.pause()
            assert app.active_query == "expenses:food"
            await wait_until(pilot, lambda: _txn_rows(app) == 1)

    async def test_invalid_submit_keeps_old_query(
        self, bar_journal: Path, empty_config: Path
    ) -> None:
        app = HledgerTuiApp(
            journal_file=bar_journal, initial_query="expenses:food"
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_query_bar()
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, QueryBarModal)
            modal.on_input_submitted(SimpleNamespace(value="tag:["))
            await pilot.pause()
            assert app.active_query == "expenses:food"
            assert isinstance(app.screen, QueryBarModal)
            assert "Invalid query" in str(
                modal.query_one("#query-bar-error", Static).content
            )

    async def test_X_clears_with_one_action(
        self, bar_journal: Path, empty_config: Path
    ) -> None:
        app = HledgerTuiApp(
            journal_file=bar_journal, initial_query="expenses:food"
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await wait_until(pilot, lambda: _txn_rows(app) == 1)
            app.action_clear_query()
            await pilot.pause()
            assert app.active_query == ""
            await wait_until(pilot, lambda: _txn_rows(app) == 2)

    async def test_footer_shows_active_query(
        self, bar_journal: Path, empty_config: Path
    ) -> None:
        from textual.widgets import Static

        app = HledgerTuiApp(
            journal_file=bar_journal, initial_query="expenses:food"
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            footer = app.screen.query_one("#footer-bar", Static)
            assert "expenses:food" in str(footer.content)


class TestSavedQueryReuse:
    """The bar reuses the existing saved-filter store (no new section)."""

    async def test_browse_saved_fills_input(
        self, bar_journal: Path, empty_config: Path
    ) -> None:
        from textual.widgets import Input

        from hledger_textual.config import load_saved_filters, save_filter

        save_filter("food", "expenses:food")
        assert load_saved_filters() == {"food": "expenses:food"}

        app = HledgerTuiApp(journal_file=bar_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_query_bar()
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, QueryBarModal)
            modal.action_browse_saved()
            await pilot.pause()
            from hledger_textual.screens.saved_filters import SavedFiltersModal

            assert isinstance(app.screen, SavedFiltersModal)
            app.screen.on_data_table_row_selected(
                SimpleNamespace(row_key=SimpleNamespace(value="food"))
            )
            await pilot.pause()
            assert isinstance(app.screen, QueryBarModal)
            assert (
                app.screen.query_one("#query-bar-input", Input).value
                == "expenses:food"
            )

    async def test_save_current_persists_to_filters(
        self, bar_journal: Path, empty_config: Path
    ) -> None:
        from hledger_textual.config import load_saved_filters

        app = HledgerTuiApp(journal_file=bar_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_query_bar()
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, QueryBarModal)
            modal.on_input_submitted(SimpleNamespace(value="expenses:food"))
            await pilot.pause()
            assert app.active_query == "expenses:food"
            app.action_query_bar()
            await pilot.pause()
            app.screen.action_save_current()
            await pilot.pause()
            from hledger_textual.screens.save_filter import SaveFilterModal

            assert isinstance(app.screen, SaveFilterModal)
            app.screen.on_input_submitted(SimpleNamespace(value="food"))
            await pilot.pause()
            assert load_saved_filters() == {"food": "expenses:food"}
