"""Tests for the ReportsPane widget."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Select

from hledger_tui.models import ReportData, ReportRow
from hledger_tui.widgets.reports_pane import ReportsPane
from tests.conftest import has_hledger


class _ReportsApp(App):
    """Minimal app wrapping ReportsPane for isolated widget testing."""

    def __init__(self, journal_file: Path) -> None:
        """Initialize with a journal file path."""
        super().__init__()
        self._journal_file = journal_file

    def compose(self) -> ComposeResult:
        """Compose a single ReportsPane."""
        yield ReportsPane(self._journal_file, id="reports")


@pytest.fixture
def reports_journal(tmp_path: Path) -> Path:
    """A minimal journal for ReportsPane testing."""
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
    journal = tmp_path / "test.journal"
    journal.write_text(content)
    return journal


_SAMPLE_IS_CSV = (
    '"Monthly Income Statement 2026-01-01..2026-03-01","",""\n'
    '"Account","Jan","Feb"\n'
    '"Revenues","",""\n'
    '"income:salary","€3000.00","€3000.00"\n'
    '"Expenses","",""\n'
    '"expenses:food","€40.80","€40.80"\n'
    '"Net:","€2959.20","€2959.20"\n'
)

_SAMPLE_BS_CSV = (
    '"Monthly Balance Sheet 2026-01-01..2026-03-01","",""\n'
    '"Account","Jan","Feb"\n'
    '"Assets","",""\n'
    '"assets:bank:checking","€5000.00","€7000.00"\n'
    '"Total:","€5000.00","€7000.00"\n'
)


# ------------------------------------------------------------------
# Integration tests (require hledger for mount, but monkeypatched)
# ------------------------------------------------------------------


class TestReportsPaneMount:
    """Tests for ReportsPane initial render."""

    async def test_pane_mounts_without_error(
        self, reports_journal: Path, monkeypatch
    ):
        """ReportsPane mounts without raising exceptions."""
        monkeypatch.setattr(
            "hledger_tui.widgets.reports_pane.load_report",
            lambda *args, **kwargs: ReportData(
                title="Test", period_headers=["Jan"], rows=[]
            ),
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(ReportsPane) is not None

    async def test_table_has_columns_after_load(
        self, reports_journal: Path, monkeypatch
    ):
        """After loading, the table should have Account + period columns."""
        from hledger_tui.hledger import _parse_report_csv

        data = _parse_report_csv(_SAMPLE_IS_CSV)
        monkeypatch.setattr(
            "hledger_tui.widgets.reports_pane.load_report",
            lambda *args, **kwargs: data,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            table = app.query_one("#reports-table", DataTable)
            # Account + 2 period columns
            assert len(table.columns) == 3

    async def test_default_report_is_income_statement(
        self, reports_journal: Path, monkeypatch
    ):
        """The default report type should be 'is' (Income Statement)."""
        calls = []

        def _mock_load(*args, **kwargs):
            calls.append(kwargs.get("report_type", args[1] if len(args) > 1 else None))
            return ReportData(title="IS", period_headers=["Jan"], rows=[])

        monkeypatch.setattr(
            "hledger_tui.widgets.reports_pane.load_report", _mock_load
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            assert "is" in calls

    async def test_table_rows_populated(
        self, reports_journal: Path, monkeypatch
    ):
        """Table rows match parsed report data."""
        from hledger_tui.hledger import _parse_report_csv

        data = _parse_report_csv(_SAMPLE_IS_CSV)
        monkeypatch.setattr(
            "hledger_tui.widgets.reports_pane.load_report",
            lambda *args, **kwargs: data,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            table = app.query_one("#reports-table", DataTable)
            assert table.row_count == 5


class TestReportsPaneReload:
    """Tests for report reloading on type/period changes."""

    async def test_r_key_triggers_refresh(
        self, reports_journal: Path, monkeypatch
    ):
        """Pressing r reloads report data without crashing."""
        call_count = 0

        def _mock_load(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return ReportData(title="IS", period_headers=["Jan"], rows=[])

        monkeypatch.setattr(
            "hledger_tui.widgets.reports_pane.load_report", _mock_load
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            initial_count = call_count
            pane = app.query_one(ReportsPane)
            pane.focus()
            await pilot.press("r")
            await pilot.pause(delay=0.5)
            assert call_count > initial_count


class TestReportsPaneErrors:
    """Tests for error handling in ReportsPane."""

    async def test_hledger_error_does_not_crash(
        self, reports_journal: Path, monkeypatch
    ):
        """HledgerError during load is handled gracefully."""
        from hledger_tui.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("report failed")

        monkeypatch.setattr(
            "hledger_tui.widgets.reports_pane.load_report", _raise
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            assert app.query_one(ReportsPane) is not None
