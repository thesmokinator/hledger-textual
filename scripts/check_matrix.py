#!/usr/bin/env python3
"""Reproduce the hledger UI matrix row for hledger-textual from evidence.

Runs the app headless (Textual ``run_test``) against each journal the
hledger UI test matrix (https://hledger.org/uis.html) uses — the vendored
copies under ``tests/fixtures/matrix/`` — and prints a markdown table
mirroring the upstream columns, so the row in the hledger site can be
regenerated from evidence (issues #275, #276).

Usage::

    uv run python scripts/check_matrix.py
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from hledger_textual.app import HledgerTuiApp  # noqa: E402

MATRIX_DIR = REPO_ROOT / "tests" / "fixtures" / "matrix"

#: Journal file name -> upstream matrix column it represents.
MATRIX_JOURNALS = {
    "sample2.journal": "sample",
    "accounttypes.journal": "accounttypes",
    "bcexample.journal": "bcexample",
    "1ktxns-100accts.journal": "synthetic",
}


def sha256(path: Path) -> str:
    """Return the hex sha256 of *path*."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dir_checksums(directory: Path) -> dict[str, str]:
    """Checksum every file in *directory*."""
    return {p.name: sha256(p) for p in sorted(directory.iterdir()) if p.is_file()}


async def check_journal(journal: Path) -> dict[str, bool | str]:
    """Run the app headless against *journal* and collect matrix checks.

    Args:
        journal: Path to the journal to open (the app's ``otherfiles``
            behaviour: any file can be opened explicitly).

    Returns:
        A dict with booleans ``loads``, ``renders``, ``otheryears`` and a
        string ``misc`` (empty when the launch wrote nothing).
    """
    from hledger_textual.widgets.transactions_table import TransactionsTable

    result: dict[str, bool | str] = {
        "loads": False,
        "renders": False,
        "otheryears": False,
        "misc": "",
    }
    directory = journal.parent
    before = dir_checksums(directory)

    try:
        app = HledgerTuiApp(journal_file=journal)
    except Exception as exc:  # pragma: no cover - defensive
        result["misc"] = f"app init failed: {exc}"
        return result

    try:
        async with app.run_test() as pilot:
            # Wait for stats: the journal must actually load.
            await _wait(pilot, lambda: app.journal_stats is not None, 60)
            stats = app.journal_stats
            if stats is None or stats.transaction_count <= 0:
                result["misc"] = "stats did not load or zero transactions"
                return result
            result["loads"] = True

            # otheryears: when the latest activity predates the current
            # month, the app must land there without manual navigation.
            latest = stats.last_date
            if latest is not None:
                today = date.today()
                if (latest.year, latest.month) < (today.year, today.month):
                    landed = app.period_selection
                    result["otheryears"] = (
                        landed.begin is not None
                        and (landed.begin.year, landed.begin.month)
                        == (latest.year, latest.month)
                    )
                else:
                    result["otheryears"] = True

            # Transactions pane renders rows for the data.
            app._activate_section("transactions")
            await pilot.pause(delay=0.5)
            table = app.query_one(TransactionsTable)
            await _wait(pilot, lambda: len(table._all_transactions) > 0, 60)
            result["renders"] = len(table._all_transactions) > 0

            # misc: launching must not write anything.
            await pilot.pause(delay=0.5)
            if dir_checksums(directory) != before:
                result["misc"] = "launch modified the journal directory"
    except Exception as exc:
        result["misc"] = f"error: {exc}"
    return result


async def _wait(pilot, condition, timeout: float) -> None:
    """Poll *condition* via pilot pauses until true or timeout (seconds)."""
    waited = 0.0
    interval = 0.05
    while waited < timeout:
        if condition():
            return
        await pilot.pause(delay=interval)
        waited += interval
    raise TimeoutError("condition not met")


async def run_checks() -> dict[str, dict[str, bool | str]]:
    """Run the app against every matrix journal."""
    results: dict[str, dict[str, bool | str]] = {}
    for name in MATRIX_JOURNALS:
        journal = MATRIX_DIR / name
        print(f"Checking {name} …", file=sys.stderr)
        results[name] = await check_journal(journal)
    return results


def _yes(value: bool | str) -> str:
    """Format a boolean as the matrix's Y/N marker."""
    return "Y" if value is True else "N"


def build_row(results: dict[str, dict[str, bool | str]]) -> str:
    """Build the upstream-style table row for hledger-textual."""
    install = "Y" if all(r["loads"] for r in results.values()) else "N"
    otherfiles = "Y" if all(r["loads"] for r in results.values()) else "N"
    otheryears = "Y" if all(r["otheryears"] for r in results.values()) else "N"
    per_journal = {
        column: "Y"
        for column in MATRIX_JOURNALS.values()
    }
    for name, result in results.items():
        column = MATRIX_JOURNALS[name]
        per_journal[column] = (
            "Y" if result["loads"] and result["renders"] else "N"
        )
    misc_notes = [f"{name}: {result['misc']}" for name, result in results.items() if result["misc"]]
    misc = "; ".join(misc_notes)
    return (
        f"| [hledger-textual] | python | {install} | {otherfiles} | {otheryears} "
        f"| {per_journal['sample']} | {per_journal['accounttypes']} "
        f"| {per_journal['bcexample']} | {per_journal['synthetic']} | {misc} |"
    )


def main() -> int:
    """Run the checks and print the evidence table."""
    results = asyncio.run(run_checks())
    print("## Evidence (regenerated from the vendored matrix fixtures)\n")
    print("| journal | loads | renders | otheryears | misc issues |")
    print("|---------|-------|---------|------------|-------------|")
    for name, result in results.items():
        print(
            f"| {name} | {_yes(result['loads'])} | {_yes(result['renders'])} "
            f"| {_yes(result['otheryears'])} | {result['misc'] or '—'} |"
        )
    print("\n## Upstream row for hledger.org/uis.md\n")
    print(build_row(results))
    ok = all(r["loads"] and r["renders"] and r["otheryears"] and not r["misc"] for r in results.values())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
