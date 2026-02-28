"""Tests for the report_chart module."""

from __future__ import annotations

import pytest

from textual.app import App, ComposeResult

from hledger_textual.hledger import _parse_report_csv
from hledger_textual.models import ReportData, ReportRow
from hledger_textual.widgets.report_chart import (
    ReportChart,
    extract_chart_data,
    parse_report_amount,
)


# ------------------------------------------------------------------
# Sample CSV data (reused from test_reports_pane)
# ------------------------------------------------------------------

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

_SAMPLE_CF_CSV = (
    '"Monthly Cash Flow 2026-01-01..2026-03-01","",""\n'
    '"Account","Jan","Feb"\n'
    '"Cash flows","",""\n'
    '"assets:bank:checking","€2959.20","-€100.00"\n'
    '"Net:","€2959.20","-€100.00"\n'
)


# ------------------------------------------------------------------
# TestParseReportAmount — pure function tests
# ------------------------------------------------------------------


class TestParseReportAmount:
    """Tests for parse_report_amount()."""

    def test_left_side_commodity(self):
        """Parses €3000.00 correctly."""
        assert parse_report_amount("€3000.00") == 3000.0

    def test_negative_left_side_commodity(self):
        """Parses -€40.80 correctly (sign before commodity)."""
        assert parse_report_amount("-€40.80") == -40.8

    def test_right_side_commodity(self):
        """Parses 3000.00 EUR correctly."""
        assert parse_report_amount("3000.00 EUR") == 3000.0

    def test_negative_right_side_commodity(self):
        """Parses -3000.00 EUR correctly."""
        assert parse_report_amount("-3000.00 EUR") == -3000.0

    def test_zero_with_commodity(self):
        """Parses €0 correctly."""
        assert parse_report_amount("€0") == 0.0

    def test_empty_string(self):
        """Empty string returns 0.0."""
        assert parse_report_amount("") == 0.0

    def test_plain_zero(self):
        """Plain '0' returns 0.0."""
        assert parse_report_amount("0") == 0.0

    def test_thousands_separator(self):
        """Parses €1,200.00 with thousands separator."""
        assert parse_report_amount("€1,200.00") == 1200.0


# ------------------------------------------------------------------
# TestExtractChartData — pure function tests
# ------------------------------------------------------------------


class TestExtractChartData:
    """Tests for extract_chart_data()."""

    def test_is_returns_income_expenses_net(self):
        """IS report returns income, expenses, and net arrays."""
        data = _parse_report_csv(_SAMPLE_IS_CSV)
        result = extract_chart_data(data, "is")

        assert result["labels"] == ["Jan", "Feb"]
        assert result["income"] == [3000.0, 3000.0]
        assert result["expenses"] == [40.8, 40.8]
        assert result["net"] == [2959.2, 2959.2]

    def test_bs_returns_totals(self):
        """BS report returns totals array."""
        data = _parse_report_csv(_SAMPLE_BS_CSV)
        result = extract_chart_data(data, "bs")

        assert result["labels"] == ["Jan", "Feb"]
        assert result["totals"] == [5000.0, 7000.0]

    def test_cf_returns_net(self):
        """CF report returns net array."""
        data = _parse_report_csv(_SAMPLE_CF_CSV)
        result = extract_chart_data(data, "cf")

        assert result["labels"] == ["Jan", "Feb"]
        assert result["net"] == [2959.2, -100.0]

    def test_empty_report_data(self):
        """Empty ReportData returns empty dict."""
        data = ReportData(title="", period_headers=[], rows=[])
        assert extract_chart_data(data, "is") == {}

    def test_no_rows(self):
        """ReportData with headers but no rows returns empty dict."""
        data = ReportData(title="T", period_headers=["Jan"], rows=[])
        assert extract_chart_data(data, "is") == {}

    def test_unknown_report_type(self):
        """Unknown report type returns empty dict."""
        data = _parse_report_csv(_SAMPLE_IS_CSV)
        assert extract_chart_data(data, "unknown") == {}


# ------------------------------------------------------------------
# TestReportChartWidget — integration tests
# ------------------------------------------------------------------


class _ChartApp(App):
    """Minimal app wrapping ReportChart for testing."""

    def compose(self) -> ComposeResult:
        """Compose a single ReportChart."""
        yield ReportChart(id="report-chart")


class TestReportChartWidget:
    """Integration tests for the ReportChart widget."""

    async def test_chart_mounts_without_error(self):
        """ReportChart mounts without raising exceptions."""
        app = _ChartApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(ReportChart) is not None

    async def test_replot_is_data(self):
        """Replot with IS data renders without crash."""
        data = _parse_report_csv(_SAMPLE_IS_CSV)
        chart_data = extract_chart_data(data, "is")

        app = _ChartApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            chart = app.query_one(ReportChart)
            chart.replot(chart_data, "is")
            await pilot.pause()

    async def test_replot_bs_data(self):
        """Replot with BS data renders without crash."""
        data = _parse_report_csv(_SAMPLE_BS_CSV)
        chart_data = extract_chart_data(data, "bs")

        app = _ChartApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            chart = app.query_one(ReportChart)
            chart.replot(chart_data, "bs")
            await pilot.pause()

    async def test_replot_cf_data(self):
        """Replot with CF data renders without crash."""
        data = _parse_report_csv(_SAMPLE_CF_CSV)
        chart_data = extract_chart_data(data, "cf")

        app = _ChartApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            chart = app.query_one(ReportChart)
            chart.replot(chart_data, "cf")
            await pilot.pause()

    async def test_replot_empty_data(self):
        """Replot with empty data does not crash."""
        app = _ChartApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            chart = app.query_one(ReportChart)
            chart.replot({}, "is")
            await pilot.pause()
