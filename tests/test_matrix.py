"""Regression tests against the hledger UI matrix journals (issue #275).

The four journals under ``tests/fixtures/matrix/`` are the exact fixtures
the hledger UI test matrix (https://hledger.org/uis.html) uses.  They are
vendored from the hledger repository (GPL-3.0, see the provenance note in
``tests/fixtures/matrix/README.md``) and must never be modified.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from tests.conftest import has_hledger, wait_until

MATRIX_DIR = Path(__file__).parent / "fixtures" / "matrix"
MATRIX_FILES = [
    "sample2.journal",
    "accounttypes.journal",
    "bcexample.journal",
    "1ktxns-100accts.journal",
]

#: sha256 of the vendored files at the pinned hledger revision.  A mismatch
#: means the fixtures were modified or refreshed without updating provenance.
MATRIX_CHECKSUMS = {
    "1ktxns-100accts.journal": "d6044994af45b34cc89f32466633c0ebcec69b4fcc7d0f46f969ef9ddbe15639",
    "accounttypes.journal": "88b67a607bd9bd89f3860be46b131eb122d001e8febcd1320a302d6bcd51f718",
    "bcexample.journal": "1d3a0b6c8388cae164de073288b71463c01ae874616d6739da560cc75ba71602",
    "sample2.journal": "3c0ce83b106efd3cb5a506688da15b4b34c0b30d5917772d644fa55407036322",
}


def _sha256(path: Path) -> str:
    """Return the hex sha256 of *path*."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestMatrixProvenance:
    """The vendored journals are byte-identical to the pinned upstream files."""

    def test_all_files_present(self):
        for name in MATRIX_FILES:
            assert (MATRIX_DIR / name).exists(), name

    def test_checksums_match_pinned_revision(self):
        for name, checksum in MATRIX_CHECKSUMS.items():
            assert _sha256(MATRIX_DIR / name) == checksum, (
                f"{name} changed; refresh provenance in "
                "tests/fixtures/matrix/README.md"
            )

    def test_provenance_note_exists(self):
        text = (MATRIX_DIR / "README.md").read_text(encoding="utf-8")
        assert "GPL-3.0" in text
        assert "61d999db5004253fdb0db188338122e0b545a9c2" in text

    def test_fixtures_are_not_packaged(self):
        """The published wheel/sdist must not carry the GPL fixtures."""
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8")
        # uv_build packages src/ only; guard against a widening that would
        # accidentally include tests/.
        assert "tests/fixtures" not in text


def _copy_fixture(tmp_path: Path, name: str) -> Path:
    """Copy a matrix fixture into *tmp_path* and return the journal path."""
    dest = tmp_path / name
    shutil.copy2(MATRIX_DIR / name, dest)
    return dest


def _dir_checksums(directory: Path) -> dict[str, str]:
    """Checksum every file in *directory*."""
    return {
        p.name: _sha256(p) for p in sorted(directory.iterdir()) if p.is_file()
    }


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestMatrixJournals:
    """Every matrix journal loads and renders in the app."""

    @pytest.fixture(params=MATRIX_FILES, ids=MATRIX_FILES)
    def matrix_journal(self, request, tmp_path: Path) -> Path:
        """A copy of one matrix fixture to run the app against."""
        return _copy_fixture(tmp_path, request.param)

    async def test_launch_loads_the_journal(self, matrix_journal: Path):
        """The app starts, loads stats and shows a non-empty transaction count."""
        app = HledgerTuiApp(journal_file=matrix_journal)
        async with app.run_test() as pilot:
            await wait_until(
                pilot,
                lambda: app.journal_stats is not None
                and app.journal_stats.transaction_count > 0,
            )

    async def test_launch_does_not_modify_journal_or_directory(
        self, matrix_journal: Path
    ):
        """Launching on a matrix fixture changes nothing on disk."""
        directory = matrix_journal.parent
        before = _dir_checksums(directory)
        app = HledgerTuiApp(journal_file=matrix_journal)
        async with app.run_test() as pilot:
            await wait_until(
                pilot,
                lambda: app.journal_stats is not None
                and app.journal_stats.transaction_count > 0,
            )
            await pilot.pause(delay=0.5)
        assert _dir_checksums(directory) == before

    async def test_transactions_render_data(self, matrix_journal: Path):
        """The Transactions pane shows rows without errors."""
        from hledger_textual.widgets.transactions_table import TransactionsTable

        app = HledgerTuiApp(journal_file=matrix_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            app._activate_section("transactions")
            await pilot.pause(delay=0.5)
            table = app.query_one(TransactionsTable)
            await wait_until(pilot, lambda: len(table._all_transactions) > 0)

    async def test_accounts_render(self, matrix_journal: Path):
        """The Accounts pane renders rows (account types, non-english names)."""
        from hledger_textual.widgets.accounts_pane import AccountsPane

        app = HledgerTuiApp(journal_file=matrix_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            app._activate_section("accounts")
            await pilot.pause(delay=0.5)
            accounts = app.query_one(AccountsPane)
            await wait_until(
                pilot,
                lambda: accounts.query("#accounts-table") is not None
                and _table_rows(app, "#accounts-table") > 0,
            )

    async def test_period_navigation_reaches_the_data(
        self, matrix_journal: Path
    ):
        """Selecting a month inside the span shows that month's data."""
        from hledger_textual.period import month_selection
        from hledger_textual.widgets.transactions_table import TransactionsTable

        app = HledgerTuiApp(journal_file=matrix_journal)
        async with app.run_test() as pilot:
            await wait_until(
                pilot,
                lambda: app.journal_stats is not None
                and app.journal_stats.first_date is not None,
            )
            first = app.journal_stats.first_date
            app._activate_section("transactions")
            await pilot.pause(delay=0.5)
            app.period_selection = month_selection(first)
            await pilot.pause(delay=0.5)
            table = app.query_one(TransactionsTable)
            await wait_until(pilot, lambda: len(table._all_transactions) > 0)

    async def test_landing_reaches_latest_activity(self, matrix_journal: Path):
        """An old journal lands on its latest month with data (otheryears)."""
        app = HledgerTuiApp(journal_file=matrix_journal)
        async with app.run_test() as pilot:
            await wait_until(
                pilot,
                lambda: app.journal_stats is not None
                and app.journal_stats.last_date is not None,
            )
            latest = app.journal_stats.last_date
            if (latest.year, latest.month) < (date.today().year, date.today().month):
                await wait_until(
                    pilot,
                    lambda: app.period_selection.begin is not None
                    and (app.period_selection.begin.year, app.period_selection.begin.month)
                    == (latest.year, latest.month),
                )
            else:
                # Current-month data: the selection stays on the current month.
                assert app.period_selection.begin is not None


def _table_rows(app, table_id: str) -> int:
    """Return the row count of a DataTable, 0 when it cannot be read."""
    try:
        from textual.widgets import DataTable

        return app.query_one(table_id, DataTable).row_count
    except Exception:
        return 0


class TestCheckMatrixScript:
    """The matrix script mirrors the upstream columns (issue #275)."""

    def _result(self, loads=True, renders=True, otheryears=True, misc=""):
        """A fabricated per-journal check result."""
        return {"loads": loads, "renders": renders, "otheryears": otheryears, "misc": misc}

    def test_all_pass_row(self):
        """All checks green produce the target row: otheryears Y, empty misc."""
        from scripts.check_matrix import MATRIX_JOURNALS, build_row

        results = {name: self._result() for name in MATRIX_JOURNALS}
        row = build_row(results)
        assert row == "| [hledger-textual] | python | Y | Y | Y | Y | Y | Y | Y |  |"

    def test_failure_marks_column_and_misc(self):
        """A failing journal flips its column and fills the misc note."""
        from scripts.check_matrix import MATRIX_JOURNALS, build_row

        results = {name: self._result() for name in MATRIX_JOURNALS}
        results["bcexample.journal"] = self._result(
            loads=False, renders=False, otheryears=False, misc="error: boom"
        )
        row = build_row(results)
        assert "| python | N | N | N | Y | Y | N | Y |" in row
        assert "bcexample.journal: error: boom" in row

    def test_main_smoke(self, capsys):
        """main() runs and prints the evidence tables (fixtures required)."""
        from scripts.check_matrix import main

        assert main() in (0, 1)
        output = capsys.readouterr().out
        assert "## Evidence" in output
        assert "## Upstream row" in output
