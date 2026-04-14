"""Pilot tests for the recurring pane (issue #131).

Covers: add form, edit form, generate (no-rules notification path), delete
confirmation, pane render.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.screens.recurring_delete_confirm import RecurringDeleteConfirmModal
from hledger_textual.screens.recurring_form import RecurringFormScreen

from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")

FIXTURES = Path(__file__).parent / "fixtures"
_SAMPLE_RECURRING = FIXTURES / "sample_recurring.journal"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_journal(tmp_path: Path) -> Path:
    """Minimal journal with no recurring rules."""
    path = tmp_path / "test.journal"
    path.write_text("", encoding="utf-8")
    return path


@pytest.fixture
def recurring_journal(tmp_path: Path) -> Path:
    """Journal whose recurring.journal contains two pre-existing rules."""
    main = tmp_path / "test.journal"
    recurring = tmp_path / "recurring.journal"
    shutil.copy2(_SAMPLE_RECURRING, recurring)
    main.write_text("include recurring.journal\n", encoding="utf-8")
    return main


@pytest.fixture
def empty_app(empty_journal: Path) -> HledgerTuiApp:
    return HledgerTuiApp(journal_file=empty_journal)


@pytest.fixture
def rules_app(recurring_journal: Path) -> HledgerTuiApp:
    return HledgerTuiApp(journal_file=recurring_journal)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRecurringPaneRender:
    """Recurring pane renders its DataTable when navigated to."""

    async def test_pane_has_datatable(self, empty_app: HledgerTuiApp) -> None:
        from textual.widgets import DataTable

        async with empty_app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=0.5)
            table = empty_app.query_one("#recurring-table", DataTable)
            assert table is not None


class TestRecurringPaneAdd:
    """'a' opens a RecurringFormScreen for a new rule."""

    async def test_add_opens_form(self, empty_app: HledgerTuiApp) -> None:
        async with empty_app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=0.5)
            await pilot.press("a")
            await pilot.pause(delay=0.5)
            assert isinstance(empty_app.screen, RecurringFormScreen)

    async def test_add_form_is_blank(self, empty_app: HledgerTuiApp) -> None:
        """New-rule form should have an empty description field."""
        from textual.widgets import Input

        async with empty_app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=0.5)
            await pilot.press("a")
            await pilot.pause(delay=0.5)
            form = empty_app.screen
            assert isinstance(form, RecurringFormScreen)
            desc = form.query_one("#recurring-input-description", Input)
            assert desc.value == ""

    async def test_add_form_escape_dismisses(self, empty_app: HledgerTuiApp) -> None:
        async with empty_app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=0.5)
            await pilot.press("a")
            await pilot.pause(delay=0.5)
            assert isinstance(empty_app.screen, RecurringFormScreen)
            await pilot.press("escape")
            await pilot.pause(delay=0.3)
            assert not isinstance(empty_app.screen, RecurringFormScreen)


class TestRecurringPaneGenerate:
    """'g' with no rules stays on main screen (notification shown)."""

    async def test_generate_no_rules_does_not_open_modal(
        self, empty_app: HledgerTuiApp
    ) -> None:
        async with empty_app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=0.5)
            await pilot.press("g")
            await pilot.pause(delay=0.5)
            # No modal screen pushed — still showing the main app screen
            assert not isinstance(empty_app.screen, RecurringFormScreen)


class TestRecurringPaneWithRules:
    """Tests requiring a pre-populated recurring.journal."""

    async def test_datatable_has_rows(self, rules_app: HledgerTuiApp) -> None:
        """Two rules in recurring.journal should produce two table rows."""
        from textual.widgets import DataTable

        async with rules_app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=0.5)
            table = rules_app.query_one("#recurring-table", DataTable)
            assert table.row_count >= 2

    async def test_edit_rule_opens_form(self, rules_app: HledgerTuiApp) -> None:
        """'e' on a loaded rule should open RecurringFormScreen."""
        async with rules_app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=0.5)
            await pilot.press("e")
            await pilot.pause(delay=0.5)
            assert isinstance(rules_app.screen, RecurringFormScreen)

    async def test_delete_rule_opens_confirm(self, rules_app: HledgerTuiApp) -> None:
        """'d' on a loaded rule should push the delete confirmation modal."""
        async with rules_app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=0.5)
            await pilot.press("d")
            await pilot.pause(delay=0.5)
            assert isinstance(rules_app.screen, RecurringDeleteConfirmModal)

    async def test_delete_cancel_stays_on_pane(
        self, rules_app: HledgerTuiApp
    ) -> None:
        """Cancelling delete should dismiss the modal without changes."""
        async with rules_app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(delay=0.5)
            await pilot.press("d")
            await pilot.pause(delay=0.5)
            assert isinstance(rules_app.screen, RecurringDeleteConfirmModal)
            await pilot.press("escape")
            await pilot.pause(delay=0.3)
            assert not isinstance(rules_app.screen, RecurringDeleteConfirmModal)
