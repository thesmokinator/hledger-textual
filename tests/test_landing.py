"""Tests for the startup landing heuristic (issue #267)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.period import (
    current_month_selection,
    month_selection,
    year_selection,
)
from tests.conftest import has_hledger, wait_until


def _write_journal(tmp_path: Path, content: str) -> Path:
    """Write a journal fixture and return its path."""
    journal = tmp_path / "journal.journal"
    journal.write_text(content)
    return journal


def _spy_notify(app: HledgerTuiApp) -> list[str]:
    """Record notify() calls synchronously.

    The notification list exposed by ``run_test`` is asynchronous and entries
    expire after their timeout, which makes assertions flaky under load.
    Wrapping ``notify`` records each message the moment it is emitted.
    """
    notices: list[str] = []
    original = app.notify

    def _spy(message, *args, **kwargs):
        notices.append(str(message))
        return original(message, *args, **kwargs)

    app.notify = _spy
    return notices


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestStartupLanding:
    """The app lands on the latest month with data when the current month is empty."""

    async def test_old_journal_lands_on_latest_month(self, tmp_path: Path):
        """A journal whose newest txn is old starts on that month, with a notice."""
        journal = _write_journal(
            tmp_path,
            "2024-03-10 * Old groceries\n"
            "    expenses:food          20.00\n"
            "    assets:checking\n",
        )
        app = HledgerTuiApp(journal_file=journal)
        notices = _spy_notify(app)
        async with app.run_test() as pilot:
            await wait_until(
                pilot,
                lambda: app.period_selection == month_selection(date(2024, 3, 1)),
            )
            assert any("latest activity" in m for m in notices)

    async def test_recent_journal_stays_on_current_month(self, tmp_path: Path):
        """A journal with current-month data keeps the current month, no notice."""
        today = date.today()
        journal = _write_journal(
            tmp_path,
            f"{today.replace(day=1).isoformat()} * Fresh groceries\n"
            "    expenses:food          20.00\n"
            "    assets:checking\n",
        )
        app = HledgerTuiApp(journal_file=journal)
        notices = _spy_notify(app)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: app.journal_stats is not None)
            await pilot.pause(delay=0.3)
            assert app.period_selection == current_month_selection()
            assert not any("latest activity" in m for m in notices)

    async def test_future_only_journal_no_landing(self, tmp_path: Path):
        """A journal with only future transactions stays on the current month."""
        journal = _write_journal(
            tmp_path,
            "2099-01-01 * Future scheduled\n"
            "    expenses:food          20.00\n"
            "    assets:checking\n",
        )
        app = HledgerTuiApp(journal_file=journal)
        notices = _spy_notify(app)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: app.journal_stats is not None)
            await pilot.pause(delay=0.3)
            assert app.period_selection == current_month_selection()
            assert not any("latest activity" in m for m in notices)

    async def test_empty_journal_no_landing(self, tmp_path: Path):
        """An empty journal neither lands nor notifies."""
        journal = _write_journal(tmp_path, "")
        app = HledgerTuiApp(journal_file=journal)
        notices = _spy_notify(app)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: app.journal_stats is not None)
            await pilot.pause(delay=0.3)
            assert app.period_selection == current_month_selection()
            assert app.journal_stats.last_date is None
            assert not any("latest activity" in m for m in notices)

    async def test_landing_runs_only_once(self, tmp_path: Path):
        """After landing, navigating away is not overridden by later stats loads."""
        journal = _write_journal(
            tmp_path,
            "2024-03-10 * Old groceries\n"
            "    expenses:food          20.00\n"
            "    assets:checking\n",
        )
        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test() as pilot:
            await wait_until(
                pilot,
                lambda: app.period_selection == month_selection(date(2024, 3, 1)),
            )
            # User navigates to another month, then refreshes the Summary.
            app.period_selection = month_selection(date(2024, 5, 1))
            await pilot.press("r")
            await pilot.pause(delay=0.5)
            assert app.period_selection == month_selection(date(2024, 5, 1))


class TestExplicitPeriod:
    """A CLI/config period (issue #268) is never overridden by the landing."""

    async def test_explicit_period_not_overridden_by_landing(self, tmp_path: Path):
        """An old journal with -p 2024 stays on 2024, no landing notice."""
        journal = _write_journal(
            tmp_path,
            "2024-03-10 * Old groceries\n"
            "    expenses:food          20.00\n"
            "    assets:checking\n",
        )
        app = HledgerTuiApp(
            journal_file=journal, initial_period=year_selection(2024)
        )
        notices = _spy_notify(app)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: app.journal_stats is not None)
            await pilot.pause(delay=0.3)
            assert app.period_selection == year_selection(2024)
            assert not any("latest activity" in m for m in notices)

    async def test_every_pane_opens_on_the_explicit_year(self, tmp_path: Path):
        """With -p 2024, Transactions, Summary and Reports scope to 2024."""
        from hledger_textual.widgets.reports_pane import ReportsPane
        from hledger_textual.widgets.summary_pane import SummaryPane
        from hledger_textual.widgets.transactions_table import TransactionsTable

        journal = _write_journal(
            tmp_path,
            "2024-03-10 * Old groceries\n"
            "    expenses:food          20.00\n"
            "    assets:checking\n",
        )
        app = HledgerTuiApp(
            journal_file=journal, initial_period=year_selection(2024)
        )
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            table = app.query_one(TransactionsTable)
            assert table._period.query() == "date:2024"
            summary = app.query_one(SummaryPane)
            assert summary._period_str() == "2024"
            reports = app.query_one(ReportsPane)
            assert reports._period_range() == ("2024-01-01", "2025-01-01")

    async def test_transactions_show_the_explicit_year(self, tmp_path: Path):
        """Transactions actually list the 2024 data at startup."""
        from hledger_textual.widgets.transactions_table import TransactionsTable

        journal = _write_journal(
            tmp_path,
            "2024-03-10 * Old groceries\n"
            "    expenses:food          20.00\n"
            "    assets:checking\n",
        )
        app = HledgerTuiApp(
            journal_file=journal, initial_period=year_selection(2024)
        )
        async with app.run_test() as pilot:
            app._activate_section("transactions")
            table = app.query_one(TransactionsTable)
            await wait_until(pilot, lambda: len(table._all_transactions) == 1)
