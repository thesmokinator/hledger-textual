"""Integration tests for the Budget pane."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.budget import parse_budget_rules
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
            from hledger_textual.screens.budget_form import BudgetFormScreen
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
            from hledger_textual.screens.budget_delete_confirm import BudgetDeleteConfirmModal
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
            from hledger_textual.widgets.budget_pane import BudgetPane
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
            from hledger_textual.widgets.budget_pane import BudgetPane
            pane = budget_app.screen.query_one(BudgetPane)
            filter_bar = pane.query_one(".filter-bar")
            assert not filter_bar.has_class("visible")

    async def test_filter_narrows_results(self, budget_app: HledgerTuiApp):
        """Typing in the filter shows only matching rules."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("slash")
            await pilot.pause()
            filter_input = budget_app.screen.query_one("#budget-filter-input")
            filter_input.value = "Groceries"
            await pilot.pause()
            table = budget_app.screen.query_one("#budget-table")
            assert table.row_count == 1


class TestBudgetEdit:
    """Tests for the edit action in BudgetPane."""

    async def test_edit_opens_form_in_edit_mode(self, budget_app: HledgerTuiApp):
        """Pressing 'e' with a rule selected opens BudgetFormScreen in edit mode."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("e")
            await pilot.pause()
            from hledger_textual.screens.budget_form import BudgetFormScreen
            assert isinstance(budget_app.screen, BudgetFormScreen)
            assert budget_app.screen.is_edit is True

    async def test_edit_prefills_selected_rule(self, budget_app: HledgerTuiApp):
        """The edit form is pre-filled with the currently selected rule."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("e")
            await pilot.pause()
            from textual.widgets import Input
            form = budget_app.screen
            # The account field should be filled (first rule is pre-selected)
            account_val = form.query_one("#budget-input-account", Input).value
            assert account_val != ""

    async def test_edit_cancel_leaves_rules_unchanged(
        self, budget_app: HledgerTuiApp, budget_app_journal
    ):
        """Cancelling the edit form does not modify any budget rule."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("e")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            budget_path = budget_app_journal.parent / "budget.journal"
            rules = parse_budget_rules(budget_path)
            assert len(rules) == 2


class TestBudgetMonthNavigation:
    """Tests for prev/next month navigation in BudgetPane."""

    async def test_prev_month_moves_back(self, budget_app: HledgerTuiApp):
        """Pressing 'h' decrements the current month."""
        from hledger_textual.widgets.budget_pane import BudgetPane
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            pane = budget_app.screen.query_one(BudgetPane)
            initial = pane._current_month
            await pilot.press("h")
            await pilot.pause()
            assert pane._current_month < initial

    async def test_next_month_moves_forward(self, budget_app: HledgerTuiApp):
        """Pressing 'l' increments the current month."""
        from hledger_textual.widgets.budget_pane import BudgetPane
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            pane = budget_app.screen.query_one(BudgetPane)
            initial = pane._current_month
            await pilot.press("l")
            await pilot.pause()
            assert pane._current_month > initial

    async def test_prev_month_wraps_january_to_december(
        self, budget_app: HledgerTuiApp
    ):
        """Navigating back from January wraps to December of the previous year."""
        from datetime import date
        from hledger_textual.widgets.budget_pane import BudgetPane
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            pane = budget_app.screen.query_one(BudgetPane)
            pane._current_month = date(2026, 1, 1)
            await pilot.press("h")
            await pilot.pause()
            assert pane._current_month.month == 12
            assert pane._current_month.year == 2025

    async def test_next_month_wraps_december_to_january(
        self, budget_app: HledgerTuiApp
    ):
        """Navigating forward from December wraps to January of the next year."""
        from datetime import date
        from hledger_textual.widgets.budget_pane import BudgetPane
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            pane = budget_app.screen.query_one(BudgetPane)
            pane._current_month = date(2025, 12, 1)
            await pilot.press("l")
            await pilot.pause()
            assert pane._current_month.month == 1
            assert pane._current_month.year == 2026


class TestBudgetRefresh:
    """Tests for the refresh action in BudgetPane."""

    async def test_refresh_keeps_row_count(self, budget_app: HledgerTuiApp):
        """Pressing 'r' reloads the data without changing the row count."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            count_before = budget_app.screen.query_one("#budget-table").row_count
            await pilot.press("r")
            await pilot.pause(delay=1.0)
            assert budget_app.screen.query_one("#budget-table").row_count == count_before


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


class TestBudgetCursor:
    """Tests for cursor movement bindings in BudgetPane."""

    async def test_cursor_down(self, budget_app: HledgerTuiApp):
        """Pressing 'j' moves the cursor down without crashing."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("j")
            await pilot.pause()
            table = budget_app.screen.query_one("#budget-table")
            assert table.row_count == 2

    async def test_cursor_up(self, budget_app: HledgerTuiApp):
        """Pressing 'k' moves the cursor up without crashing."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("k")
            await pilot.pause()
            table = budget_app.screen.query_one("#budget-table")
            assert table.row_count == 2


class TestBudgetColorCoding:
    """Tests for color-coded usage display in _update_table."""

    async def test_over_budget_row_renders(self, budget_app: HledgerTuiApp):
        """Over-budget usage (>100%) uses red markup without crashing."""
        from decimal import Decimal
        from hledger_textual.models import BudgetRow
        from hledger_textual.widgets.budget_pane import BudgetPane

        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            pane = budget_app.screen.query_one(BudgetPane)
            # Inject an over-budget row (actual > budget → red path)
            pane._budget_rows = [
                BudgetRow(
                    account="Expenses:Groceries",
                    actual=Decimal("900"),
                    budget=Decimal("800"),
                    commodity="€",
                )
            ]
            pane._update_table()
            await pilot.pause()
            table = pane.query_one("#budget-table")
            assert table.row_count > 0

    async def test_near_budget_row_renders(self, budget_app: HledgerTuiApp):
        """Near-budget usage (75–100%) uses yellow markup without crashing."""
        from decimal import Decimal
        from hledger_textual.models import BudgetRow
        from hledger_textual.widgets.budget_pane import BudgetPane

        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            pane = budget_app.screen.query_one(BudgetPane)
            # Inject a near-budget row (80% usage → yellow path)
            pane._budget_rows = [
                BudgetRow(
                    account="Expenses:Groceries",
                    actual=Decimal("640"),
                    budget=Decimal("800"),
                    commodity="€",
                )
            ]
            pane._update_table()
            await pilot.pause()
            table = pane.query_one("#budget-table")
            assert table.row_count > 0


class TestBudgetNoSelection:
    """Tests for edit/delete actions when no valid rule is selected."""

    async def test_edit_no_rule_stays_on_main_screen(
        self, empty_budget_app: HledgerTuiApp
    ):
        """Pressing 'e' with no rule selected does not push a form screen."""
        async with empty_budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("e")
            await pilot.pause()
            from hledger_textual.screens.budget_form import BudgetFormScreen
            assert not isinstance(empty_budget_app.screen, BudgetFormScreen)

    async def test_delete_no_rule_stays_on_main_screen(
        self, empty_budget_app: HledgerTuiApp
    ):
        """Pressing 'd' with no rule selected does not push a confirm screen."""
        async with empty_budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("d")
            await pilot.pause()
            from hledger_textual.screens.budget_delete_confirm import BudgetDeleteConfirmModal
            assert not isinstance(empty_budget_app.screen, BudgetDeleteConfirmModal)


class TestBudgetAddSave:
    """Tests for the full add flow (form → worker → file)."""

    async def test_add_saves_rule_to_file(
        self, budget_app: HledgerTuiApp, budget_app_journal: Path
    ):
        """Saving the add form appends a new rule to the budget file."""
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("a")
            await pilot.pause()
            from textual.widgets import Input
            form = budget_app.screen
            form.query_one("#budget-input-account", Input).value = "Expenses:Utilities"
            form.query_one("#budget-input-amount", Input).value = "200.00"
            form.query_one("#budget-input-commodity", Input).value = "€"
            # Call _save() directly (pilot.click is unreliable for tall modals)
            form._save()
            await pilot.pause(delay=2.0)
            budget_path = budget_app_journal.parent / "budget.journal"
            rules = parse_budget_rules(budget_path)
            assert len(rules) == 3

    async def test_add_error_does_not_crash(self, budget_app: HledgerTuiApp, monkeypatch):
        """BudgetError during _do_add is caught and notified."""
        from hledger_textual.budget import BudgetError

        def _raise(*args, **kwargs):
            raise BudgetError("add failed")

        monkeypatch.setattr("hledger_textual.widgets.budget_pane.add_budget_rule", _raise)
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("a")
            await pilot.pause()
            from textual.widgets import Input
            form = budget_app.screen
            form.query_one("#budget-input-account", Input).value = "Expenses:Utilities"
            form.query_one("#budget-input-amount", Input).value = "200.00"
            form._save()
            await pilot.pause(delay=1.0)
            # App must not crash; table still accessible
            assert budget_app.screen.query_one("#budget-table") is not None


class TestBudgetEditSave:
    """Tests for the full edit flow (form → worker → file)."""

    async def test_edit_saves_updated_rule(
        self, budget_app: HledgerTuiApp, budget_app_journal: Path
    ):
        """Saving the edit form updates the rule in the budget file."""
        from decimal import Decimal

        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("e")
            await pilot.pause()
            from textual.widgets import Input
            form = budget_app.screen
            form.query_one("#budget-input-amount", Input).value = "900.00"
            form._save()
            await pilot.pause(delay=2.0)
            budget_path = budget_app_journal.parent / "budget.journal"
            rules = parse_budget_rules(budget_path)
            amounts = [r.amount.quantity for r in rules]
            assert Decimal("900.00") in amounts

    async def test_edit_error_does_not_crash(self, budget_app: HledgerTuiApp, monkeypatch):
        """BudgetError during _do_update is caught and notified."""
        from hledger_textual.budget import BudgetError

        def _raise(*args, **kwargs):
            raise BudgetError("update failed")

        monkeypatch.setattr("hledger_textual.widgets.budget_pane.update_budget_rule", _raise)
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("e")
            await pilot.pause()
            from textual.widgets import Input
            form = budget_app.screen
            form.query_one("#budget-input-amount", Input).value = "900.00"
            form._save()
            await pilot.pause(delay=1.0)
            assert budget_app.screen.query_one("#budget-table") is not None


class TestBudgetDeleteError:
    """Tests for BudgetError handling in the delete worker."""

    async def test_delete_error_does_not_crash(
        self, budget_app: HledgerTuiApp, monkeypatch
    ):
        """BudgetError during _do_delete is caught and notified."""
        from hledger_textual.budget import BudgetError

        def _raise(*args, **kwargs):
            raise BudgetError("delete failed")

        monkeypatch.setattr("hledger_textual.widgets.budget_pane.delete_budget_rule", _raise)
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("d")
            await pilot.pause()
            delete_btn = budget_app.screen.query_one("#btn-budget-delete")
            await pilot.click(delete_btn)
            await pilot.pause(delay=1.0)
            assert budget_app.screen.query_one("#budget-table") is not None


class TestBudgetLoadErrors:
    """Tests for error handling inside _load_budget_data worker."""

    async def test_ensure_budget_file_error_handled(
        self, budget_app: HledgerTuiApp, monkeypatch
    ):
        """BudgetError from ensure_budget_file is caught without crashing."""
        from hledger_textual.budget import BudgetError

        def _raise(*args, **kwargs):
            raise BudgetError("no budget file")

        monkeypatch.setattr(
            "hledger_textual.widgets.budget_pane.ensure_budget_file", _raise
        )
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            # App must not crash
            assert budget_app.screen.query_one("#budget-table") is not None

    async def test_load_budget_report_hledger_error_handled(
        self, budget_app: HledgerTuiApp, monkeypatch
    ):
        """HledgerError from load_budget_report is silently handled."""
        from hledger_textual.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("hledger failed")

        monkeypatch.setattr(
            "hledger_textual.widgets.budget_pane.load_budget_report", _raise
        )
        async with budget_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            assert budget_app.screen.query_one("#budget-table") is not None
