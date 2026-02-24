"""Integration tests for the Textual app."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hledger_tui.app import HledgerTuiApp
from hledger_tui.hledger import load_transactions
from hledger_tui.screens.transactions import TransactionsScreen

from tests.conftest import FIXTURES_DIR, has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


@pytest.fixture
def app_journal(tmp_path: Path) -> Path:
    """A temporary journal for app testing."""
    dest = tmp_path / "app_test.journal"
    shutil.copy2(FIXTURES_DIR / "sample.journal", dest)
    return dest


@pytest.fixture
def app(app_journal: Path) -> HledgerTuiApp:
    """Create an app instance with the test journal."""
    return HledgerTuiApp(journal_file=app_journal)


class TestAppStartup:
    """Tests for application startup."""

    async def test_app_starts_and_shows_transactions(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            table = screen.query_one("#transactions-table")
            assert table.row_count == 3

    async def test_header_shows_file_path(self, app: HledgerTuiApp, app_journal: Path):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            header_file = screen.query_one("#header-file")
            assert str(app_journal) in str(header_file.renderable)

    async def test_quit_key(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("q")


class TestFilter:
    """Tests for the filter functionality."""

    async def test_filter_shows_input(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash")
            screen = app.screen
            filter_bar = screen.query_one("#filter-bar")
            assert filter_bar.has_class("visible")

    async def test_filter_narrows_results(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            await pilot.press("slash")
            filter_input = screen.query_one("#filter-input")
            filter_input.value = "Grocery"
            await pilot.pause()
            table = screen.query_one("#transactions-table")
            assert table.row_count == 1

    async def test_escape_clears_filter(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            await pilot.press("slash")
            filter_input = screen.query_one("#filter-input")
            filter_input.value = "Grocery"
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            table = screen.query_one("#transactions-table")
            assert table.row_count == 3

    async def test_filter_by_account(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            await pilot.press("slash")
            filter_input = screen.query_one("#filter-input")
            filter_input.value = "office"
            await pilot.pause()
            table = screen.query_one("#transactions-table")
            assert table.row_count == 1


class TestRefresh:
    """Tests for the refresh functionality."""

    async def test_refresh_reloads(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            table = screen.query_one("#transactions-table")
            assert table.row_count == 3
            await pilot.press("r")
            await pilot.pause()
            assert table.row_count == 3


class TestDelete:
    """Tests for the delete flow."""

    async def test_delete_shows_modal(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            from hledger_tui.screens.delete_confirm import DeleteConfirmModal
            assert isinstance(app.screen, DeleteConfirmModal)

    async def test_delete_cancel(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            screen = app.screen
            table = screen.query_one("#transactions-table")
            assert table.row_count == 3

    async def test_delete_confirm(self, app: HledgerTuiApp, app_journal: Path):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            delete_btn = app.screen.query_one("#btn-delete")
            await pilot.click(delete_btn)
            await pilot.pause(delay=1.0)
            txns = load_transactions(app_journal)
            assert len(txns) == 2
