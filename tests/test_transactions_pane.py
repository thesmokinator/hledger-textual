"""Integration tests for the Transactions pane."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.screens.move_confirm import MoveConfirmModal
from hledger_textual.screens.transaction_form import TransactionFormScreen
from hledger_textual.widgets.transactions_table import TransactionsTable
from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


@pytest.fixture
def txn_pane_journal(tmp_path: Path) -> Path:
    """A minimal journal with current-month transactions."""
    today = date.today()
    d1 = today.replace(day=1)
    d2 = today.replace(day=2)
    content = (
        f"{d1.isoformat()} * Grocery shopping\n"
        "    expenses:food              €40.80\n"
        "    assets:bank:checking\n"
        "\n"
        f"{d2.isoformat()} Salary\n"
        "    assets:bank:checking     €3000.00\n"
        "    income:salary\n"
    )
    journal = tmp_path / "test.journal"
    journal.write_text(content)
    return journal


@pytest.fixture
def txn_app(txn_pane_journal: Path) -> HledgerTuiApp:
    """Create an app instance for transactions pane testing."""
    return HledgerTuiApp(journal_file=txn_pane_journal)


class TestTodayMonth:
    """Tests for the 't' (today month) keybinding in TransactionsPane."""

    async def test_today_resets_to_current_month(self, txn_app: HledgerTuiApp):
        """Pressing 't' after navigating away returns to the current month."""
        async with txn_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")  # switch to transactions tab
            await pilot.pause(delay=1.0)

            txn_table = txn_app.screen.query_one(TransactionsTable)
            original_month = txn_table.current_month

            # Navigate to previous month
            await pilot.press("left")
            await pilot.pause(delay=1.0)
            assert txn_table.current_month < original_month

            # Press 't' to jump back to today
            await pilot.press("t")
            await pilot.pause(delay=1.0)
            assert txn_table.current_month == date.today().replace(day=1)

    async def test_today_updates_period_label(self, txn_app: HledgerTuiApp):
        """Pressing 't' updates the period label to the current month name."""
        from textual.widgets import Static

        async with txn_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=1.0)

            # Navigate away
            await pilot.press("left")
            await pilot.pause(delay=1.0)

            # Press 't' to jump back
            await pilot.press("t")
            await pilot.pause(delay=1.0)

            label = txn_app.screen.query_one("#txn-period-label", Static)
            expected = date.today().replace(day=1).strftime("%B %Y")
            assert str(label.renderable) == expected


_TODAY = date.today()
_D1 = _TODAY.replace(day=1)
_D2 = _TODAY.replace(day=2)
_D3 = _TODAY.replace(day=3)


@pytest.fixture
def txn3_journal(tmp_path: Path) -> Path:
    """Three current-month transactions for clone/move tests."""
    content = (
        f"{_D1.isoformat()} Salary\n"
        "    assets:bank:checking               €3000.00\n"
        "    income:salary\n"
        "\n"
        f"{_D2.isoformat()} Grocery shopping\n"
        "    expenses:food:groceries              €40.00\n"
        "    assets:bank:checking\n"
        "\n"
        f"{_D3.isoformat()} Office supplies\n"
        "    expenses:office                      €25.00\n"
        "    assets:bank:checking\n"
    )
    path = tmp_path / "test3.journal"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def empty_journal(tmp_path: Path) -> Path:
    path = tmp_path / "empty.journal"
    path.write_text("", encoding="utf-8")
    return path


@pytest.fixture
def app3(txn3_journal: Path) -> HledgerTuiApp:
    return HledgerTuiApp(journal_file=txn3_journal)


@pytest.fixture
def empty_app(empty_journal: Path) -> HledgerTuiApp:
    return HledgerTuiApp(journal_file=empty_journal)


class TestTransactionsPaneRender:
    """Pane mounts its TransactionsTable and shows correct month label."""

    async def test_pane_has_table(self, app3: HledgerTuiApp) -> None:
        async with app3.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            table = app3.query_one(TransactionsTable)
            assert table is not None

    async def test_period_label_is_current_month(self, app3: HledgerTuiApp) -> None:
        async with app3.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            table = app3.query_one(TransactionsTable)
            assert table._period_label() == _TODAY.strftime("%B %Y")


class TestTransactionsPaneMonthNav:
    """Left/right arrows navigate months."""

    async def test_prev_month_decrements(self, app3: HledgerTuiApp) -> None:
        async with app3.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            table = app3.query_one(TransactionsTable)
            initial = table.current_month
            await pilot.press("left")
            await pilot.pause(delay=0.3)
            assert table.current_month < initial

    async def test_next_month_increments(self, app3: HledgerTuiApp) -> None:
        async with app3.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            table = app3.query_one(TransactionsTable)
            initial = table.current_month
            await pilot.press("right")
            await pilot.pause(delay=0.3)
            assert table.current_month > initial


class TestTransactionsPaneClone:
    """'c' clones selected transaction or notifies when nothing selected."""

    async def test_clone_no_selection_stays_on_main(
        self, empty_app: HledgerTuiApp
    ) -> None:
        async with empty_app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("c")
            await pilot.pause(delay=0.5)
            assert not isinstance(empty_app.screen, TransactionFormScreen)

    async def test_clone_with_selection_opens_form(
        self, app3: HledgerTuiApp
    ) -> None:
        async with app3.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("c")
            await pilot.pause(delay=0.5)
            assert isinstance(app3.screen, TransactionFormScreen)


class TestTransactionsPaneMove:
    """'m' opens MoveConfirmModal or notifies when nothing selected."""

    async def test_move_no_selection_stays_on_main(
        self, empty_app: HledgerTuiApp
    ) -> None:
        async with empty_app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("m")
            await pilot.pause(delay=0.5)
            assert not isinstance(empty_app.screen, MoveConfirmModal)

    async def test_move_with_selection_opens_modal(
        self, app3: HledgerTuiApp
    ) -> None:
        async with app3.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("m")
            await pilot.pause(delay=0.5)
            assert isinstance(app3.screen, MoveConfirmModal)

    async def test_move_cancel_dismisses_modal(self, app3: HledgerTuiApp) -> None:
        async with app3.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("m")
            await pilot.pause(delay=0.5)
            assert isinstance(app3.screen, MoveConfirmModal)
            await pilot.press("escape")
            await pilot.pause(delay=0.3)
            assert not isinstance(app3.screen, MoveConfirmModal)


class TestTransactionsPaneFilter:
    """'/' enables the search input; escape disables it."""

    async def test_slash_enables_search_input(self, app3: HledgerTuiApp) -> None:
        from textual.widgets import Input

        async with app3.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            search = app3.query_one("#txn-search-input", Input)
            assert search.disabled
            await pilot.press("/")
            await pilot.pause(delay=0.3)
            assert not search.disabled

    async def test_escape_disables_search_input(self, app3: HledgerTuiApp) -> None:
        from textual.widgets import Input

        async with app3.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("/")
            await pilot.pause(delay=0.3)
            search = app3.query_one("#txn-search-input", Input)
            assert not search.disabled
            await pilot.press("escape")
            await pilot.pause(delay=0.3)
            assert search.disabled
