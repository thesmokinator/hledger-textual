"""Tests for the ReportsPane widget."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from textual.app import App, ComposeResult
from textual.coordinate import Coordinate
from textual.widgets import DataTable

from hledger_textual.models import ReportData, ReportRow
from hledger_textual.widgets.reports_pane import ReportsPane, _format_custom_output
from tests.conftest import wait_until


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


class TestReportsPaneVimNavigation:
    """Tests for h/j/k/l vim-style cursor navigation in ReportsPane."""

    async def test_l_key_moves_cursor_right(
        self, reports_journal: Path, monkeypatch
    ):
        """Pressing 'l' advances the cell cursor to the next column."""
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
            table.move_cursor(row=1, column=0)
            await pilot.pause()
            assert table.cursor_column == 0

            app.query_one(ReportsPane).focus()
            await pilot.press("l")
            await pilot.pause()
            assert table.cursor_column == 1

    async def test_h_key_moves_cursor_left(
        self, reports_journal: Path, monkeypatch
    ):
        """Pressing 'h' moves the cell cursor back one column."""
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
            table.move_cursor(row=1, column=1)
            await pilot.pause()
            assert table.cursor_column == 1

            app.query_one(ReportsPane).focus()
            await pilot.press("h")
            await pilot.pause()
            assert table.cursor_column == 0


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
    """Tests for chart modal in ReportsPane."""

    async def test_c_key_opens_chart_modal(
        self, reports_journal: Path, monkeypatch
    ):
        """Pressing c opens the ReportChartModal."""
        from hledger_textual.hledger import _parse_report_csv
        from hledger_textual.screens.report_chart_modal import ReportChartModal

        data = _parse_report_csv(_SAMPLE_IS_CSV)
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: data,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            pane = app.query_one(ReportsPane)
            pane.focus()
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ReportChartModal)
            await pilot.press("escape")
            await pilot.pause(delay=0.5)
            assert not isinstance(app.screen, ReportChartModal)

    async def test_c_key_does_nothing_without_data(
        self, reports_journal: Path, monkeypatch
    ):
        """Pressing c shows a warning when no report data is loaded."""
        from hledger_textual.hledger import HledgerError
        from hledger_textual.screens.report_chart_modal import ReportChartModal

        def _raise(*args, **kwargs):
            raise HledgerError("no data")

        monkeypatch.setattr("hledger_textual.widgets.reports_pane.load_report", _raise)
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            pane = app.query_one(ReportsPane)
            pane.focus()
            await pilot.press("c")
            await pilot.pause()
            assert not isinstance(app.screen, ReportChartModal)


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

            # Check that investment data rows are present (prefix stripped)
            accounts = [r.account for r in pane._report_data.rows]
            assert "XDWD" in accounts
            assert "XEON" in accounts

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

    async def test_t_key_toggles_tree_mode(
        self, reports_journal: Path, monkeypatch
    ):
        """Pressing t flips _tree_mode and triggers reload with the new mode."""
        captured_modes: list[str] = []

        def _mock_load(*args, **kwargs):
            captured_modes.append(kwargs.get("mode", "flat"))
            return ReportData(title="IS", period_headers=["Jan"], rows=[])

        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report", _mock_load
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            pane = app.query_one(ReportsPane)
            assert not pane._tree_mode
            assert captured_modes[-1] == "flat"

            pane.focus()
            await pilot.press("t")
            await pilot.pause(delay=0.5)
            assert pane._tree_mode
            assert captured_modes[-1] == "tree"

            await pilot.press("t")
            await pilot.pause(delay=0.5)
            assert not pane._tree_mode
            assert captured_modes[-1] == "flat"

    async def test_tree_rows_are_rendered_with_indentation(
        self, reports_journal: Path, monkeypatch
    ):
        """Rows with depth > 0 are prefixed with 2 spaces per level in the table."""
        from textual.coordinate import Coordinate

        data = ReportData(
            title="IS",
            period_headers=["Jan"],
            rows=[
                ReportRow(account="Revenues", amounts=[""], is_section_header=True),
                ReportRow(account="income", amounts=["€100.00"], depth=0),
                ReportRow(account="salary", amounts=["€80.00"], depth=1),
                ReportRow(account="freelance", amounts=["€20.00"], depth=1),
                ReportRow(account="Total:", amounts=["€100.00"], is_total=True),
                ReportRow(account="Expenses", amounts=[""], is_section_header=True),
                ReportRow(account="expenses", amounts=["€50.00"], depth=0),
                ReportRow(account="food", amounts=["€30.00"], depth=1),
                ReportRow(account="groceries", amounts=["€25.00"], depth=2),
            ],
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: data,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            table = app.query_one("#reports-table", DataTable)

            cells_by_account: dict[str, str] = {}
            for row_idx in range(table.row_count):
                cell = table.get_cell_at(Coordinate(row_idx, 0))
                text = cell.plain if hasattr(cell, "plain") else str(cell)
                stripped = text.lstrip(" ")
                if stripped:
                    cells_by_account[stripped] = text

            assert cells_by_account["income"] == "income"
            assert cells_by_account["salary"] == "  salary"
            assert cells_by_account["freelance"] == "  freelance"
            assert cells_by_account["expenses"] == "expenses"
            assert cells_by_account["food"] == "  food"
            assert cells_by_account["groceries"] == "    groceries"

    async def test_t_key_noop_when_custom_report_active(
        self, reports_journal: Path, monkeypatch
    ):
        """Pressing t does nothing when a custom report is active."""
        def _mock_load(*args, **kwargs):
            return ReportData(title="IS", period_headers=["Jan"], rows=[])

        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report", _mock_load
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            pane = app.query_one(ReportsPane)
            pane._custom_report_name = "my-report"
            initial = pane._tree_mode
            pane.focus()
            await pilot.press("t")
            await pilot.pause(delay=0.2)
            assert pane._tree_mode == initial

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


# ------------------------------------------------------------------
# Unit tests for _format_custom_output  (#86)
# ------------------------------------------------------------------


class TestFormatCustomOutput:
    """Tests for the _format_custom_output helper function."""

    def test_bal_output_preserves_all_data_lines_with_skip_title(self):
        """bal output has no title; all indented data lines must be kept.

        Regression test for #86: the first data line was incorrectly
        treated as a title and dropped when skip_title=True.
        """
        raw = (
            "          $-49583.15  Liabilities:Members:Jason\n"
            "          $-49306.64  Liabilities:Members:Shannon\n"
        )
        result = _format_custom_output(raw, skip_title=True)
        plain = result.plain
        assert "Jason" in plain
        assert "Shannon" in plain

    def test_bal_output_preserves_all_data_lines_without_skip_title(self):
        """bal output lines are preserved when skip_title=False too."""
        raw = (
            "          $-49583.15  Liabilities:Members:Jason\n"
            "          $-49306.64  Liabilities:Members:Shannon\n"
        )
        result = _format_custom_output(raw, skip_title=False)
        plain = result.plain
        assert "Jason" in plain
        assert "Shannon" in plain

    def test_compound_report_title_skipped(self):
        """Compound report title (non-indented) is skipped with skip_title=True."""
        raw = (
            "Balance Sheet 2026-03-31\n"
            "\n"
            "                  || 2026-03-31\n"
            "==================||===========\n"
            " Assets           ||   $5000.00\n"
        )
        result = _format_custom_output(raw, skip_title=True)
        plain = result.plain
        assert "Balance Sheet" not in plain
        assert "Assets" in plain

    def test_compound_report_title_kept(self):
        """Compound report title is rendered bold when skip_title=False."""
        raw = (
            "Balance Sheet 2026-03-31\n"
            "\n"
            " Assets           ||   $5000.00\n"
        )
        result = _format_custom_output(raw, skip_title=False)
        plain = result.plain
        assert "Balance Sheet" in plain
        assert "Assets" in plain

    def test_single_indented_line(self):
        """A single indented data line is not dropped as a title."""
        raw = "          $100.00  expenses:food\n"
        result = _format_custom_output(raw, skip_title=True)
        assert "expenses:food" in result.plain

    def test_total_separator_styling(self):
        """Lines after --- separator are treated as totals, not dropped."""
        raw = (
            "          $100.00  expenses:food\n"
            "--------------------\n"
            "          $100.00\n"
        )
        result = _format_custom_output(raw, skip_title=True)
        plain = result.plain
        assert "expenses:food" in plain
        assert "$100.00" in plain

    def test_empty_input(self):
        """Empty input produces empty output."""
        result = _format_custom_output("", skip_title=True)
        assert result.plain == ""

    def test_leading_blank_lines_before_data(self):
        """Leading blank lines before indented data are handled correctly."""
        raw = (
            "\n"
            "\n"
            "          $500.00  assets:bank\n"
        )
        result = _format_custom_output(raw, skip_title=True)
        assert "assets:bank" in result.plain


# ------------------------------------------------------------------
# Drill-down tests  (#99)
# ------------------------------------------------------------------


class TestReportsPaneDrillDown:
    """Tests for drilling down from reports to transactions."""

    async def test_enter_on_data_cell_pushes_transactions_screen(
        self, reports_journal: Path, monkeypatch
    ):
        """Selecting a data cell pushes AccountTransactionsScreen with date query."""
        from hledger_textual.hledger import _parse_report_csv
        from hledger_textual.screens.account_transactions import (
            AccountTransactionsScreen,
        )

        data = _parse_report_csv(_SAMPLE_IS_CSV)
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: data,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            table = app.query_one("#reports-table", DataTable)
            # Row 1 = "income:salary", col 1 = first period column ("Jan")
            table.move_cursor(row=1, column=1)
            await pilot.pause()

            pane = app.query_one(ReportsPane)
            pane.action_view_transactions()
            await pilot.pause()

            assert isinstance(app.screen, AccountTransactionsScreen)
            assert app.screen.account == "income:salary"
            assert app.screen._date_query is not None
            assert "date:" in app.screen._date_query

            await pilot.press("escape")
            await pilot.pause(delay=0.5)
            assert not isinstance(app.screen, AccountTransactionsScreen)

    async def test_enter_on_account_column_has_no_date_filter(
        self, reports_journal: Path, monkeypatch
    ):
        """Selecting the Account column drills down without a date filter."""
        from hledger_textual.hledger import _parse_report_csv
        from hledger_textual.screens.account_transactions import (
            AccountTransactionsScreen,
        )

        data = _parse_report_csv(_SAMPLE_IS_CSV)
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: data,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            table = app.query_one("#reports-table", DataTable)
            # Row 1 = "income:salary", Account column (col 0)
            table.move_cursor(row=1, column=0)
            await pilot.pause()

            pane = app.query_one(ReportsPane)
            pane.action_view_transactions()
            await pilot.pause()

            assert isinstance(app.screen, AccountTransactionsScreen)
            assert app.screen.account == "income:salary"
            assert app.screen._date_query is None

            await pilot.press("escape")

    async def test_enter_on_section_header_does_nothing(
        self, reports_journal: Path, monkeypatch
    ):
        """Selecting a section header row does not push a screen."""
        from hledger_textual.hledger import _parse_report_csv
        from hledger_textual.screens.account_transactions import (
            AccountTransactionsScreen,
        )

        data = _parse_report_csv(_SAMPLE_IS_CSV)
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: data,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            table = app.query_one("#reports-table", DataTable)
            # Row 0 = "Revenues" (section header)
            table.move_cursor(row=0, column=0)
            await pilot.pause()

            pane = app.query_one(ReportsPane)
            pane.action_view_transactions()
            await pilot.pause()

            assert not isinstance(app.screen, AccountTransactionsScreen)

    async def test_enter_on_total_row_does_nothing(
        self, reports_journal: Path, monkeypatch
    ):
        """Selecting a total row does not push a screen."""
        from hledger_textual.hledger import _parse_report_csv
        from hledger_textual.screens.account_transactions import (
            AccountTransactionsScreen,
        )

        data = _parse_report_csv(_SAMPLE_IS_CSV)
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: data,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            table = app.query_one("#reports-table", DataTable)
            # Last row = "Net:" (total)
            table.move_cursor(row=table.row_count - 1, column=0)
            await pilot.pause()

            pane = app.query_one(ReportsPane)
            pane.action_view_transactions()
            await pilot.pause()

            assert not isinstance(app.screen, AccountTransactionsScreen)

    async def test_drill_down_in_tree_mode_uses_full_path(
        self, reports_journal: Path, monkeypatch
    ):
        """In tree mode, drill-down uses the reconstructed full account path."""
        from hledger_textual.screens.account_transactions import (
            AccountTransactionsScreen,
        )

        data = ReportData(
            title="IS",
            period_headers=["Jan"],
            rows=[
                ReportRow(account="Revenues", amounts=[""], is_section_header=True),
                ReportRow(account="income", amounts=["€100.00"], depth=0),
                ReportRow(account="salary", amounts=["€80.00"], depth=1),
            ],
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: data,
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            pane = app.query_one(ReportsPane)
            pane._tree_mode = True
            pane.focus()
            await pilot.press("r")
            await pilot.pause(delay=0.5)

            table = app.query_one("#reports-table", DataTable)
            # Row layout: 0=Revenues, 1=income, 2=salary
            table.move_cursor(row=2, column=1)
            await pilot.pause()

            pane.action_view_transactions()
            await pilot.pause()

            assert isinstance(app.screen, AccountTransactionsScreen)
            assert app.screen.account == "income:salary"

            await pilot.press("escape")


class TestFlatMultiCommodityMarker:
    """Markers for multi-commodity account rows in flat (non-stacked) mode."""

    @staticmethod
    def _make_data() -> ReportData:
        """Deterministic report with mixed multi/single-commodity rows."""
        return ReportData(
            title="BS",
            period_headers=["Jan", "Feb"],
            rows=[
                ReportRow(
                    account="assets:bank:checking",
                    amounts=["£100.00, €50.00", "£120.00, €60.00"],
                ),
                ReportRow(
                    account="assets:bank:savings",
                    amounts=["$500.00", "$600.00"],
                ),
                ReportRow(
                    account="Total:",
                    amounts=["£220.00, €110.00", "£240.00, €120.00"],
                    is_total=True,
                ),
            ],
        )

    @staticmethod
    def _cell_text(table: DataTable, row_idx: int) -> str:
        """Get the plain text of the account cell at a row index."""
        from textual.coordinate import Coordinate

        cell = table.get_cell_at(Coordinate(row_idx, 0))
        return cell.plain if hasattr(cell, "plain") else str(cell)

    async def test_marker_constant_exported(self):
        """The module exports MULTI_COMMODITY_MARKER as U+25C6 + space."""
        from hledger_textual.widgets.reports_pane import MULTI_COMMODITY_MARKER

        assert MULTI_COMMODITY_MARKER == "◆ "

    async def test_flat_mode_multi_commodity_shows_marker(
        self, reports_journal: Path, monkeypatch
    ):
        """Flat-mode multi-commodity data row prepends the marker."""
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: ReportData(title="", period_headers=[], rows=[]),
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.query_one(ReportsPane)
            pane._report_data = self._make_data()
            pane._stacked_currency = False
            pane._apply_report()
            await pilot.pause()

            table = app.query_one("#reports-table", DataTable)
            found = False
            for row_idx in range(table.row_count):
                text = self._cell_text(table, row_idx)
                if "assets:bank:checking" in text:
                    assert text.startswith("◆ "), f"expected marker, got {text!r}"
                    found = True
            assert found, "checking row not found"

    async def test_flat_mode_single_currency_no_marker(
        self, reports_journal: Path, monkeypatch
    ):
        """Flat-mode single-currency data row has no marker."""
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: ReportData(title="", period_headers=[], rows=[]),
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.query_one(ReportsPane)
            pane._report_data = self._make_data()
            pane._stacked_currency = False
            pane._apply_report()
            await pilot.pause()

            table = app.query_one("#reports-table", DataTable)
            found = False
            for row_idx in range(table.row_count):
                text = self._cell_text(table, row_idx)
                if "assets:bank:savings" in text:
                    assert not text.startswith("◆"), f"unexpected marker on {text!r}"
                    found = True
            assert found, "savings row not found"

    async def test_flat_mode_total_row_no_marker(
        self, reports_journal: Path, monkeypatch
    ):
        """Total rows never receive the marker even when multi-commodity."""
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: ReportData(title="", period_headers=[], rows=[]),
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.query_one(ReportsPane)
            pane._report_data = self._make_data()
            pane._stacked_currency = False
            pane._apply_report()
            await pilot.pause()

            table = app.query_one("#reports-table", DataTable)
            found = False
            for row_idx in range(table.row_count):
                text = self._cell_text(table, row_idx)
                if "Total:" in text:
                    assert not text.startswith("◆"), f"unexpected marker on {text!r}"
                    found = True
            assert found, "Total row not found"

    async def test_stacked_mode_no_marker(
        self, reports_journal: Path, monkeypatch
    ):
        """In stacked mode, rows are split per commodity — no marker."""
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: ReportData(title="", period_headers=[], rows=[]),
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.query_one(ReportsPane)
            pane._report_data = self._make_data()
            # _stacked_currency defaults to True
            pane._apply_report()
            await pilot.pause()

            table = app.query_one("#reports-table", DataTable)
            for row_idx in range(table.row_count):
                text = self._cell_text(table, row_idx)
                assert not text.startswith("◆"), f"unexpected marker at row {row_idx}: {text!r}"

    async def test_tree_mode_no_marker(
        self, reports_journal: Path, monkeypatch
    ):
        """Tree mode already shows depth — never adds the marker."""
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: ReportData(title="", period_headers=[], rows=[]),
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.query_one(ReportsPane)
            pane._report_data = self._make_data()
            pane._stacked_currency = False
            pane._tree_mode = True
            pane._apply_report()
            await pilot.pause()

            table = app.query_one("#reports-table", DataTable)
            for row_idx in range(table.row_count):
                text = self._cell_text(table, row_idx)
                assert not text.startswith("◆"), f"unexpected marker at row {row_idx}: {text!r}"


class TestFlatMultiCommodityRowHeight:
    """Multi-commodity rows in flat (non-stacked) mode must render every
    stacked currency line, not just the first."""

    @staticmethod
    def _make_data() -> ReportData:
        """Deterministic report with mixed multi/single-commodity rows."""
        return ReportData(
            title="BS",
            period_headers=["Jan", "Feb"],
            rows=[
                ReportRow(
                    account="assets:bank:checking",
                    amounts=["£100.00, €50.00", "£120.00, €60.00"],
                ),
                ReportRow(
                    account="assets:bank:savings",
                    amounts=["$500.00", "$600.00"],
                ),
            ],
        )

    @staticmethod
    def _row_height_by_account_text(table: DataTable, needle: str) -> int:
        """Return the rendered height of the row whose account cell matches."""
        keys = list(table.rows.keys())
        for row_idx in range(table.row_count):
            cell = table.get_cell_at(Coordinate(row_idx, 0))
            text = cell.plain if hasattr(cell, "plain") else str(cell)
            if needle in text:
                return table.get_row_height(keys[row_idx])
        raise AssertionError(f"row containing {needle!r} not found")

    async def test_flat_multi_commodity_row_has_multi_line_height(
        self, reports_journal: Path, monkeypatch
    ):
        """A flat multi-commodity row renders at height >= 2."""
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: ReportData(title="", period_headers=[], rows=[]),
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.query_one(ReportsPane)
            pane._report_data = self._make_data()
            pane._stacked_currency = False
            pane._apply_report()
            await pilot.pause()

            table = app.query_one("#reports-table", DataTable)
            height = self._row_height_by_account_text(table, "checking")
            assert height >= 2, (
                f"multi-commodity row height is {height}; stacked currencies clipped"
            )

    async def test_flat_single_commodity_row_stays_single_line(
        self, reports_journal: Path, monkeypatch
    ):
        """A flat single-commodity row renders at height 1."""
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: ReportData(title="", period_headers=[], rows=[]),
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.query_one(ReportsPane)
            pane._report_data = self._make_data()
            pane._stacked_currency = False
            pane._apply_report()
            await pilot.pause()

            table = app.query_one("#reports-table", DataTable)
            height = self._row_height_by_account_text(table, "savings")
            assert height == 1, f"single-commodity row height is {height}"

    async def test_stacked_mode_rows_stay_single_line(
        self, reports_journal: Path, monkeypatch
    ):
        """Stacked mode emits one row per commodity — all height 1."""
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *args, **kwargs: ReportData(title="", period_headers=[], rows=[]),
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.query_one(ReportsPane)
            pane._report_data = self._make_data()
            # _stacked_currency defaults to True
            pane._apply_report()
            await pilot.pause()

            table = app.query_one("#reports-table", DataTable)
            keys = list(table.rows.keys())
            for row_idx in range(table.row_count):
                height = table.get_row_height(keys[row_idx])
                assert height == 1, (
                    f"stacked row {row_idx} height is {height}; expected 1"
                )


class TestReportsCommodityResolution:
    """The reports pane must resolve the commodity like the other panes."""

    async def test_load_report_receives_resolved_commodity(
        self, reports_journal: Path, monkeypatch
    ):
        """resolve_default_commodity's value is forwarded to load_report."""
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.resolve_default_commodity",
            lambda _file: "€",
        )
        seen: list[dict] = []

        def spy_load_report(*args, **kwargs):
            seen.append({"args": args, "kwargs": kwargs})
            return ReportData(title="Test", period_headers=["Jan"], rows=[])

        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report", spy_load_report
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: len(seen) >= 1)

        assert seen, "load_report was not called"
        assert seen[-1]["kwargs"].get("commodity") == "€"

    async def test_load_report_none_when_unconfigured(
        self, reports_journal: Path, monkeypatch
    ):
        """Unset config and no journal directive -> commodity=None (no -X)."""
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.resolve_default_commodity",
            lambda _file: None,
        )
        seen: list[dict] = []

        def spy_load_report(*args, **kwargs):
            seen.append({"args": args, "kwargs": kwargs})
            return ReportData(title="Test", period_headers=["Jan"], rows=[])

        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report", spy_load_report
        )
        app = _ReportsApp(reports_journal)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: len(seen) >= 1)

        assert seen, "load_report was not called"
        assert seen[-1]["kwargs"].get("commodity") is None
