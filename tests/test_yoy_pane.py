"""Year-over-year comparison mode in Reports (issue #278)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.period import year_range
from hledger_textual.widgets.pane_mixin import set_period
from hledger_textual.widgets.reports_pane import ReportsPane
from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


@pytest.fixture
def yoy_journal(tmp_path: Path) -> Path:
    """Three-year journal: salary grows, food appears from 2023, bank accumulates."""
    journal = tmp_path / "yoy.journal"
    journal.write_text(
        "2022-03-15 Salary 2022\n"
        "    assets:bank:checking  €3000.00\n"
        "    income:salary  -€3000.00\n"
        "\n"
        "2022-06-01 Buy shares\n"
        "    assets:investments:etf  10 XDWD @ €50.00\n"
        "    assets:bank:checking  -€500.00\n"
        "\n"
        "2023-04-20 Salary 2023\n"
        "    assets:bank:checking  €3600.00\n"
        "    income:salary  -€3600.00\n"
        "\n"
        "2023-09-10 Groceries\n"
        "    expenses:food  €120.00\n"
        "    assets:bank:checking  -€120.00\n"
        "\n"
        "2024-02-01 Salary 2024\n"
        "    assets:bank:checking  €4000.00\n"
        "    income:salary  -€4000.00\n"
        "\n"
        "2024-11-25 Groceries\n"
        "    expenses:food  €200.00\n"
        "    assets:bank:checking  -€200.00\n"
    )
    return journal


async def _load_comparison(app: HledgerTuiApp, mode: str) -> ReportsPane:
    """Scope the app to 2022..2024, enable comparison, load, return the pane."""
    pane = app.screen.query_one(ReportsPane)
    set_period(pane, year_range(2022, 2024))
    pane.set_comparison(mode)
    worker = pane._load_report_data()
    await worker.wait()
    return pane


class TestYearComparison:
    """Year mode shows yearly columns plus trailing Δ / Δ%."""

    async def test_year_columns_and_delta(self, yoy_journal: Path) -> None:
        app = HledgerTuiApp(journal_file=yoy_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = await _load_comparison(app, "year")
            assert pane._report_data is not None
            assert pane._report_data.period_headers == [
                "2022", "2023", "2024", "Δ", "Δ%",
            ]

    async def test_bs_columns_are_end_of_year_balances(
        self, yoy_journal: Path
    ) -> None:
        app = HledgerTuiApp(journal_file=yoy_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.screen.query_one(ReportsPane)
            pane._report_type = "bs"
            set_period(pane, year_range(2022, 2024))
            pane.set_comparison("year")
            worker = pane._load_report_data()
            await worker.wait()
            assert pane._report_data is not None
            assert pane._report_data.period_headers[:3] == [
                "2022", "2023", "2024",
            ]
            checking = next(
                r for r in pane._report_data.rows
                if r.account == "assets:bank:checking"
            )
            # End-of-year balances accumulate: 2023 (5980) != 2023 flows (3480).
            # Strip grouping separators: the test env may lack locale data.
            assert [a.replace(",", "") for a in checking.amounts[:3]] == [
                "€2500.00",
                "€5980.00",
                "€9780.00",
            ]

    async def test_toggle_key_cycles_modes(self, yoy_journal: Path) -> None:
        app = HledgerTuiApp(journal_file=yoy_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            assert app.screen.query_one(ReportsPane)._comparison == "off"
            await pilot.press("y")
            assert app.screen.query_one(ReportsPane)._comparison == "year"
            await pilot.press("y")
            assert app.screen.query_one(ReportsPane)._comparison == "quarter"
            await pilot.press("y")
            assert app.screen.query_one(ReportsPane)._comparison == "off"


class TestComparisonDrillDown:
    """Interval-aware column mapping incl. whole-range Δ drill."""

    def test_year_column_maps_to_year(self) -> None:
        from hledger_textual.widgets.reports_pane import ReportsPane as P

        pane = P.__new__(P)
        pane._period_begin = date(2022, 6, 1)
        pane._comparison = "year"
        pane._comparison_years = [2022, 2023, 2024]
        assert pane._column_to_date_query(0) == "date:2022"
        assert pane._column_to_date_query(2) == "date:2024"

    def test_quarter_column_maps_to_quarter_start(self) -> None:
        from hledger_textual.widgets.reports_pane import ReportsPane as P

        pane = P.__new__(P)
        pane._period_begin = date(2022, 1, 1)
        pane._comparison = "quarter"
        pane._comparison_years = [2022, 2023, 2024]
        assert pane._column_to_date_query(0) == "date:2022-01"
        assert pane._column_to_date_query(5) == "date:2023-04"

    def test_month_mode_unchanged(self) -> None:
        from hledger_textual.widgets.reports_pane import ReportsPane as P

        pane = P.__new__(P)
        pane._period_begin = date(2024, 3, 1)
        pane._comparison = "off"
        pane._comparison_years = []
        assert pane._column_to_date_query(0) == "date:2024-03"
        assert pane._column_to_date_query(2) == "date:2024-05"


class TestComparisonExportAndChart:
    """Exports mirror the year columns; charts group by year without Δ."""

    async def test_export_mirrors_columns(self, yoy_journal: Path) -> None:
        app = HledgerTuiApp(journal_file=yoy_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = await _load_comparison(app, "year")
            data = pane.get_export_data()
            assert data.headers[:5] == ["Account", "2022", "2023", "2024", "Δ"]

    async def test_chart_groups_by_year(self, yoy_journal: Path) -> None:
        from hledger_textual.comparison import without_comparison_columns
        from hledger_textual.widgets.report_chart import extract_chart_data

        app = HledgerTuiApp(journal_file=yoy_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = await _load_comparison(app, "year")
            assert pane._report_data is not None
            charted = extract_chart_data(
                without_comparison_columns(pane._report_data), "is"
            )
            assert charted["labels"] == ["2022", "2023", "2024"]

    def test_without_comparison_columns_strips(self) -> None:
        from hledger_textual.comparison import (
            append_comparison_columns,
            without_comparison_columns,
        )
        from hledger_textual.models import ReportData, ReportRow

        data = ReportData(
            title="t",
            period_headers=["2022", "2024"],
            rows=[ReportRow(account="a", amounts=["€1.00", "€2.00"])],
        )
        extended = append_comparison_columns(data)
        assert extended.period_headers[-2:] == ["Δ", "Δ%"]
        stripped = without_comparison_columns(extended)
        assert stripped.period_headers == ["2022", "2024"]
        assert stripped.rows[0].amounts == ["€1.00", "€2.00"]


class TestNormalizeYearHeaders:
    """Balance-sheet date headers collapse to year labels in comparison."""

    def test_bs_year_end_dates_collapse(self) -> None:
        from hledger_textual.comparison import normalize_comparison_headers

        assert normalize_comparison_headers(
            ["2022-12-31", "2023-12-31"], "year"
        ) == ["2022", "2023"]

    def test_plain_year_headers_unchanged(self) -> None:
        from hledger_textual.comparison import normalize_comparison_headers

        assert normalize_comparison_headers(["2022", "2023"], "year") == [
            "2022",
            "2023",
        ]

    def test_bs_quarter_end_dates_collapse(self) -> None:
        from hledger_textual.comparison import normalize_comparison_headers

        assert normalize_comparison_headers(
            ["2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31"],
            "quarter",
        ) == ["2022Q1", "2022Q2", "2022Q3", "2022Q4"]

    def test_plain_quarter_headers_unchanged(self) -> None:
        from hledger_textual.comparison import normalize_comparison_headers

        assert normalize_comparison_headers(["2022Q1", "2022Q2"], "quarter") == [
            "2022Q1",
            "2022Q2",
        ]
