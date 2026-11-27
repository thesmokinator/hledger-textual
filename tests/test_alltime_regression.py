"""Slow all-time regression on a synthetic 10k journal (issue #280).

Opt-in: ``HLEDGER_TEXTUAL_SLOW_TESTS=1``.  Asserts the all-time view paints
the newest year first and completes with every transaction, proving the
year buckets compose into the full set.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from textual.widgets import DataTable

from hledger_textual.app import HledgerTuiApp
from hledger_textual.period import all_selection
from hledger_textual.widgets.pane_mixin import set_period
from hledger_textual.widgets.transactions_table import TransactionsTable
from scripts.generate_synthetic_journal import generate_journal
from tests.conftest import has_hledger, wait_until

pytestmark = [
    pytest.mark.skipif(not has_hledger(), reason="hledger not installed"),
    pytest.mark.skipif(
        os.environ.get("HLEDGER_TEXTUAL_SLOW_TESTS") != "1",
        reason="slow: set HLEDGER_TEXTUAL_SLOW_TESTS=1",
    ),
]


@pytest.fixture
def empty_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at an empty temp path (default threshold)."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    return config_file


def _rows(app: HledgerTuiApp) -> int:
    """Row count of the transactions table, -1 while not mounted."""
    try:
        return app.screen.query_one("#transactions-table", DataTable).row_count
    except Exception:
        return -1


async def test_all_time_10k_paints_newest_first_then_completes(
    tmp_path: Path, empty_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First paint shows the newest year; the fill ends with all 10k rows."""
    import hledger_textual.widgets.transactions_table as table_mod

    journal = generate_journal(tmp_path / "big.journal", 10_000, seed=42)
    bucket_queries: list[str] = []
    real_load = table_mod.load_transactions

    def spy_load(*args, **kwargs):
        query = kwargs.get("query")
        if query and query.startswith("date:"):
            bucket_queries.append(query)
        return real_load(*args, **kwargs)

    monkeypatch.setattr(table_mod, "load_transactions", spy_load)
    app = HledgerTuiApp(journal_file=journal)
    async with app.run_test(size=(160, 45)) as pilot:
        await pilot.pause(delay=2.0)
        table = app.screen.query_one(TransactionsTable)
        set_period(table, all_selection())
        await pilot.press("3")
        await wait_until(pilot, lambda: _rows(app) > 0, timeout=300.0)
        assert _rows(app) < 10_000
        await wait_until(pilot, lambda: _rows(app) == 10_000, timeout=590.0)
    assert bucket_queries, "expected per-year bucketed queries, got a full print"
    assert all(q.startswith("date:") for q in bucket_queries)
