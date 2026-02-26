"""Integration tests for the Accounts pane."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_tui.app import HledgerTuiApp
from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


@pytest.fixture
def accounts_app_journal(tmp_path: Path) -> Path:
    """A temporary journal for accounts pane testing."""
    today = date.today()
    d1 = today.replace(day=1)

    content = (
        f"{d1.isoformat()} * Grocery shopping\n"
        "    expenses:food:groceries              €40.80\n"
        "    assets:bank:checking\n"
        "\n"
        f"{d1.isoformat()} Salary\n"
        "    assets:bank:checking               €3000.00\n"
        "    income:salary\n"
    )
    dest = tmp_path / "test.journal"
    dest.write_text(content)
    return dest


@pytest.fixture
def accounts_app(accounts_app_journal: Path) -> HledgerTuiApp:
    """Create an app instance for accounts testing."""
    return HledgerTuiApp(journal_file=accounts_app_journal)


class TestAccountsPane:
    """Tests for the Accounts pane display."""

    async def test_switch_to_accounts(self, accounts_app: HledgerTuiApp):
        """Pressing 2 switches to the accounts pane."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            from textual.widgets import ContentSwitcher

            switcher = accounts_app.screen.query_one(
                "#content-switcher", ContentSwitcher
            )
            assert switcher.current == "accounts"

    async def test_accounts_table_has_rows(self, accounts_app: HledgerTuiApp):
        """Accounts table shows accounts when data exists."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            table = accounts_app.screen.query_one("#accounts-table")
            assert table.row_count > 0

    async def test_accounts_refresh(self, accounts_app: HledgerTuiApp):
        """Pressing r refreshes the accounts list."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            table = accounts_app.screen.query_one("#accounts-table")
            count_before = table.row_count
            await pilot.press("r")
            await pilot.pause()
            assert table.row_count == count_before


class TestAccountsFilter:
    """Tests for the Accounts pane filter."""

    async def test_filter_shows_input(self, accounts_app: HledgerTuiApp):
        """Pressing / shows the filter input."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            await pilot.press("slash")
            await pilot.pause()
            from hledger_tui.widgets.accounts_pane import AccountsPane

            pane = accounts_app.screen.query_one(AccountsPane)
            filter_bar = pane.query_one(".filter-bar")
            assert filter_bar.has_class("visible")

    async def test_filter_narrows_results(self, accounts_app: HledgerTuiApp):
        """Typing in the filter narrows the account list."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            table = accounts_app.screen.query_one("#accounts-table")
            count_all = table.row_count
            await pilot.press("slash")
            await pilot.pause()
            filter_input = accounts_app.screen.query_one("#acc-filter-input")
            filter_input.value = "income"
            await pilot.pause()
            assert table.row_count < count_all
            assert table.row_count == 1

    async def test_escape_dismisses_filter(self, accounts_app: HledgerTuiApp):
        """Pressing Escape hides the filter and restores all rows."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            table = accounts_app.screen.query_one("#accounts-table")
            count_all = table.row_count
            await pilot.press("slash")
            await pilot.pause()
            filter_input = accounts_app.screen.query_one("#acc-filter-input")
            filter_input.value = "income"
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert table.row_count == count_all


class TestAccountDrillDown:
    """Tests for the account drill-down screen."""

    async def test_enter_opens_account_screen(self, accounts_app: HledgerTuiApp):
        """Pressing Enter on an account opens the drill-down screen."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            from hledger_tui.screens.account_transactions import (
                AccountTransactionsScreen,
            )

            assert isinstance(accounts_app.screen, AccountTransactionsScreen)

    async def test_escape_returns_from_account_screen(
        self, accounts_app: HledgerTuiApp
    ):
        """Pressing Escape on the drill-down screen goes back."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            from hledger_tui.screens.account_transactions import (
                AccountTransactionsScreen,
            )

            assert not isinstance(accounts_app.screen, AccountTransactionsScreen)

    async def test_account_screen_shows_transactions(
        self, accounts_app: HledgerTuiApp
    ):
        """Drill-down screen shows transactions for the selected account."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause(delay=1.0)
            table = accounts_app.screen.query_one("#transactions-table")
            assert table.row_count > 0
