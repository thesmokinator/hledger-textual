"""Integration tests for the Budget pane."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_tui.app import HledgerTuiApp
from hledger_tui.budget import parse_budget_rules
from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


@pytest.fixture
def budget_app_journal(tmp_path: Path) -> Path:
    """A temporary journal with current-month transactions for budget testing."""
    today = date.today()
    d1 = today.replace(day=1)
    d2 = today.replace(day=2)

    content = (
        "include budget.journal\n"
        "\n"
        f"{d1.isoformat()} * Grocery shopping\n"
        "    Expenses:Groceries                   €40.80\n"
        "    assets:bank:checking\n"
        "\n"
        f"{d2.isoformat()} Restaurant dinner\n"
        "    Expenses:Restaurant                  €55.00\n"
        "    assets:bank:checking\n"
    )
    journal = tmp_path / "test.journal"
    journal.write_text(content)

    budget_content = (
        "~ monthly\n"
        "    Expenses:Groceries                          €800.00\n"
        "    Expenses:Restaurant                         €150.00\n"
        "    Assets:Budget\n"
    )
    budget = tmp_path / "budget.journal"
    budget.write_text(budget_content)

    return journal


@pytest.fixture
def budget_app(budget_app_journal: Path) -> HledgerTuiApp:
    """Create an app instance for budget testing."""
    return HledgerTuiApp(journal_file=budget_app_journal)


@pytest.fixture
def empty_budget_app(tmp_path: Path) -> HledgerTuiApp:
    """Create an app with no budget rules."""
    today = date.today()
    d1 = today.replace(day=1)

    content = (
        f"{d1.isoformat()} Test\n"
        "    Expenses:Groceries                   €10.00\n"
        "    assets:bank:checking\n"
    )
    journal = tmp_path / "test.journal"
    journal.write_text(content)
    return HledgerTuiApp(journal_file=journal)


class TestBudgetTabSwitch:
    """Tests for switching to the budget tab."""

    async def test_switch_to_budget_via_key(self, budget_app: HledgerTuiApp):
        """Pressing 3 switches to the budget pane."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            from textual.widgets import ContentSwitcher
            switcher = budget_app.screen.query_one("#content-switcher", ContentSwitcher)
            assert switcher.current == "budget"

    async def test_budget_table_has_rows(self, budget_app: HledgerTuiApp):
        """Budget table shows budget rules when data exists."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            table = budget_app.screen.query_one("#budget-table")
            # Should have 2 budget rules (Groceries and Restaurant)
            assert table.row_count == 2


class TestBudgetEmptyState:
    """Tests for the empty budget state."""

    async def test_empty_state_message(self, empty_budget_app: HledgerTuiApp):
        """Shows empty state message when no budget rules exist."""
        async with empty_budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            table = empty_budget_app.screen.query_one("#budget-table")
            # Should have 1 row with the empty state message
            assert table.row_count == 1


class TestBudgetAdd:
    """Tests for adding a budget rule."""

    async def test_add_shows_form(self, budget_app: HledgerTuiApp):
        """Pressing 'a' on budget pane opens the form."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("a")
            await pilot.pause()
            from hledger_tui.screens.budget_form import BudgetFormScreen
            assert isinstance(budget_app.screen, BudgetFormScreen)

    async def test_add_cancel(self, budget_app: HledgerTuiApp):
        """Cancelling the add form does not add a rule."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            table = budget_app.screen.query_one("#budget-table")
            assert table.row_count == 2


class TestBudgetDelete:
    """Tests for deleting a budget rule."""

    async def test_delete_shows_confirm(self, budget_app: HledgerTuiApp):
        """Pressing 'd' shows delete confirmation."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("d")
            await pilot.pause()
            from hledger_tui.screens.budget_delete_confirm import BudgetDeleteConfirmModal
            assert isinstance(budget_app.screen, BudgetDeleteConfirmModal)

    async def test_delete_cancel(self, budget_app: HledgerTuiApp):
        """Cancelling delete does not remove the rule."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("d")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            table = budget_app.screen.query_one("#budget-table")
            assert table.row_count == 2

    async def test_delete_confirm(
        self, budget_app: HledgerTuiApp, budget_app_journal: Path
    ):
        """Confirming delete removes the rule."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("d")
            await pilot.pause()
            delete_btn = budget_app.screen.query_one("#btn-budget-delete")
            await pilot.click(delete_btn)
            await pilot.pause(delay=1.0)
            budget_path = budget_app_journal.parent / "budget.journal"
            rules = parse_budget_rules(budget_path)
            assert len(rules) == 1


class TestBudgetFilter:
    """Tests for budget filter functionality."""

    async def test_filter_shows_input(self, budget_app: HledgerTuiApp):
        """Pressing '/' shows the filter input."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("slash")
            await pilot.pause()
            from hledger_tui.widgets.budget_pane import BudgetPane
            pane = budget_app.screen.query_one(BudgetPane)
            filter_bar = pane.query_one(".filter-bar")
            assert filter_bar.has_class("visible")

    async def test_escape_dismisses_filter(self, budget_app: HledgerTuiApp):
        """Pressing Escape hides the filter."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("slash")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            from hledger_tui.widgets.budget_pane import BudgetPane
            pane = budget_app.screen.query_one(BudgetPane)
            filter_bar = pane.query_one(".filter-bar")
            assert not filter_bar.has_class("visible")


class TestBudgetFooter:
    """Tests for the budget footer text."""

    async def test_footer_updates_on_switch(self, budget_app: HledgerTuiApp):
        """Footer shows budget-specific text when switching to budget tab."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            from textual.widgets import Static
            footer = budget_app.screen.query_one("#footer-bar", Static)
            rendered = str(footer.renderable)
            assert "Add" in rendered
            assert "Month" in rendered
