"""Global query wiring in every transaction-backed pane (issue #281).

Loader arg threading is covered in test_query_loaders.py; here the pane
side is verified: panes read the app-owned query, pass it to loaders, and
period navigation preserves it.  Real hledger backs the end-to-end paths.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.widgets.pane_mixin import get_global_query
from tests.conftest import has_hledger, wait_until

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


@pytest.fixture
def query_journal(tmp_path: Path) -> Path:
    """Current-month journal: food expense plus salary income."""
    today = date.today()
    d1 = today.replace(day=1).isoformat()
    d2 = today.replace(day=2).isoformat()
    journal = tmp_path / "query.journal"
    journal.write_text(
        f"{d1} * Grocery shopping\n"
        "    expenses:food              €40.80\n"
        "    assets:bank:checking\n"
        "\n"
        f"{d2} Salary\n"
        "    assets:bank:checking     €3000.00\n"
        "    income:salary\n"
    )
    return journal


def _txn_rows(app: HledgerTuiApp) -> int:
    """Row count of the transactions table, -1 while not mounted."""
    try:
        from textual.widgets import DataTable

        return app.screen.query_one("#transactions-table", DataTable).row_count
    except Exception:
        return -1


class TestGlobalQueryHelper:
    """get_global_query mirrors get_period with an empty fallback."""

    def test_fallback_without_app(self) -> None:
        assert get_global_query(object()) == ""

    async def test_reads_app_state(self, query_journal: Path) -> None:
        from hledger_textual.widgets.transactions_table import TransactionsTable

        app = HledgerTuiApp(
            journal_file=query_journal, initial_query="tag:x"
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await wait_until(pilot, lambda: _txn_rows(app) >= 0)
            table = app.screen.query_one(TransactionsTable)
            assert get_global_query(table) == "tag:x"


class TestTransactionsEndToEnd:
    """The global query filters transactions and survives navigation."""

    async def test_global_query_filters_transactions(
        self, query_journal: Path
    ) -> None:
        app = HledgerTuiApp(
            journal_file=query_journal, initial_query="expenses:food"
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await wait_until(pilot, lambda: _txn_rows(app) == 1)

    async def test_period_navigation_keeps_query(
        self, tmp_path: Path
    ) -> None:
        """Moving between two non-empty months keeps filtering by the query."""
        from hledger_textual.dateutil import prev_month

        today = date.today()
        prev = prev_month(today)
        journal = tmp_path / "two_months.journal"
        journal.write_text(
            f"{today.replace(day=1).isoformat()} * Grocery shopping\n"
            "    expenses:food              €40.80\n"
            "    assets:bank:checking\n"
            "\n"
            f"{today.replace(day=2).isoformat()} Salary\n"
            "    assets:bank:checking     €3000.00\n"
            "    income:salary\n"
            "\n"
            f"{prev.replace(day=3).isoformat()} * More groceries\n"
            "    expenses:food              €12.00\n"
            "    assets:bank:checking\n"
        )
        app = HledgerTuiApp(
            journal_file=journal, initial_query="expenses:food"
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            await wait_until(pilot, lambda: _txn_rows(app) == 1)
            await pilot.press("left")  # previous month: still food only
            await wait_until(
                pilot,
                lambda: _txn_rows(app) == 1
                and app.period_selection.begin == prev,
            )
            assert app.active_query == "expenses:food"
            await pilot.press("right")  # back to the current month
            await wait_until(
                pilot,
                lambda: _txn_rows(app) == 1
                and app.period_selection.begin == today.replace(day=1),
            )
            assert app.active_query == "expenses:food"


class TestPaneLoaderWiring:
    """Each pane passes the global query down to its hledger loader."""

    async def _query_seen_by(
        self, monkeypatch: pytest.MonkeyPatch, module_path: str, name: str,
        pane_id: str, trigger: str, journal: Path,
    ) -> dict:
        """Spy on a pane-module loader, drive the pane load, await it."""
        import hledger_textual.hledger as hledger_mod

        real = getattr(hledger_mod, name)
        seen: dict = {}

        def spy(*args, **kwargs):
            seen.update(kwargs)
            return real(*args, **kwargs)

        monkeypatch.setattr(module_path, spy)
        app = HledgerTuiApp(
            journal_file=journal, initial_query="expenses:food"
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.screen.query_one(pane_id)
            worker = getattr(pane, trigger)()
            await worker.wait()
            assert seen.get("query") == "expenses:food"
            return seen

    async def test_summary_receives_query(
        self, query_journal: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await self._query_seen_by(
            monkeypatch,
            "hledger_textual.widgets.summary_pane.load_period_summary",
            "load_period_summary", "#summary", "_load_month_data",
            query_journal,
        )

    async def test_accounts_receives_query(
        self, query_journal: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await self._query_seen_by(
            monkeypatch,
            "hledger_textual.widgets.accounts_pane.load_account_balances",
            "load_account_balances", "#accounts", "_load_data",
            query_journal,
        )

    async def test_budget_receives_query(
        self, query_journal: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await self._query_seen_by(
            monkeypatch,
            "hledger_textual.widgets.budget_pane.load_budget_report",
            "load_budget_report", "#budget", "_load_budget_data",
            query_journal,
        )

    async def test_reports_receives_query(
        self, query_journal: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await self._query_seen_by(
            monkeypatch,
            "hledger_textual.widgets.reports_pane.load_report",
            "load_report", "#reports", "_load_report_data",
            query_journal,
        )
