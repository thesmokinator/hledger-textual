"""Tests for the ReportsPane widget."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Select

from hledger_textual.models import ReportData, ReportRow
from hledger_textual.widgets.report_chart import ReportChart
from hledger_textual.widgets.reports_pane import ReportsPane
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
            "hledger_textual.widgets.reports_pane.load_report",
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
        from hledger_textual.hledger import _parse_report_csv

        data = _parse_report_csv(_SAMPLE_IS_CSV)
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
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
            "hledger_textual.widgets.reports_pane.load_report", _mock_load
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            assert "is" in calls

    async def test_table_rows_populated(
        self, reports_journal: Path, monkeypatch
    ):
        """Table rows match parsed report data."""
        from hledger_textual.hledger import _parse_report_csv

        data = _parse_report_csv(_SAMPLE_IS_CSV)
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: data,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            table = app.query_one("#reports-table", DataTable)
            assert table.row_count == 7


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
            "hledger_textual.widgets.reports_pane.load_report", _mock_load
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
        from hledger_textual.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("report failed")

        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report", _raise
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            assert app.query_one(ReportsPane) is not None


class TestReportsPaneChart:
    """Tests for chart toggle and update in ReportsPane."""

    async def test_c_key_toggles_chart_visibility(
        self, reports_journal: Path, monkeypatch
    ):
        """Pressing c toggles the chart's visible CSS class."""
        from hledger_textual.hledger import _parse_report_csv

        data = _parse_report_csv(_SAMPLE_IS_CSV)
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: data,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            chart = app.query_one("#report-chart", ReportChart)
            assert not chart.has_class("visible")

            pane = app.query_one(ReportsPane)
            pane.focus()
            await pilot.press("c")
            await pilot.pause()
            assert chart.has_class("visible")

            await pilot.press("c")
            await pilot.pause()
            assert not chart.has_class("visible")

    async def test_chart_updates_on_report_load(
        self, reports_journal: Path, monkeypatch
    ):
        """Chart is updated when report data loads."""
        from hledger_textual.hledger import _parse_report_csv

        data = _parse_report_csv(_SAMPLE_IS_CSV)
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: data,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            chart = app.query_one("#report-chart", ReportChart)
            # Chart should exist and have been replotted (no crash)
            assert chart is not None


_SAMPLE_INV_CSV = (
    '"Monthly Balance Changes 2026-01-01..2026-03-01","",""\n'
    '"Account","Jan","Feb"\n'
    '"assets:investments:XDWD","€100.00","€200.00"\n'
    '"assets:investments:XEON","€8450.00","€0"\n'
    '"Total:","€8550.00","€200.00"\n'
)


class TestReportsPaneInvestments:
    """Tests for the investments toggle on the Reports pane."""

    async def test_i_key_toggles_investments(
        self, reports_journal: Path, monkeypatch
    ):
        """Pressing i toggles the _show_investments flag and triggers reload."""
        call_count = 0

        def _mock_load(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return ReportData(title="IS", period_headers=["Jan"], rows=[])

        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report", _mock_load
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_investment_report",
            lambda *args, **kwargs: ReportData(
                title="", period_headers=[], rows=[]
            ),
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            pane = app.query_one(ReportsPane)
            assert not pane._show_investments

            pane.focus()
            await pilot.press("i")
            await pilot.pause(delay=0.5)
            assert pane._show_investments

            await pilot.press("i")
            await pilot.pause(delay=0.5)
            assert not pane._show_investments

    async def test_investments_rows_appended_to_is(
        self, reports_journal: Path, monkeypatch
    ):
        """With investments on + IS report, investment rows are appended."""
        from hledger_textual.hledger import _parse_report_csv

        is_data = _parse_report_csv(_SAMPLE_IS_CSV)
        inv_data = _parse_report_csv(_SAMPLE_INV_CSV)

        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: is_data,
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_investment_report",
            lambda *args, **kwargs: inv_data,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            pane = app.query_one(ReportsPane)
            pane.focus()
            await pilot.press("i")
            await pilot.pause(delay=0.5)

            # Check that "Investments" section header was added
            assert pane._report_data is not None
            section_names = [
                r.account for r in pane._report_data.rows if r.is_section_header
            ]
            assert "Investments" in section_names

            # Check that investment data rows are present
            accounts = [r.account for r in pane._report_data.rows]
            assert "assets:investments:XDWD" in accounts
            assert "assets:investments:XEON" in accounts

    async def test_investments_no_effect_on_bs(
        self, reports_journal: Path, monkeypatch
    ):
        """The investments toggle has no effect for BS report type."""
        from hledger_textual.hledger import _parse_report_csv

        bs_data = _parse_report_csv(_SAMPLE_BS_CSV)
        inv_call_count = 0

        def _mock_inv(*args, **kwargs):
            nonlocal inv_call_count
            inv_call_count += 1
            return ReportData(title="", period_headers=[], rows=[])

        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: bs_data,
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_investment_report",
            _mock_inv,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            pane = app.query_one(ReportsPane)
            pane._report_type = "bs"
            pane._show_investments = True
            pane.focus()
            await pilot.press("r")
            await pilot.pause(delay=0.5)

            # Investment data should not be merged for BS
            assert pane._report_data is not None
            section_names = [
                r.account for r in pane._report_data.rows if r.is_section_header
            ]
            assert "Investments" not in section_names
            assert inv_call_count == 0

    async def test_empty_investment_data_no_extra_rows(
        self, reports_journal: Path, monkeypatch
    ):
        """Empty investment data doesn't add spurious rows."""
        from hledger_textual.hledger import _parse_report_csv

        is_data = _parse_report_csv(_SAMPLE_IS_CSV)
        original_row_count = len(is_data.rows)

        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: _parse_report_csv(_SAMPLE_IS_CSV),
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_investment_report",
            lambda *args, **kwargs: ReportData(
                title="", period_headers=[], rows=[]
            ),
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            pane = app.query_one(ReportsPane)
            pane.focus()
            await pilot.press("i")
            await pilot.pause(delay=0.5)

            # No extra rows should be added for empty investment data
            assert pane._report_data is not None
            assert len(pane._report_data.rows) == original_row_count
