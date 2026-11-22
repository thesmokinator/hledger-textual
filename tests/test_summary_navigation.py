"""Tests for Summary month/year navigation (issue #265)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from textual.widgets import Static

from hledger_textual.app import HledgerTuiApp
from hledger_textual.period import current_month_selection, month_selection
from hledger_textual.widgets.summary_pane import SummaryPane
from tests.conftest import has_hledger, wait_until


@pytest.fixture
def nav_journal(tmp_path: Path) -> Path:
    """Journal with data in the current month and in March 2024."""
    today = date.today().replace(day=1)
    journal = tmp_path / "nav.journal"
    journal.write_text(
        f"{today.isoformat()} * Fresh groceries\n"
        "    expenses:food              40.00\n"
        "    assets:checking\n"
        "\n"
        "2024-03-10 * Old salary\n"
        "    assets:checking            1000.00\n"
        "    income:salary\n"
    )
    return journal


@pytest.fixture
def nav_app(nav_journal: Path) -> HledgerTuiApp:
    """Main app over the navigation journal (Summary is the default tab)."""
    return HledgerTuiApp(journal_file=nav_journal)


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSummaryMonthNavigation:
    """Arrow keys move the shared anchor; only month sections reload."""

    async def test_right_moves_to_next_month(self, nav_app: HledgerTuiApp):
        """Right arrow steps the shared anchor forward one month."""
        async with nav_app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            await pilot.press("right")
            await pilot.pause(delay=0.5)
            expected = month_selection(date.today().replace(day=1))
            from hledger_textual.period import shift_months

            assert nav_app.period_selection == shift_months(expected, 1)

    async def test_left_moves_to_previous_month(self, nav_app: HledgerTuiApp):
        """Left arrow steps the shared anchor back one month."""
        async with nav_app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            await pilot.press("left")
            await pilot.pause(delay=0.5)
            from hledger_textual.period import shift_months

            expected = shift_months(current_month_selection(), -1)
            assert nav_app.period_selection == expected

    async def test_year_step_across_december_january(self, nav_app: HledgerTuiApp):
        """Shift+arrows step a year and cross the December/January boundary."""
        async with nav_app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            nav_app.period_selection = month_selection(date(2024, 12, 1))
            await pilot.pause(delay=0.5)
            await pilot.press("shift+right")
            await pilot.pause(delay=0.5)
            assert nav_app.period_selection == month_selection(date(2025, 12, 1))
            await pilot.press("shift+left")
            await pilot.pause(delay=0.5)
            assert nav_app.period_selection == month_selection(date(2024, 12, 1))

    async def test_t_returns_to_current_month(self, nav_app: HledgerTuiApp):
        """Pressing t restores the current calendar month."""
        async with nav_app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            nav_app.period_selection = month_selection(date(2024, 3, 1))
            await pilot.pause(delay=0.5)
            await pilot.press("t")
            await pilot.pause(delay=0.5)
            assert nav_app.period_selection == current_month_selection()

    async def test_month_change_reloads_only_month_sections(
        self, nav_app: HledgerTuiApp, monkeypatch
    ):
        """A month step loads cards/breakdown once, never the all-time loaders."""
        from hledger_textual.widgets import summary_pane as sp

        summary_calls: list[str | None] = []
        liabilities_calls: list[int] = []
        portfolio_calls: list[int] = []

        real_summary = sp.load_period_summary

        def _count_summary(file, period=None, **kwargs):
            summary_calls.append(period)
            return real_summary(file, period, **kwargs)

        def _count_liabilities(*args, **kwargs):
            liabilities_calls.append(1)
            return []

        def _count_portfolio(*args, **kwargs):
            portfolio_calls.append(1)
            return [], {}

        monkeypatch.setattr(sp, "load_period_summary", _count_summary)
        monkeypatch.setattr(sp, "load_liabilities_breakdown", _count_liabilities)
        monkeypatch.setattr(sp, "load_investment_portfolio", _count_portfolio)

        async with nav_app.run_test() as pilot:
            await wait_until(pilot, lambda: len(summary_calls) >= 1)
            await pilot.pause(delay=0.5)
            summary_calls.clear()
            liabilities_calls.clear()
            portfolio_calls.clear()

            await pilot.press("right")
            await wait_until(pilot, lambda: len(summary_calls) >= 1)
            await pilot.pause(delay=0.5)

            assert len(summary_calls) == 1
            assert summary_calls[0] is not None  # month-scoped, not all-time
            assert not liabilities_calls
            assert not portfolio_calls

    async def test_empty_month_shows_jump_hint(self, nav_app: HledgerTuiApp):
        """An empty month shows the jump-to-latest hint instead of silent zeros."""
        async with nav_app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            # April 2024 has no transactions in the fixture.
            nav_app.period_selection = month_selection(date(2024, 4, 1))
            pane = nav_app.query_one(SummaryPane)
            await wait_until(
                pilot,
                lambda: pane.query_one("#summary-month-hint", Static).display,
            )
            hint = pane.query_one("#summary-month-hint", Static)
            assert "Jump to latest activity" in str(hint.content)

    async def test_jump_to_latest_action(self, nav_app: HledgerTuiApp):
        """The jump action lands on the month of the latest transaction."""
        async with nav_app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            nav_app.period_selection = month_selection(date(2024, 4, 1))
            await pilot.pause(delay=0.5)
            pane = nav_app.query_one(SummaryPane)
            pane.action_jump_to_latest()
            await pilot.pause(delay=0.5)
            # Latest activity is the current month in this fixture.
            assert nav_app.period_selection == current_month_selection()

    async def test_month_visible_in_section_titles(self, nav_app: HledgerTuiApp):
        """The breakdown titles name the selected month."""
        async with nav_app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            nav_app.period_selection = month_selection(date(2024, 3, 1))
            pane = nav_app.query_one(SummaryPane)
            await wait_until(
                pilot,
                lambda: "March 2024"
                in str(pane.query_one("#summary-income-title", Static).content),
            )
