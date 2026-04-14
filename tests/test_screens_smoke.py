"""Smoke tests for screens / modals with 0 % code coverage.

Each test pushes the screen directly onto a minimal app and asserts that
key widgets are present, exercising the ``compose`` method and basic
``on_mount`` setup without requiring full navigation flows.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.models import (
    Amount,
    AmountStyle,
    Posting,
    Transaction,
    TransactionStatus,
)
from hledger_textual.screens.about import AboutModal
from hledger_textual.screens.budget_overview import BudgetOverviewScreen
from hledger_textual.screens.export_modal import ExportModal
from hledger_textual.screens.help import HelpScreen
from hledger_textual.screens.move_confirm import MoveConfirmModal
from hledger_textual.screens.recurring_form import RecurringFormScreen

from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_EURO = AmountStyle(
    commodity_side="L",
    commodity_spaced=False,
    decimal_mark=".",
    precision=2,
)

_AMOUNT_50 = Amount(commodity="€", quantity=50, style=_EURO)


def _make_txn(tmp_path: Path) -> Transaction:
    """Build a minimal Transaction for modals that require one."""
    return Transaction(
        index=0,
        date=date.today().isoformat(),
        description="Coffee shop",
        status=TransactionStatus.UNMARKED,
        postings=[
            Posting(account="expenses:food", amounts=[_AMOUNT_50]),
            Posting(account="assets:bank:checking", amounts=[]),
        ],
    )


@pytest.fixture
def journal(tmp_path: Path) -> Path:
    path = tmp_path / "smoke.journal"
    path.write_text("", encoding="utf-8")
    return path


@pytest.fixture
def app(journal: Path) -> HledgerTuiApp:
    return HledgerTuiApp(journal_file=journal)


# ---------------------------------------------------------------------------
# HelpScreen
# ---------------------------------------------------------------------------


class TestHelpScreenSmoke:
    """HelpScreen renders via '?' shortcut and contains expected tabs."""

    async def test_help_opens_via_shortcut(self, app: HledgerTuiApp) -> None:
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause(delay=0.3)
            assert isinstance(app.screen, HelpScreen)

    async def test_help_has_shortcuts_tab(self, app: HledgerTuiApp) -> None:
        from textual.widgets import TabbedContent

        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause(delay=0.3)
            screen = app.screen
            assert isinstance(screen, HelpScreen)
            tabs = screen.query_one("#help-tabs", TabbedContent)
            assert tabs is not None

    async def test_help_dismiss_on_escape(self, app: HledgerTuiApp) -> None:
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause(delay=0.3)
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause(delay=0.3)
            assert not isinstance(app.screen, HelpScreen)


# ---------------------------------------------------------------------------
# AboutModal
# ---------------------------------------------------------------------------


class TestAboutModalSmoke:
    """AboutModal composes and renders its key widgets."""

    async def test_about_renders(self, app: HledgerTuiApp, journal: Path) -> None:
        from textual.widgets import Static

        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await app.push_screen(AboutModal(journal))
            await pilot.pause(delay=0.5)
            screen = app.screen
            assert isinstance(screen, AboutModal)
            # The about modal has at least one Static widget with content
            statics = list(screen.query(Static))
            assert len(statics) > 0

    async def test_about_dismiss_on_escape(
        self, app: HledgerTuiApp, journal: Path
    ) -> None:
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await app.push_screen(AboutModal(journal))
            await pilot.pause(delay=0.3)
            assert isinstance(app.screen, AboutModal)
            await pilot.press("escape")
            await pilot.pause(delay=0.3)
            assert not isinstance(app.screen, AboutModal)


# ---------------------------------------------------------------------------
# ExportModal
# ---------------------------------------------------------------------------


class TestExportModalSmoke:
    """ExportModal composes with format radio buttons and filename input."""

    async def test_export_modal_renders(self, app: HledgerTuiApp) -> None:
        from textual.widgets import Label, RadioSet

        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await app.push_screen(ExportModal())
            await pilot.pause(delay=0.3)
            screen = app.screen
            assert isinstance(screen, ExportModal)
            assert screen.query_one("#export-title", Label) is not None
            assert screen.query_one("#export-format", RadioSet) is not None

    async def test_export_modal_default_csv_selected(
        self, app: HledgerTuiApp
    ) -> None:
        from textual.widgets import RadioButton

        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await app.push_screen(ExportModal())
            await pilot.pause(delay=0.3)
            screen = app.screen
            assert isinstance(screen, ExportModal)
            csv_btn = screen.query_one("#radio-csv", RadioButton)
            assert csv_btn.value is True

    async def test_export_modal_dismiss_on_escape(
        self, app: HledgerTuiApp
    ) -> None:
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await app.push_screen(ExportModal())
            await pilot.pause(delay=0.3)
            assert isinstance(app.screen, ExportModal)
            await pilot.press("escape")
            await pilot.pause(delay=0.3)
            assert not isinstance(app.screen, ExportModal)


# ---------------------------------------------------------------------------
# MoveConfirmModal
# ---------------------------------------------------------------------------


class TestMoveConfirmModalSmoke:
    """MoveConfirmModal shows date navigation and confirm/cancel buttons."""

    async def test_move_modal_renders(
        self, app: HledgerTuiApp, tmp_path: Path
    ) -> None:
        from textual.widgets import Button, Label

        txn = _make_txn(tmp_path)
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await app.push_screen(MoveConfirmModal(txn))
            await pilot.pause(delay=0.3)
            screen = app.screen
            assert isinstance(screen, MoveConfirmModal)
            assert screen.query_one("#move-title", Label) is not None
            assert screen.query_one("#btn-move-confirm", Button) is not None
            assert screen.query_one("#btn-move-cancel", Button) is not None

    async def test_move_modal_cancel_dismisses(
        self, app: HledgerTuiApp, tmp_path: Path
    ) -> None:
        txn = _make_txn(tmp_path)
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await app.push_screen(MoveConfirmModal(txn))
            await pilot.pause(delay=0.3)
            assert isinstance(app.screen, MoveConfirmModal)
            await pilot.click("#btn-move-cancel")
            await pilot.pause(delay=0.3)
            assert not isinstance(app.screen, MoveConfirmModal)


# ---------------------------------------------------------------------------
# RecurringFormScreen
# ---------------------------------------------------------------------------


class TestRecurringFormScreenSmoke:
    """RecurringFormScreen opens for a new rule and has a description field."""

    async def test_recurring_form_new_rule(
        self, app: HledgerTuiApp, journal: Path
    ) -> None:
        from textual.widgets import Button, Input

        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await app.push_screen(RecurringFormScreen(journal))
            await pilot.pause(delay=0.5)
            screen = app.screen
            assert isinstance(screen, RecurringFormScreen)
            assert screen.query_one("#recurring-input-description", Input) is not None
            assert screen.query_one("#btn-save", Button) is not None

    async def test_recurring_form_dismiss_on_escape(
        self, app: HledgerTuiApp, journal: Path
    ) -> None:
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await app.push_screen(RecurringFormScreen(journal))
            await pilot.pause(delay=0.3)
            assert isinstance(app.screen, RecurringFormScreen)
            await pilot.press("escape")
            await pilot.pause(delay=0.3)
            assert not isinstance(app.screen, RecurringFormScreen)


# ---------------------------------------------------------------------------
# BudgetOverviewScreen
# ---------------------------------------------------------------------------


class TestBudgetOverviewScreenSmoke:
    """BudgetOverviewScreen renders a DataTable and period Select."""

    async def test_budget_overview_renders(
        self, app: HledgerTuiApp, journal: Path
    ) -> None:
        from textual.widgets import DataTable, Label, Select

        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await app.push_screen(BudgetOverviewScreen(journal, rules=[]))
            await pilot.pause(delay=0.5)
            screen = app.screen
            assert isinstance(screen, BudgetOverviewScreen)
            assert screen.query_one("#budget-overview-title", Label) is not None
            assert screen.query_one("#budget-overview-table", DataTable) is not None
            assert screen.query_one("#budget-overview-periods", Select) is not None

    async def test_budget_overview_dismiss_on_escape(
        self, app: HledgerTuiApp, journal: Path
    ) -> None:
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await app.push_screen(BudgetOverviewScreen(journal, rules=[]))
            await pilot.pause(delay=0.5)
            assert isinstance(app.screen, BudgetOverviewScreen)
            await pilot.press("escape")
            await pilot.pause(delay=0.3)
            assert not isinstance(app.screen, BudgetOverviewScreen)
