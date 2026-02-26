"""Integration tests for the Textual app."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_tui.app import HledgerTuiApp
from hledger_tui.hledger import load_transactions
from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


@pytest.fixture
def app_journal(tmp_path: Path) -> Path:
    """A temporary journal with current-month dates for app testing.

    Uses dates within the current month so that the default "thismonth"
    period filter always shows all three transactions.
    """
    today = date.today()
    d1 = today.replace(day=1)
    d2 = today.replace(day=2)
    d3 = today.replace(day=3)

    content = (
        "; Test journal for app integration tests\n"
        "\n"
        f"{d1.isoformat()} * (INV-001) Grocery shopping  ; weekly groceries\n"
        "    expenses:food:groceries              €40.80\n"
        "    assets:bank:checking\n"
        "\n"
        f"{d2.isoformat()} Salary\n"
        "    assets:bank:checking               €3000.00\n"
        "    income:salary\n"
        "\n"
        f"{d3.isoformat()} ! Office supplies  ; for home office\n"
        "    expenses:office                      €25.00\n"
        "    expenses:shipping                    €10.00\n"
        "    assets:bank:checking\n"
    )
    dest = tmp_path / "app_test.journal"
    dest.write_text(content)
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
            table = app.screen.query_one("#transactions-table")
            assert table.row_count == 3

    async def test_journal_bar_shows_file_path(
        self, app: HledgerTuiApp, app_journal: Path
    ):
        async with app.run_test() as pilot:
            await pilot.pause()
            journal_bar = app.screen.query_one("#journal-bar")
            assert str(app_journal) in str(journal_bar.renderable)

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
            from hledger_tui.widgets.transactions_table import TransactionsTable
            txn_table = app.screen.query_one(TransactionsTable)
            filter_bar = txn_table.query_one(".filter-bar")
            assert filter_bar.has_class("visible")

    async def test_filter_narrows_results(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash")
            desc_input = app.screen.query_one("#txn-desc-input")
            desc_input.value = "Grocery"
            await pilot.pause()
            table = app.screen.query_one("#transactions-table")
            assert table.row_count == 1

    async def test_escape_clears_filter(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash")
            desc_input = app.screen.query_one("#txn-desc-input")
            desc_input.value = "Grocery"
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            table = app.screen.query_one("#transactions-table")
            assert table.row_count == 3

    async def test_filter_by_account(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            from hledger_tui.widgets.transactions_table import TransactionsTable
            txn_table = app.screen.query_one(TransactionsTable)
            txn_table._account_filter = "office"
            worker = txn_table._load_transactions()
            await worker.wait()
            await pilot.pause()
            table = app.screen.query_one("#transactions-table")
            assert table.row_count == 1


class TestRefresh:
    """Tests for the refresh functionality."""

    async def test_refresh_reloads(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#transactions-table")
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
            table = app.screen.query_one("#transactions-table")
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


class TestTabNavigation:
    """Tests for the on_key handler that activates a section from the tab bar."""

    async def test_enter_on_tab_bar_activates_section(self, app: HledgerTuiApp):
        """Pressing Enter on the tab bar activates the highlighted section."""
        from textual.widgets import ContentSwitcher, Tabs

        async with app.run_test() as pilot:
            await pilot.pause()
            # Focus the tab bar and move to the Accounts tab
            app.query_one("#nav-tabs", Tabs).focus()
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            # Press Enter to activate — should trigger on_key and switch content
            await pilot.press("enter")
            await pilot.pause()
            switcher = app.screen.query_one("#content-switcher", ContentSwitcher)
            assert switcher.current == "accounts"

    async def test_down_on_tab_bar_activates_section(self, app: HledgerTuiApp):
        """Pressing Down on the tab bar activates the highlighted section."""
        from textual.widgets import ContentSwitcher, Tabs

        async with app.run_test() as pilot:
            await pilot.pause()
            # Focus the tab bar and move to the Accounts tab
            app.query_one("#nav-tabs", Tabs).focus()
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            # Press Down to activate — should trigger on_key and switch content
            await pilot.press("down")
            await pilot.pause()
            switcher = app.screen.query_one("#content-switcher", ContentSwitcher)
            assert switcher.current == "accounts"
