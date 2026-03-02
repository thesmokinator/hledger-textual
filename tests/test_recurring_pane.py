"""Integration tests for the Recurring pane."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.recurring import parse_recurring_rules
from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


@pytest.fixture
def recurring_app_journal(tmp_path: Path) -> Path:
    """A temporary journal with recurring rules for pane testing."""
    today = date.today()
    d1 = today.replace(day=1)

    content = (
        "include recurring.journal\n"
        "\n"
        f"{d1.isoformat()} * Opening balance\n"
        "    Assets:Bank:Checking                 €10000.00\n"
        "    Equity:Opening\n"
    )
    journal = tmp_path / "test.journal"
    journal.write_text(content)

    recurring_content = (
        "~ monthly  Rent payment  ; recurring-id:rent-001, last-generated:2025-01-01\n"
        "    Expenses:Rent                                   €800.00\n"
        "    Assets:Bank:Checking\n"
        "\n"
        "~ weekly  Grocery run  ; recurring-id:grocery-001, last-generated:2025-01-01\n"
        "    Expenses:Groceries                              €100.00\n"
        "    Assets:Bank:Checking\n"
    )
    recurring = tmp_path / "recurring.journal"
    recurring.write_text(recurring_content)

    return journal


@pytest.fixture
def recurring_app(recurring_app_journal: Path) -> HledgerTuiApp:
    """Create an app instance for recurring testing."""
    return HledgerTuiApp(journal_file=recurring_app_journal)


@pytest.fixture
def empty_recurring_app(tmp_path: Path) -> HledgerTuiApp:
    """Create an app with no recurring rules."""
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


class TestRecurringTabSwitch:
    """Tests for switching to the recurring tab."""

    async def test_switch_to_recurring_via_key(self, recurring_app: HledgerTuiApp):
        """Pressing 3 switches to the recurring pane."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            from textual.widgets import ContentSwitcher
            switcher = recurring_app.screen.query_one("#content-switcher", ContentSwitcher)
            assert switcher.current == "recurring"

    async def test_recurring_table_has_rows(self, recurring_app: HledgerTuiApp):
        """Recurring table shows rules when data exists."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            table = recurring_app.screen.query_one("#recurring-table")
            assert table.row_count == 2


class TestRecurringEmptyState:
    """Tests for the empty recurring state."""

    async def test_empty_state_message(self, empty_recurring_app: HledgerTuiApp):
        """Shows empty state message when no recurring rules exist."""
        async with empty_recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            table = empty_recurring_app.screen.query_one("#recurring-table")
            assert table.row_count == 1


class TestRecurringAdd:
    """Tests for adding a recurring rule."""

    async def test_add_shows_form(self, recurring_app: HledgerTuiApp):
        """Pressing 'a' on recurring pane opens the form."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("a")
            await pilot.pause()
            from hledger_textual.screens.recurring_form import RecurringFormScreen
            assert isinstance(recurring_app.screen, RecurringFormScreen)

    async def test_add_cancel(self, recurring_app: HledgerTuiApp):
        """Cancelling the add form does not add a rule."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            table = recurring_app.screen.query_one("#recurring-table")
            assert table.row_count == 2


class TestRecurringDelete:
    """Tests for deleting a recurring rule."""

    async def test_delete_shows_confirm(self, recurring_app: HledgerTuiApp):
        """Pressing 'd' shows delete confirmation."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("d")
            await pilot.pause()
            from hledger_textual.screens.recurring_delete_confirm import RecurringDeleteConfirmModal
            assert isinstance(recurring_app.screen, RecurringDeleteConfirmModal)

    async def test_delete_cancel(self, recurring_app: HledgerTuiApp):
        """Cancelling delete does not remove the rule."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("d")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            table = recurring_app.screen.query_one("#recurring-table")
            assert table.row_count == 2

    async def test_delete_confirm(
        self, recurring_app: HledgerTuiApp, recurring_app_journal: Path
    ):
        """Confirming delete removes the rule."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("d")
            await pilot.pause()
            delete_btn = recurring_app.screen.query_one("#btn-recurring-delete")
            await pilot.click(delete_btn)
            await pilot.pause(delay=1.0)
            recurring_path = recurring_app_journal.parent / "recurring.journal"
            rules = parse_recurring_rules(recurring_path)
            assert len(rules) == 1


class TestRecurringFilter:
    """Tests for recurring filter functionality."""

    async def test_filter_shows_input(self, recurring_app: HledgerTuiApp):
        """Pressing '/' shows the filter input."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("slash")
            await pilot.pause()
            from hledger_textual.widgets.recurring_pane import RecurringPane
            pane = recurring_app.screen.query_one(RecurringPane)
            filter_bar = pane.query_one(".filter-bar")
            assert filter_bar.has_class("visible")

    async def test_escape_dismisses_filter(self, recurring_app: HledgerTuiApp):
        """Pressing Escape hides the filter."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("slash")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            from hledger_textual.widgets.recurring_pane import RecurringPane
            pane = recurring_app.screen.query_one(RecurringPane)
            filter_bar = pane.query_one(".filter-bar")
            assert not filter_bar.has_class("visible")

    async def test_filter_narrows_results(self, recurring_app: HledgerTuiApp):
        """Typing in the filter shows only matching rules."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("slash")
            await pilot.pause()
            filter_input = recurring_app.screen.query_one("#recurring-filter-input")
            filter_input.value = "Rent"
            await pilot.pause()
            table = recurring_app.screen.query_one("#recurring-table")
            assert table.row_count == 1


class TestRecurringEdit:
    """Tests for the edit action in RecurringPane."""

    async def test_edit_opens_form_in_edit_mode(self, recurring_app: HledgerTuiApp):
        """Pressing 'e' with a rule selected opens RecurringFormScreen in edit mode."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("e")
            await pilot.pause()
            from hledger_textual.screens.recurring_form import RecurringFormScreen
            assert isinstance(recurring_app.screen, RecurringFormScreen)
            assert recurring_app.screen.is_edit is True

    async def test_edit_cancel_leaves_rules_unchanged(
        self, recurring_app: HledgerTuiApp, recurring_app_journal: Path
    ):
        """Cancelling the edit form does not modify any rule."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("e")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            recurring_path = recurring_app_journal.parent / "recurring.journal"
            rules = parse_recurring_rules(recurring_path)
            assert len(rules) == 2


class TestRecurringGenerate:
    """Tests for the generate action."""

    async def test_generate_shows_dialog(self, recurring_app: HledgerTuiApp):
        """Pressing 'g' with pending rules shows the generate dialog."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("g")
            await pilot.pause(delay=1.0)
            from hledger_textual.screens.recurring_generate import RecurringGenerateScreen
            assert isinstance(recurring_app.screen, RecurringGenerateScreen)


class TestRecurringFooter:
    """Tests for the recurring footer text."""

    async def test_footer_updates_on_switch(self, recurring_app: HledgerTuiApp):
        """Footer shows recurring-specific text when switching to recurring tab."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            from textual.widgets import Static
            footer = recurring_app.screen.query_one("#footer-bar", Static)
            rendered = str(footer.renderable)
            assert "Generate" in rendered
            assert "Add" in rendered


class TestRecurringCursor:
    """Tests for cursor movement bindings in RecurringPane."""

    async def test_cursor_down(self, recurring_app: HledgerTuiApp):
        """Pressing 'j' moves the cursor down without crashing."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("j")
            await pilot.pause()
            table = recurring_app.screen.query_one("#recurring-table")
            assert table.row_count == 2

    async def test_cursor_up(self, recurring_app: HledgerTuiApp):
        """Pressing 'k' moves the cursor up without crashing."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("k")
            await pilot.pause()
            table = recurring_app.screen.query_one("#recurring-table")
            assert table.row_count == 2


class TestRecurringNoSelection:
    """Tests for edit/delete actions when no valid rule is selected."""

    async def test_edit_no_rule_stays_on_main_screen(
        self, empty_recurring_app: HledgerTuiApp
    ):
        """Pressing 'e' with no rule selected does not push a form screen."""
        async with empty_recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("e")
            await pilot.pause()
            from hledger_textual.screens.recurring_form import RecurringFormScreen
            assert not isinstance(empty_recurring_app.screen, RecurringFormScreen)

    async def test_delete_no_rule_stays_on_main_screen(
        self, empty_recurring_app: HledgerTuiApp
    ):
        """Pressing 'd' with no rule selected does not push a confirm screen."""
        async with empty_recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            await pilot.press("d")
            await pilot.pause()
            from hledger_textual.screens.recurring_delete_confirm import RecurringDeleteConfirmModal
            assert not isinstance(empty_recurring_app.screen, RecurringDeleteConfirmModal)


class TestRecurringRefresh:
    """Tests for the refresh action in RecurringPane."""

    async def test_refresh_keeps_row_count(self, recurring_app: HledgerTuiApp):
        """Pressing 'r' reloads the data without changing the row count."""
        async with recurring_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=1.0)
            count_before = recurring_app.screen.query_one("#recurring-table").row_count
            await pilot.press("r")
            await pilot.pause(delay=1.0)
            assert recurring_app.screen.query_one("#recurring-table").row_count == count_before
