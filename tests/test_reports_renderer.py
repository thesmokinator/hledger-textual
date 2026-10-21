"""Unit tests for the pure reports renderer helpers.

These tests exercise :mod:`hledger_textual.widgets.reports_renderer`
without mounting any widget and without the hledger binary.
"""

from __future__ import annotations

from hledger_textual.models import ReportData, ReportRow
from hledger_textual.widgets.reports_renderer import (
    MULTI_COMMODITY_MARKER,
    build_report_rows,
    format_custom_output,
    merge_investments,
)


def _data(rows: list[ReportRow], headers: list[str] | None = None) -> ReportData:
    return ReportData(title="Report", period_headers=headers or ["2026-01"], rows=rows)


class TestBuildReportRows:
    """Tests for build_report_rows."""

    def test_section_header_and_total_get_spacer_rows(self):
        """Section headers (after the first row) and totals get a spacer."""
        data = _data([
            ReportRow(account="Income", is_section_header=True),
            ReportRow(account="Salary", amounts=["€100.00"]),
            ReportRow(account="Total", amounts=["€100.00"], is_total=True),
        ])
        rows, table_rows, paths = build_report_rows(data, tree_mode=False, stacked_currency=False)
        # header row, salary row, spacer, total row
        assert len(rows) == 4
        assert table_rows[2] is None
        assert paths[2] == ""

    def test_tree_mode_recomputes_full_paths(self):
        """Tree fragments are joined into full colon-separated paths."""
        data = _data([
            ReportRow(account="expenses", amounts=["€10.00"], depth=0),
            ReportRow(account="food", amounts=["€10.00"], depth=1),
        ])
        _, _, paths = build_report_rows(data, tree_mode=True, stacked_currency=False)
        assert paths == ["expenses", "expenses:food"]

    def test_flat_mode_marks_multi_commodity_accounts(self):
        """Flat non-stacked mode prefixes multi-currency accounts."""
        data = _data([ReportRow(account="assets:bank", amounts=["€10.00, $5.00"])])
        rows, _, _ = build_report_rows(data, tree_mode=False, stacked_currency=False)
        assert rows[0][0][0].plain.startswith(MULTI_COMMODITY_MARKER)

    def test_stacked_mode_expands_one_row_per_commodity(self):
        """Stacked mode renders each commodity on its own row."""
        data = _data([ReportRow(account="assets:bank", amounts=["€10.00, $5.00"])])
        rows, table_rows, _ = build_report_rows(data, tree_mode=False, stacked_currency=True)
        assert len(rows) == 2
        assert table_rows[0] is table_rows[1]

    def test_single_currency_row_uses_auto_height(self):
        """Ordinary rows are flagged for auto height; spacers are not."""
        data = _data([ReportRow(account="Salary", amounts=["€100.00"])])
        rows, _, _ = build_report_rows(data, tree_mode=False, stacked_currency=False)
        assert rows[0][1] is True


class TestMergeInvestments:
    """Tests for merge_investments."""

    def test_appends_investment_section(self):
        """Investment leaf rows are appended under a section header."""
        is_data = _data([ReportRow(account="Salary", amounts=["€100.00"])])
        inv_data = _data([ReportRow(account="assets:broker:STCK", amounts=["€50.00"])])
        merged = merge_investments(is_data, inv_data)
        accounts = [r.account for r in merged.rows]
        assert accounts == ["Salary", "Investments", "STCK"]
        assert merged.rows[1].is_section_header


class TestFormatCustomOutput:
    """Tests for format_custom_output."""

    def test_skip_title_drops_first_line(self):
        """With skip_title the hledger title line is omitted."""
        result = format_custom_output("Balance Sheet\n  €10.00  assets\n", skip_title=True)
        assert "Balance Sheet" not in result.plain

    def test_title_is_kept_by_default(self):
        """Without skip_title the title line is rendered."""
        result = format_custom_output("Balance Sheet\n  €10.00  assets\n")
        assert "Balance Sheet" in result.plain
