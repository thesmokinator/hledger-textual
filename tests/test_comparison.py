"""Comparison delta/growth computation (issue #278)."""

from __future__ import annotations

from hledger_textual.models import ReportData, ReportRow


def _data(headers: list[str], cells: list[list[str]]) -> ReportData:
    """Build a ReportData with one account row per cell list."""
    return ReportData(
        title="t",
        period_headers=headers,
        rows=[
            ReportRow(account=f"acct{i}", amounts=row) for i, row in enumerate(cells)
        ],
    )


class TestFormatDelta:
    """format_delta diffs last vs first per commodity."""

    def test_simple_flow_delta(self) -> None:
        from hledger_textual.comparison import format_delta

        assert format_delta("€3000.00", "€3800.00") == "+€800.00"

    def test_negative_delta(self) -> None:
        from hledger_textual.comparison import format_delta

        assert format_delta("€200.00", "€120.00") == "-€80.00"

    def test_zero_delta(self) -> None:
        from hledger_textual.comparison import format_delta

        assert format_delta("€200.00", "€200.00") == "€0.00"

    def test_empty_cells_are_zero(self) -> None:
        from hledger_textual.comparison import format_delta

        assert format_delta("", "€200.00") == "+€200.00"
        assert format_delta("0", "0") == "0.00"

    def test_multicommodity_cells(self) -> None:
        from hledger_textual.comparison import format_delta

        result = format_delta("10 XDWD, €2500.00", "10 XDWD, €5980.00")
        assert "€" in result and "+€3,480.00" in result
        assert "XDWD" in result


class TestFormatGrowth:
    """format_growth is last-vs-first pct; zero base yields an em dash."""

    def test_simple_growth(self) -> None:
        from hledger_textual.comparison import format_growth

        assert format_growth("€3000.00", "€3800.00") == "+26.7%"

    def test_zero_base_is_dash(self) -> None:
        from hledger_textual.comparison import format_growth

        assert format_growth("0", "€200.00") == "—"
        assert format_growth("", "€200.00") == "—"

    def test_zero_to_zero_is_dash(self) -> None:
        from hledger_textual.comparison import format_growth

        assert format_growth("0", "0") == "—"

    def test_negative_growth(self) -> None:
        from hledger_textual.comparison import format_growth

        assert format_growth("€200.00", "€120.00") == "-40.0%"


class TestAppendComparisonColumns:
    """append_comparison_columns adds trailing Δ / Δ% to every data row."""

    def test_headers_and_cells_extended(self) -> None:
        from hledger_textual.comparison import append_comparison_columns

        out = append_comparison_columns(
            _data(["2022", "2024"], [["€3000.00", "€3800.00"]])
        )
        assert out.period_headers == ["2022", "2024", "Δ", "Δ%"]
        assert out.rows[0].amounts[-2:] == ["+€800.00", "+26.7%"]

    def test_section_headers_get_blanks(self) -> None:
        from hledger_textual.comparison import append_comparison_columns

        data = ReportData(
            title="t",
            period_headers=["2022", "2024"],
            rows=[ReportRow(account="Revenues", amounts=["", ""])],
        )
        out = append_comparison_columns(data)
        assert out.rows[0].amounts == ["", "", "", ""]

    def test_single_column_has_no_delta(self) -> None:
        from hledger_textual.comparison import append_comparison_columns

        out = append_comparison_columns(_data(["2024"], [["€3800.00"]]))
        assert out.period_headers == ["2024"]
        assert out.rows[0].amounts == ["€3800.00"]

    def test_input_not_mutated(self) -> None:
        from hledger_textual.comparison import append_comparison_columns

        data = _data(["2022", "2024"], [["€3000.00", "€3800.00"]])
        append_comparison_columns(data)
        assert data.period_headers == ["2022", "2024"]
        assert data.rows[0].amounts == ["€3000.00", "€3800.00"]
