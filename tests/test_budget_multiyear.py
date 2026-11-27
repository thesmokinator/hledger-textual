"""Per-year budget totals from monthly rows (issue #282)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from hledger_textual.models import BudgetRow


def _row(actual: str, budget: str, commodity: str = "€") -> BudgetRow:
    """Build a BudgetRow from decimal strings."""
    return BudgetRow(
        account="expenses:food",
        actual=Decimal(actual),
        budget=Decimal(budget),
        commodity=commodity,
    )


class TestGroupMonthsByYear:
    """Month periods group into calendar years preserving order."""

    def test_groups_two_years(self) -> None:
        from hledger_textual.budget_yearly import group_months_by_year

        periods = ["2024-11", "2024-12", "2025-01", "2025-02"]
        assert group_months_by_year(periods) == [
            ("2024", [0, 1]),
            ("2025", [2, 3]),
        ]

    def test_single_year(self) -> None:
        from hledger_textual.budget_yearly import group_months_by_year

        assert group_months_by_year(["2024-01", "2024-02"]) == [
            ("2024", [0, 1])
        ]


class TestSumYearRow:
    """Year totals sum the monthly actuals and budgets."""

    def test_sums_actual_and_budget(self) -> None:
        from hledger_textual.budget_yearly import sum_year_row

        total = sum_year_row(
            "expenses:food", [_row("40.00", "100.00"), _row("60.00", "100.00")]
        )
        assert total.actual == Decimal("100.00")
        assert total.budget == Decimal("200.00")
        assert total.commodity == "€"
        assert total.usage_pct == pytest.approx(50.0)

    def test_changing_rules_sum_effective_budgets(self) -> None:
        """A rule change mid-range sums each month's effective budget."""
        from hledger_textual.budget_yearly import sum_year_row

        total = sum_year_row(
            "expenses:food", [_row("40.00", "100.00"), _row("60.00", "150.00")]
        )
        assert total.budget == Decimal("250.00")

    def test_zero_budget_year_is_safe(self) -> None:
        from hledger_textual.budget_yearly import sum_year_row

        total = sum_year_row(
            "expenses:food", [_row("10.00", "0.00"), _row("0.00", "0.00")]
        )
        assert total.usage_pct == 0.0

    def test_keeps_first_non_empty_commodity(self) -> None:
        from hledger_textual.budget_yearly import sum_year_row

        total = sum_year_row(
            "expenses:food",
            [_row("0.00", "0.00", ""), _row("60.00", "100.00", "€")],
        )
        assert total.commodity == "€"


class TestYearColumns:
    """Column specs interleave year totals after each December."""

    def test_interleaves_year_after_december(self) -> None:
        from hledger_textual.budget_yearly import year_columns

        periods = ["2024-11", "2024-12", "2025-01"]
        assert year_columns(periods) == [
            ("month", 0),
            ("month", 1),
            ("year", "2024", [0, 1]),
            ("month", 2),
            ("year", "2025", [2]),
        ]
