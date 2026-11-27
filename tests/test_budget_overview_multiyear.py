"""Multi-year budget overview rendering and changing rules (issue #282)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from textual.widgets import DataTable

from hledger_textual.app import HledgerTuiApp
from hledger_textual.models import Amount, AmountStyle, BudgetRow, BudgetRule
from hledger_textual.screens.budget_overview import BudgetOverviewScreen
from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


def _euro_style() -> AmountStyle:
    """Default amount style for rule construction."""
    return AmountStyle()


def _rule(account: str = "expenses:food") -> BudgetRule:
    """A budget rule used for account ordering in the overview."""
    return BudgetRule(
        account=account,
        amount=Amount(
            commodity="€", quantity=Decimal("100.00"), style=_euro_style()
        ),
    )


def _row(actual: str, budget: str, commodity: str = "€") -> BudgetRow:
    """Build a BudgetRow from decimal strings."""
    return BudgetRow(
        account="expenses:food",
        actual=Decimal(actual),
        budget=Decimal(budget),
        commodity=commodity,
    )


def _journal(tmp_path: Path) -> Path:
    """Journal with a rule change mid-year: €100 base, €150 from June."""
    today = date.today()
    year = today.year
    journal = tmp_path / "changing.journal"
    journal.write_text(
        "~ monthly\n"
        "    expenses:food  €100.00\n"
        "    assets:bank:checking\n"
        "\n"
        f"~ monthly from {year}-06-01\n"
        "    expenses:food  €150.00\n"
        "    assets:bank:checking\n"
        "\n"
        f"{year}-01-10 Groceries\n"
        "    expenses:food  €40.00\n"
        "    assets:bank:checking\n"
        "\n"
        f"{year}-07-12 Groceries\n"
        "    expenses:food  €90.00\n"
        "    assets:bank:checking\n"
    )
    return journal


class TestOverviewYearColumns:
    """The overview renders year totals after each December."""

    async def test_year_columns_and_totals(self, tmp_path: Path) -> None:
        journal = tmp_path / "empty.journal"
        journal.write_text("")
        periods = ["2023-11", "2023-12", "2024-01", "2024-02"]
        rows = {
            "expenses:food": [
                _row("40.00", "100.00"),
                _row("60.00", "100.00"),
                _row("10.00", "100.00"),
                _row("90.00", "150.00"),
            ]
        }
        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.push_screen(
                BudgetOverviewScreen(journal, rules=[_rule()])
            )
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, BudgetOverviewScreen)
            screen._populate_table(periods, rows)
            await pilot.pause()
            table = screen.query_one("#budget-overview-table", DataTable)
            labels = [
                str(col.label) for col in table.columns.values()
            ]
            assert labels == [
                "Account",
                "2023-11", "2023-12", "2023",
                "2024-01", "2024-02", "2024",
            ]
            assert table.row_count == 1

    async def test_changing_rule_year_total(self, tmp_path: Path) -> None:
        """Year totals sum each month's effective budget (€100 → €250)."""
        from hledger_textual.hledger import load_multi_period_budget_report

        journal = _journal(tmp_path)
        year = date.today().year
        periods, rows = load_multi_period_budget_report(
            journal, f"{year}-01", f"{year}-12"
        )
        assert periods[0] == f"{year}-01"
        budgets = [r.budget for r in rows["expenses:food"]]
        assert budgets[:5] == [Decimal("100.00")] * 5
        assert budgets[5:] == [Decimal("250.00")] * (len(budgets) - 5)

        from hledger_textual.budget_yearly import group_months_by_year, sum_year_row

        groups = group_months_by_year(periods)
        assert groups[0][0] == str(year)
        total = sum_year_row(
            "expenses:food",
            [rows["expenses:food"][i] for i in groups[0][1]],
        )
        expected = Decimal("100.00") * 5 + Decimal("250.00") * (
            len(groups[0][1]) - 5
        )
        assert total.budget == expected


class TestOverviewExport:
    """CSV export mirrors on-screen columns including year totals."""

    async def _mounted_screen(self, app, pilot, journal):
        from hledger_textual.screens.budget_overview import BudgetOverviewScreen

        await app.push_screen(BudgetOverviewScreen(journal, rules=[_rule()]))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BudgetOverviewScreen)
        return screen

    async def test_export_data_includes_year_totals(
        self, tmp_path: Path
    ) -> None:
        journal = tmp_path / "empty.journal"
        journal.write_text("")
        periods = ["2023-11", "2023-12", "2024-01"]
        rows = {
            "expenses:food": [
                _row("40.00", "100.00"),
                _row("60.00", "100.00"),
                _row("10.00", "100.00"),
            ]
        }
        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._mounted_screen(app, pilot, journal)
            screen._populate_table(periods, rows)
            await pilot.pause()
            data = screen.get_export_data()
            assert data is not None
            assert data.headers == [
                "Account",
                "2023-11", "2023-12", "2023",
                "2024-01", "2024",
            ]
            assert data.rows[0][0] == "expenses:food"
            assert "€100.00" in data.rows[0][3]
            assert "€10.00" in data.rows[0][5]

    async def test_export_csv_round_trip(self, tmp_path: Path) -> None:
        from hledger_textual.export import export_csv

        journal = tmp_path / "empty.journal"
        journal.write_text("")
        periods = ["2024-01", "2024-02"]
        rows = {"expenses:food": [_row("40.00", "100.00"), _row("60.00", "100.00")]}
        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._mounted_screen(app, pilot, journal)
            screen._populate_table(periods, rows)
            await pilot.pause()
            data = screen.get_export_data()
            assert data is not None
            out = tmp_path / "overview.csv"
            export_csv(data, out)
            text = out.read_text(encoding="utf-8")
            assert "2024" in text.splitlines()[0]
            assert "€100.00" in text

    async def test_x_opens_export_modal(self, tmp_path: Path) -> None:
        from hledger_textual.screens.export_modal import ExportModal

        journal = tmp_path / "empty.journal"
        journal.write_text("")
        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._mounted_screen(app, pilot, journal)
            screen._populate_table(["2024-01"], {"expenses:food": [_row("1.00", "2.00")]})
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            assert isinstance(app.screen, ExportModal)
