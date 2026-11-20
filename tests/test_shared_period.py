"""Tests for the app-owned shared period selection (issue #263)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.period import (
    current_month_selection,
    month_selection,
    shift_months,
)
from tests.conftest import has_hledger, wait_until

MULTI_MONTH_JOURNAL = """\
2024-03-10 * Old groceries
    expenses:food          20.00
    assets:checking

2024-05-01 * Salary
    assets:checking        1000.00
    income:salary
"""


@pytest.fixture
def multi_month_app(tmp_path: Path) -> HledgerTuiApp:
    """App over a journal whose data lies outside the current month."""
    journal = tmp_path / "journal.journal"
    journal.write_text(MULTI_MONTH_JOURNAL)
    return HledgerTuiApp(journal_file=journal)


@pytest.fixture
def fresh_app(tmp_path: Path) -> HledgerTuiApp:
    """App over a journal with current-month data (no startup landing)."""
    journal = tmp_path / "fresh.journal"
    journal.write_text(
        f"{date.today().replace(day=1).isoformat()} * Fresh groceries\n"
        "    expenses:food          20.00\n"
        "    assets:checking\n"
    )
    return HledgerTuiApp(journal_file=journal)


class TestSharedPeriodUnit:
    """Pure-python checks on period plumbing without a running app."""

    def _reports_pane(self, months: int, selection):
        """Build a ReportsPane with a local fallback period."""
        from hledger_textual.widgets.reports_pane import ReportsPane

        pane = ReportsPane.__new__(ReportsPane)
        pane._period_months = months
        pane._period_fallback = selection
        return pane

    def test_reports_window_ends_at_anchor(self):
        """A 6-month window ends at the anchor month, not today."""
        pane = self._reports_pane(6, month_selection(date(2024, 3, 1)))
        assert pane._period_range() == ("2023-10-01", "2024-04-01")

    def test_reports_window_crosses_year_boundary(self):
        """January anchors reach back into the previous year."""
        pane = self._reports_pane(6, month_selection(date(2024, 1, 1)))
        assert pane._period_range() == ("2023-08-01", "2024-02-01")

    def test_reports_ytd_starts_at_january(self):
        """YTD covers January to the anchor month of the selected year."""
        pane = self._reports_pane(0, month_selection(date(2024, 3, 1)))
        assert pane._period_range() == ("2024-01-01", "2024-04-01")


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSharedPeriodIntegration:
    """Panes derive their scope from the app's shared period selection."""

    async def test_app_starts_on_current_month(
        self, fresh_app: HledgerTuiApp
    ):
        """The default selection is the current calendar month."""
        async with fresh_app.run_test() as pilot:
            await pilot.pause()
            assert fresh_app.period_selection == current_month_selection()

    async def test_transactions_follow_the_shared_period(
        self, multi_month_app: HledgerTuiApp
    ):
        """Setting an old month loads that month in the Transactions pane."""
        from hledger_textual.widgets.transactions_table import TransactionsTable

        async with multi_month_app.run_test() as pilot:
            await pilot.pause()
            multi_month_app._activate_section("transactions")
            await pilot.pause(delay=0.5)
            multi_month_app.period_selection = month_selection(date(2024, 3, 1))
            table = multi_month_app.query_one(TransactionsTable)
            await wait_until(
                pilot, lambda: table._period.begin == date(2024, 3, 1)
            )
            await wait_until(pilot, lambda: len(table._all_transactions) == 1)

    async def test_summary_follows_the_shared_period(
        self, multi_month_app: HledgerTuiApp
    ):
        """The Summary breakdown period matches the shared selection."""
        from hledger_textual.widgets.summary_pane import SummaryPane

        async with multi_month_app.run_test() as pilot:
            await pilot.pause()
            multi_month_app.period_selection = month_selection(date(2024, 5, 1))
            summary = multi_month_app.query_one(SummaryPane)
            await wait_until(pilot, lambda: summary._period_str() == "2024-05")

    async def test_reports_follow_the_shared_period(
        self, multi_month_app: HledgerTuiApp
    ):
        """The Reports window ends at the shared anchor month."""
        from hledger_textual.widgets.reports_pane import ReportsPane

        async with multi_month_app.run_test() as pilot:
            await pilot.pause()
            multi_month_app._activate_section("reports")
            await pilot.pause(delay=0.5)
            multi_month_app.period_selection = month_selection(date(2024, 3, 1))
            reports = multi_month_app.query_one(ReportsPane)
            await wait_until(
                pilot,
                lambda: reports._period_begin == date(2023, 10, 1),
            )

    async def test_hidden_panes_marked_stale_on_period_change(
        self, multi_month_app: HledgerTuiApp
    ):
        """Changing the period while Transactions is visible marks Budget stale."""
        async with multi_month_app.run_test() as pilot:
            await pilot.pause()
            multi_month_app._activate_section("transactions")
            await pilot.pause()
            multi_month_app._stale_panes.clear()
            multi_month_app.period_selection = month_selection(date(2024, 3, 1))
            assert "budget" in multi_month_app._stale_panes
            assert "reports" in multi_month_app._stale_panes

    async def test_stale_panes_refresh_on_activation(
        self, multi_month_app: HledgerTuiApp
    ):
        """A pane marked stale picks up the new period when activated."""
        from hledger_textual.widgets.budget_pane import BudgetPane

        async with multi_month_app.run_test() as pilot:
            await pilot.pause()
            multi_month_app.period_selection = month_selection(date(2024, 3, 1))
            multi_month_app._activate_section("budget")
            await pilot.pause(delay=0.5)
            budget = multi_month_app.query_one(BudgetPane)
            assert budget._current_month == date(2024, 3, 1)

    async def test_budget_navigation_updates_the_app_period(
        self, fresh_app: HledgerTuiApp
    ):
        """Budget month steps move the shared selection, not a private anchor."""
        from hledger_textual.widgets.budget_pane import BudgetPane

        async with fresh_app.run_test() as pilot:
            await pilot.pause()
            fresh_app._activate_section("budget")
            await pilot.pause(delay=0.5)
            await pilot.press("h")
            await pilot.pause(delay=0.5)
            expected = shift_months(current_month_selection(), -1)
            assert fresh_app.period_selection == expected
            budget = fresh_app.query_one(BudgetPane)
            assert budget._current_month == expected.begin

    async def test_transactions_navigation_updates_the_app_period(
        self, fresh_app: HledgerTuiApp
    ):
        """Transactions month steps move the shared selection."""
        from hledger_textual.widgets.transactions_table import TransactionsTable

        async with fresh_app.run_test() as pilot:
            await pilot.pause()
            fresh_app._activate_section("transactions")
            await pilot.pause(delay=0.5)
            await pilot.press("right")
            await pilot.pause(delay=0.5)
            expected = shift_months(current_month_selection(), 1)
            assert fresh_app.period_selection == expected
            table = fresh_app.query_one(TransactionsTable)
            assert table._period == expected
