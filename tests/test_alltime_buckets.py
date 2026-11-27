"""Year-bucketed all-time loading in TransactionsTable (issue #280)."""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.models import JournalStats
from hledger_textual.period import all_selection
from hledger_textual.widgets.pane_mixin import set_period
from hledger_textual.widgets.transactions_table import TransactionsTable
from tests.conftest import has_hledger, wait_until

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


def _stats(first: str, last: str, count: int = 10) -> JournalStats:
    """JournalStats spanning two dates with a small count (no threshold trip)."""
    return JournalStats(
        transaction_count=count,
        account_count=2,
        commodities=["€"],
        first_date=date.fromisoformat(first),
        last_date=date.fromisoformat(last),
    )


def _rows(app: HledgerTuiApp) -> int:
    """Row count of the transactions table, -1 while not mounted."""
    try:
        from textual.widgets import DataTable

        return app.screen.query_one("#transactions-table", DataTable).row_count
    except Exception:
        return -1


class TestYearBuckets:
    """All-time loads one bounded query per year, newest first."""

    async def test_per_year_queries_newest_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import re

        import hledger_textual.widgets.transactions_table as table_mod

        journal = tmp_path / "j.journal"
        journal.write_text("")
        seen: list[str | None] = []

        def fake_load(file, query=None, reverse=False, cache=None):
            seen.append(query)
            return []

        monkeypatch.setattr(table_mod, "load_transactions", fake_load)
        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: app.journal_stats is not None)
            # Startup overwrites stats from the real (empty) journal; the
            # multi-year span under test is set after the app settles.
            app.journal_stats = _stats("2022-03-01", "2024-06-01")
            await pilot.pause()
            table = app.screen.query_one(TransactionsTable)
            set_period(table, all_selection())
            worker = table._load_all_time_buckets(table._all_time_generation)
            await worker.wait()
            await pilot.pause()
            buckets = [
                q for q in seen
                if q and re.fullmatch(r"date:\d{4}", q)
            ]
            assert buckets == ["date:2024", "date:2023", "date:2022"]
            # No unbounded full-journal print: the whole JSON is never held.
            assert None not in seen

    async def test_stats_missing_falls_back_to_full_load(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import hledger_textual.widgets.transactions_table as table_mod

        journal = tmp_path / "j.journal"
        journal.write_text("")
        seen: list[str | None] = []

        def fake_load(file, query=None, reverse=False, cache=None):
            seen.append(query)
            return []

        monkeypatch.setattr(table_mod, "load_transactions", fake_load)
        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: app.journal_stats is not None)
            app.journal_stats = None
            await pilot.pause()
            table = app.screen.query_one(TransactionsTable)
            set_period(table, all_selection())
            worker = table._load_all_time_buckets(table._all_time_generation)
            await worker.wait()
            await pilot.pause()
            # Exactly one unbounded load (the fallback); month loads carry dates.
            assert seen.count(None) == 1

    async def test_stale_fill_is_dropped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import hledger_textual.widgets.transactions_table as table_mod

        journal = tmp_path / "j.journal"
        journal.write_text("")
        release = threading.Event()

        def fake_load(file, query=None, reverse=False, cache=None):
            release.wait(timeout=30)
            return []

        monkeypatch.setattr(table_mod, "load_transactions", fake_load)
        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: app.journal_stats is not None)
            app.journal_stats = _stats("2022-03-01", "2024-06-01")
            await pilot.pause()
            table = app.screen.query_one(TransactionsTable)
            set_period(table, all_selection())
            gen = table._all_time_generation
            worker = table._load_all_time_buckets(gen)
            await pilot.pause()
            # A newer load invalidates the in-flight fill.
            table._all_time_generation = gen + 1
            release.set()
            await worker.wait()
            await pilot.pause()
            assert table._all_transactions == []

    async def test_multiyear_journal_renders_all_rows_newest_first(
        self, tmp_path: Path
    ) -> None:
        journal = tmp_path / "multi.journal"
        journal.write_text(
            "2022-05-01 Old\n"
            "    expenses:food  €10.00\n"
            "    assets:cash\n"
            "\n"
            "2024-07-01 New\n"
            "    expenses:food  €20.00\n"
            "    assets:cash\n"
        )
        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("3")
            table = app.screen.query_one(TransactionsTable)
            set_period(table, all_selection())
            table._load_transactions()
            await wait_until(pilot, lambda: _rows(app) == 2, timeout=60.0)
            first = table._all_transactions[0]
            assert first.date == "2024-07-01"
