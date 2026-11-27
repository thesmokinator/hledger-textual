#!/usr/bin/env python3
"""Measure hledger-textual performance on a journal.

Records startup, tab switches, cold reloads after a journal change, and the
cold/warm cost of the main hledger loaders.  Results are printed as a table
and can be written as JSON for comparison across commits.

Examples:
    python scripts/benchmark_perf.py --transactions 50000
    python scripts/benchmark_perf.py --journal examples/demo.journal --output perf.json
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
for _entry in (str(REPO_ROOT / "src"), str(SCRIPTS_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from generate_synthetic_journal import generate_journal  # noqa: E402

from hledger_textual.app import HledgerTuiApp  # noqa: E402
from hledger_textual.cache import HledgerCache  # noqa: E402
from hledger_textual.config import resolve_default_commodity  # noqa: E402
from hledger_textual.hledger import (  # noqa: E402
    get_hledger_version,
    load_expense_breakdown,
    load_income_breakdown,
    load_investment_portfolio,
    load_liabilities_breakdown,
    load_period_net_by_commodity,
    load_period_summary,
    load_report,
    load_transactions,
)
from hledger_textual.period import all_selection  # noqa: E402
from hledger_textual.widgets.pane_mixin import set_period  # noqa: E402
from hledger_textual.widgets.transactions_table import TransactionsTable  # noqa: E402
from hledger_textual.widgets.accounts_pane import AccountsPane  # noqa: E402
from hledger_textual.widgets.reports_pane import ReportsPane  # noqa: E402
from hledger_textual.widgets.summary_pane import SummaryPane  # noqa: E402
from hledger_textual.widgets.transactions_pane import TransactionsPane  # noqa: E402

#: Tabs that perform an hledger load on activation when marked stale.
_RELOAD_SECTIONS = ("summary", "accounts", "transactions", "reports")


async def _wait_until(pilot, condition, *, timeout: float = 600.0) -> float:
    """Pump the app until *condition* is true and return the elapsed seconds.

    Args:
        pilot: Textual pilot driving the app.
        condition: Zero-argument predicate.
        timeout: Seconds before giving up.

    Returns:
        Elapsed wall-clock seconds.

    Raises:
        TimeoutError: When the condition is not met in time.
    """
    started = time.perf_counter()
    while not condition():
        if time.perf_counter() - started > timeout:
            raise TimeoutError("benchmark condition not met in time")
        await pilot.pause(0.05)
    return time.perf_counter() - started


def _key_for(app: HledgerTuiApp, section: str) -> str:
    """Return the number key bound to *section*."""
    return str(app._tab_order.index(section) + 1)


async def _activate(app: HledgerTuiApp, pilot, section: str) -> float:
    """Switch to *section* through the UI and return the elapsed seconds."""
    switcher = app.query_one("#content-switcher")
    started = time.perf_counter()
    await pilot.press(_key_for(app, section))
    await _wait_until(pilot, lambda: switcher.current == section)
    return time.perf_counter() - started


async def _measure_app(
    journal: Path, *, repeat: int, measure_reloads: bool = True
) -> tuple[dict[str, float], dict[str, float]]:
    """Measure UI flows.  Returns (startup, switch) timings."""
    startups: list[float] = []
    summaries: list[float] = []
    preloads: list[float] = []
    warm_refreshes: list[float] = []
    switches: dict[str, list[float]] = {section: [] for section in ("summary", "accounts", "transactions", "budget", "recurring", "reports")}
    reloads: dict[str, list[float]] = {section: [] for section in _RELOAD_SECTIONS}

    def _ready(app: HledgerTuiApp, section: str):
        """Return a predicate that is true once *section* has usable data."""
        if section == "summary":
            pane = app.query_one(SummaryPane)
            return lambda: pane._static_loaded and pane._breakdown_loaded
        if section == "accounts":
            pane = app.query_one(AccountsPane)
            return lambda: bool(pane._balances) or bool(pane._tree_roots)
        if section == "transactions":
            pane = app.query_one(TransactionsPane)
            return lambda: bool(pane._table._all_transactions)
        if section == "reports":
            pane = app.query_one(ReportsPane)
            return lambda: pane._report_data is not None
        if section == "budget":
            from hledger_textual.widgets.budget_pane import BudgetPane

            pane = app.query_one(BudgetPane)
            return lambda: pane._budget_path is not None
        from hledger_textual.widgets.recurring_pane import RecurringPane

        pane = app.query_one(RecurringPane)
        return lambda: pane._recurring_path is not None

    for _run in range(repeat):
        app = HledgerTuiApp(journal_file=journal)
        started = time.perf_counter()
        async with app.run_test(size=(160, 45)) as pilot:
            summary = app.query_one(SummaryPane)
            await _wait_until(pilot, lambda: summary._static_loaded)
            startups.append(time.perf_counter() - started)
            await _wait_until(
                pilot,
                lambda: summary._breakdown_loaded and summary._investments_loaded,
            )
            summaries.append(time.perf_counter() - started)

            # Non-visible panes load in the background after the Summary.
            # Wait for that preload before timing warm switches, and record
            # how long the whole startup (including preload) takes.
            await _wait_until(pilot, lambda: app._preload_started)
            for section in ("accounts", "transactions", "reports", "budget", "recurring"):
                await _wait_until(pilot, _ready(app, section))
            preloads.append(time.perf_counter() - started)

            # Warm tab switches: every pane has already loaded.
            for section in ("accounts", "transactions", "budget", "recurring", "reports", "summary"):
                switches[section].append(await _activate(app, pilot, section))

            # Warm refresh: cache is valid, so only the table redraw remains.
            await _activate(app, pilot, "summary")
            summary._static_loaded = False
            summary._breakdown_loaded = False
            started = time.perf_counter()
            summary.action_refresh()
            await _wait_until(
                pilot, lambda: summary._static_loaded and summary._breakdown_loaded
            )
            warm_refreshes.append(time.perf_counter() - started)

            # Cold reloads: emulate a journal mutation (cache invalidated,
            # pane marked stale) and time the switch that reloads it.  Skipped
            # when the disk cache is warm: without a journal mtime change the
            # reload would be served from disk and not measure real work.
            if measure_reloads:
                for section in _RELOAD_SECTIONS:
                    await _activate(
                        app,
                        pilot,
                        "summary" if section != "summary" else "accounts",
                    )
                    app._cache.invalidate_all()
                    if section == "summary":
                        summary._static_loaded = False
                        summary._breakdown_loaded = False
                    elif section == "accounts":
                        app.query_one(AccountsPane)._balances = []
                    elif section == "transactions":
                        app.query_one(TransactionsPane)._table._all_transactions = []
                    else:
                        app.query_one(ReportsPane)._report_data = None
                    app._stale_panes = {section}
                    started = time.perf_counter()
                    await pilot.press(_key_for(app, section))
                    await _wait_until(pilot, _ready(app, section))
                    reloads[section].append(time.perf_counter() - started)

    def _median(values: list[float]) -> float:
        return round(statistics.median(values), 3)

    startup = {
        "startup_cards_s": _median(startups),
        "startup_summary_s": _median(summaries),
        "preload_complete_s": _median(preloads),
        "refresh_summary_warm_s": _median(warm_refreshes),
    }
    switch_stats = {
        f"switch_{name}_ms": round(_median(values) * 1000, 2)
        for name, values in switches.items()
    }
    switch_stats.update(
        {
            f"reload_{name}_s": _median(values)
            for name, values in reloads.items()
            if values
        }
    )
    return startup, switch_stats


async def _measure_all_time(journal: Path) -> dict[str, float]:
    """Time the all-time transactions view: first paint and full fill.

    The threshold modal is bypassed (patched sky-high) so the measurement
    covers the bucketed load itself.  Startup settles first (preload
    complete on the current month), so the clock isolates the all-time
    load instead of startup contention.  Polling is sparse (2 s): tight
    polls force re-renders of a huge table and pollute the measurement.

    Returns:
        Dict with ``alltime_first_paint_s``, ``alltime_full_fill_s`` and
        ``alltime_rows`` (0 when the journal span is unknown).
    """
    from hledger_textual.widgets.transactions_pane import TransactionsPane

    with patch(
        "hledger_textual.widgets.transactions_table.load_all_time_threshold",
        return_value=10**9,
    ):
        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(delay=2.0)
            await _wait_until(pilot, lambda: app.journal_stats is not None)
            await _wait_until(
                pilot,
                lambda: bool(
                    app.query_one(TransactionsPane)
                    ._table._all_transactions
                ),
            )
            await pilot.pause(delay=1.0)
            started = time.perf_counter()
            set_period(app.screen.query_one(TransactionsTable), all_selection())
            await pilot.press("3")
            first_paint: float | None = None
            total = (
                app.journal_stats.transaction_count
                if app.journal_stats is not None
                else 0
            )
            # Phase 1: fast polls until first paint (empty table = cheap).
            while first_paint is None and time.perf_counter() - started < 600:
                await pilot.pause(delay=0.1)
                try:
                    from textual.widgets import DataTable

                    rows = app.screen.query_one(
                        "#transactions-table", DataTable
                    ).row_count
                except Exception:
                    rows = -1
                if rows > 0:
                    first_paint = round(time.perf_counter() - started, 3)
            # Phase 2: sparse polls to full fill (rendering a huge table
            # every 0.1 s would pollute the measurement).
            while True:
                await pilot.pause(delay=2.0)
                elapsed = time.perf_counter() - started
                try:
                    from textual.widgets import DataTable

                    rows = app.screen.query_one(
                        "#transactions-table", DataTable
                    ).row_count
                except Exception:
                    rows = -1
                if (total and rows >= total) or elapsed > 600:
                    break
            return {
                "alltime_first_paint_s": first_paint or -1.0,
                "alltime_full_fill_s": round(time.perf_counter() - started, 3),
                "alltime_rows": rows,
            }


def _time_loaders(journal: Path) -> dict[str, float]:
    """Time the main loaders cold and warm on a single cache."""
    cache = HledgerCache()
    today = date.today()
    month = today.strftime("%Y-%m")
    commodity = resolve_default_commodity(journal)
    begin = (today.replace(day=1) - timedelta(days=150)).isoformat()
    end = (today.replace(day=1) + timedelta(days=31)).isoformat()

    loaders = {
        "summary": lambda: load_period_summary(
            journal, cache=cache, commodity=commodity
        ),
        "net_by_commodity": lambda: load_period_net_by_commodity(journal, cache=cache),
        "liabilities": lambda: load_liabilities_breakdown(
            journal, commodity=commodity, cache=cache
        ),
        "investment_portfolio": lambda: load_investment_portfolio(
            journal, cache=cache
        ),
        "income_breakdown": lambda: load_income_breakdown(
            journal, month, commodity=commodity, cache=cache
        ),
        "expense_breakdown": lambda: load_expense_breakdown(
            journal, month, commodity=commodity, cache=cache
        ),
        "report_6m": lambda: load_report(
            journal,
            "is",
            period_begin=begin,
            period_end=end,
            commodity=commodity,
            cache=cache,
        ),
        "transactions_month": lambda: load_transactions(
            journal, query=f"date:{month}", reverse=True, cache=cache
        ),
    }

    timings: dict[str, float] = {}
    for name, loader in loaders.items():
        started = time.perf_counter()
        loader()
        timings[f"loader_{name}_cold_s"] = round(time.perf_counter() - started, 3)
        started = time.perf_counter()
        loader()
        timings[f"loader_{name}_warm_s"] = round(time.perf_counter() - started, 3)
    return timings


def _environment(journal: Path | None) -> dict[str, object]:
    """Collect metadata that affects timings."""
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "textual": importlib.metadata.version("textual"),
        "hledger": get_hledger_version(),
        "journal": str(journal) if journal else "",
        "journal_size_bytes": journal.stat().st_size if journal else 0,
    }


def _print_table(results: dict[str, object]) -> None:
    """Print measured values in a stable order."""
    for key, value in results.items():
        if isinstance(value, float):
            print(f"{key:42s} {value:10.3f}")
        else:
            print(f"{key:42s} {value}")


async def _async_main(args) -> int:
    """Run the benchmark."""
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "hledger_textual.config._CONFIG_PATH",
                Path(tempfile.gettempdir()) / "hledger-textual-no-config.toml",
            )
        )
        stack.enter_context(
            patch("hledger_textual.app.load_auto_generate_recurring", return_value=False)
        )
        stack.enter_context(
            patch.object(HledgerTuiApp, "_check_for_updates", lambda _self: None)
        )
        stack.enter_context(
            patch(
                "hledger_textual.widgets.summary_pane.load_price_tickers",
                return_value={},
            )
        )
        stack.enter_context(
            patch(
                "hledger_textual.widgets.summary_pane.has_pricehist",
                return_value=False,
            )
        )

        # Never add budget/recurring includes to a journal passed with
        # --journal: the benchmark must stay read-only.
        aux_dir = Path(tempfile.mkdtemp(prefix="hledger-bench-aux-"))
        budget_path = aux_dir / "budget.journal"
        recurring_path = aux_dir / "recurring.journal"
        budget_path.write_text("", encoding="utf-8")
        recurring_path.write_text("", encoding="utf-8")
        stack.enter_context(
            patch(
                "hledger_textual.budget.ensure_budget_file",
                side_effect=lambda _file: budget_path,
            )
        )
        stack.enter_context(
            patch(
                "hledger_textual.recurring.ensure_recurring_file",
                side_effect=lambda _file: recurring_path,
            )
        )

        if args.journal is not None:
            journal = args.journal
        else:
            journal = Path(tempfile.gettempdir()) / f"hledger-textual-bench-{args.transactions}.journal"
            generate_journal(journal, args.transactions, seed=args.seed)
            print(f"generated {args.transactions} transactions at {journal}")

        results = _environment(journal)
        results["transactions"] = args.transactions

        if args.disk_cache:
            cache_dir = Path(tempfile.mkdtemp(prefix="hledger-bench-cache-"))
            os.environ.pop("HLEDGER_TEXTUAL_NO_DISK_CACHE", None)
            os.environ["HLEDGER_TEXTUAL_CACHE_DIR"] = str(cache_dir)
            # First run populates the cache; record its startup cost, then
            # measure a restart served entirely from disk.
            first_startup, _first_switches = await _measure_app(
                journal, repeat=1, measure_reloads=False
            )
            results["first_startup_cards_s"] = first_startup["startup_cards_s"]
            results["first_startup_summary_s"] = first_startup["startup_summary_s"]
            _time_loaders(journal)
            results["disk_cache"] = "warm"
            startup, switches = await _measure_app(
                journal, repeat=args.repeat, measure_reloads=False
            )
            shutil.rmtree(cache_dir, ignore_errors=True)
        else:
            os.environ["HLEDGER_TEXTUAL_NO_DISK_CACHE"] = "1"
            results["disk_cache"] = "cold"
            results.update(_time_loaders(journal))
            startup, switches = await _measure_app(journal, repeat=args.repeat)

        results.update(startup)
        results.update(switches)

        if args.all_time:
            await _measure_all_time(journal)  # warm the disk cache; unrecorded
            results.update(await _measure_all_time(journal))

    _print_table(results)
    if args.output is not None:
        args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the benchmark command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, help="journal to measure")
    parser.add_argument(
        "-n",
        "--transactions",
        type=int,
        default=50_000,
        help="synthetic transactions when --journal is omitted (default: 50000)",
    )
    parser.add_argument("--seed", type=int, default=42, help="synthetic seed")
    parser.add_argument(
        "--disk-cache",
        action="store_true",
        help="measure a restart served by the persistent disk cache",
    )
    parser.add_argument(
        "--repeat", type=int, default=1, help="app measurement repeats (default: 1)"
    )
    parser.add_argument(
        "--all-time",
        action="store_true",
        help="also measure the all-time transactions view (first paint + full fill)",
    )
    parser.add_argument("--output", type=Path, help="write results as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
