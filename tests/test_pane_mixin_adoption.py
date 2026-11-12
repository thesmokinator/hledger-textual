"""Tests for DataTablePaneMixin adoption in transactions and summary panes."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.screens.export_modal import ExportModal
from hledger_textual.widgets.pane_mixin import DataTablePaneMixin
from hledger_textual.widgets.summary_pane import SummaryPane
from hledger_textual.widgets.transactions_pane import TransactionsPane
from tests.conftest import has_hledger, wait_until

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


def test_both_panes_use_data_table_pane_mixin():
    """Transactions and summary panes inherit the shared mixin."""
    assert issubclass(TransactionsPane, DataTablePaneMixin)
    assert issubclass(SummaryPane, DataTablePaneMixin)


def test_mixin_configuration():
    """Each pane declares its primary table and resize behaviour."""
    assert TransactionsPane._main_table_id == "transactions-table"
    assert SummaryPane._main_table_id == "summary-income-table"
    assert SummaryPane._focus_on_show is False
    assert "summary-breakdown-table" in SummaryPane._additional_tables


def test_summary_export_data_from_stored_rows():
    """Summary export reuses the rows collected while applying breakdowns."""
    pane = object.__new__(SummaryPane)
    pane._summary_export_rows = [["Income", "income:salary", "€100.00", "100%"]]
    data = pane.get_export_data()
    assert data.headers == ["Section", "Account", "Amount", "% of total"]
    assert data.rows == [["Income", "income:salary", "€100.00", "100%"]]
    assert data.pane_name == "summary"


@pytest.fixture
def journal(tmp_path: Path) -> Path:
    """A minimal journal with current-month income and expenses."""
    today = date.today()
    d1 = today.replace(day=1)
    d2 = today.replace(day=2)
    content = (
        f"{d1.isoformat()} * Grocery shopping\n"
        "    expenses:food              €40.80\n"
        "    assets:bank:checking\n"
        "\n"
        f"{d2.isoformat()} Salary\n"
        "    assets:bank:checking     €3000.00\n"
        "    income:salary\n"
    )
    path = tmp_path / "test.journal"
    path.write_text(content)
    return path


async def test_transactions_export_uses_mixin_modal(journal: Path):
    """The transactions Export action opens the shared export modal."""
    app = HledgerTuiApp(journal_file=journal)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3")
        await wait_until(pilot, lambda: bool(app.screen.query(TransactionsPane)))
        pane = app.screen.query_one(TransactionsPane)
        await wait_until(pilot, lambda: len(pane.get_export_data().rows) >= 2)
        data = pane.get_export_data()
        assert data.pane_name == "transactions"
        assert data.headers[0] == "Date"

        pane.action_export()
        await pilot.pause(delay=0.5)
        assert isinstance(app.screen, ExportModal)


async def test_summary_export_data_after_load(journal: Path):
    """After loading, the summary pane exposes breakdown rows for export."""
    app = HledgerTuiApp(journal_file=journal)
    async with app.run_test() as pilot:
        await pilot.pause()
        pane = app.screen.query_one(SummaryPane)
        await wait_until(pilot, lambda: len(pane.get_export_data().rows) >= 1)
        data = pane.get_export_data()
        assert data.pane_name == "summary"
        assert {row[0] for row in data.rows} <= {"Income", "Expenses"}


class TestRunExportRoundTrip:
    """_run_export tmp round trip incl. failure branch (issue #247)."""

    async def test_csv_round_trip_writes_rows(
        self, journal: Path, tmp_path: Path
    ):
        """Exported CSV on disk matches the ExportData rows."""
        from hledger_textual.export import ExportData

        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.screen.query_one(TransactionsPane)
            data = ExportData.from_rows(
                "Probe", ["A", "B"], [["1", "2"], ["3", "4"]], "probe"
            )
            pane._run_export(data, "csv", "probe.csv", str(tmp_path))
            target = tmp_path / "probe.csv"
            await wait_until(pilot, lambda: target.exists(), timeout=15.0)
            await pilot.pause(delay=0.5)
            import csv as _csv

            with open(target, encoding="utf-8") as fh:
                assert list(_csv.reader(fh)) == [["A", "B"], ["1", "2"], ["3", "4"]]

    async def test_export_failure_notifies(
        self, journal: Path, tmp_path: Path, monkeypatch
    ):
        """An export backend failure surfaces as an error toast."""
        from hledger_textual.export import ExportData

        def _raise(data, path):
            raise OSError("disk full")

        monkeypatch.setattr("hledger_textual.export.export_csv", _raise)
        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test(notifications=True) as pilot:
            await pilot.pause()
            pane = app.screen.query_one(TransactionsPane)
            data = ExportData.from_rows(
                "Probe", ["A"], [["1"]], "probe"
            )
            pane._run_export(data, "csv", "probe.csv", str(tmp_path))
            await wait_until(
                pilot,
                lambda: any(
                    "Export failed" in str(n.message)
                    for n in app._notifications
                ),
                timeout=15.0,
            )
