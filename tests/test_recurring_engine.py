"""Tests for the recurring transaction engine."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from hledger_textual.models import (
    Amount,
    AmountStyle,
    Posting,
    RecurringRule,
    TransactionStatus,
)
from hledger_textual.recurring_engine import (
    build_transaction_from_rule,
    compute_all_due_dates,
    compute_next_due_date,
    find_pending_generations,
    validate_period_expression,
)
from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


class TestValidatePeriodExpression:
    """Tests for validate_period_expression."""

    @pytest.mark.parametrize(
        "expr",
        [
            "daily",
            "weekly",
            "every 2 weeks",
            "biweekly",
            "monthly",
            "bimonthly",
            "quarterly",
            "yearly",
            "every 3 days",
            "every 6 months",
            "every 2 years",
        ],
    )
    def test_valid_expressions(self, expr: str):
        """Known period expressions are valid."""
        is_valid, error = validate_period_expression(expr)
        assert is_valid is True
        assert error == ""

    @pytest.mark.parametrize(
        "expr",
        [
            "every 3rd thursday",
            "every friday",
            "every 2nd monday",
            "every feb 14th",
        ],
    )
    def test_valid_complex_expressions(self, expr: str):
        """Complex hledger period expressions are valid."""
        is_valid, error = validate_period_expression(expr)
        assert is_valid is True
        assert error == ""

    @pytest.mark.parametrize(
        "expr",
        ["never", "sometimes", "every other day", ""],
    )
    def test_invalid_expressions(self, expr: str):
        """Unknown period expressions are invalid."""
        is_valid, error = validate_period_expression(expr)
        assert is_valid is False
        assert error != ""

    def test_invalid_expression_has_descriptive_error(self):
        """Invalid expressions return a descriptive error message."""
        is_valid, error = validate_period_expression("nonsense garbage")
        assert is_valid is False
        assert "unexpected" in error.lower() or len(error) > 0


class TestComputeNextDueDate:
    """Tests for compute_next_due_date."""

    def test_monthly_due(self):
        """Monthly rule with last_generated in Feb is due in March."""
        result = compute_next_due_date(
            "monthly",
            "2026-02-01",
            reference_date=date(2026, 3, 2),
        )
        assert result == date(2026, 3, 1)

    def test_monthly_not_due(self):
        """Monthly rule generated today is not due again."""
        result = compute_next_due_date(
            "monthly",
            "2026-03-01",
            reference_date=date(2026, 3, 2),
        )
        assert result is None

    def test_weekly(self):
        """Weekly rule due after 7 days."""
        result = compute_next_due_date(
            "weekly",
            "2026-02-20",
            reference_date=date(2026, 3, 2),
        )
        assert result == date(2026, 2, 27)

    def test_daily(self):
        """Daily rule is due next day."""
        result = compute_next_due_date(
            "daily",
            "2026-03-01",
            reference_date=date(2026, 3, 2),
        )
        assert result == date(2026, 3, 2)

    def test_biweekly(self):
        """Every 2 weeks rule."""
        result = compute_next_due_date(
            "every 2 weeks",
            "2026-02-15",
            reference_date=date(2026, 3, 2),
        )
        assert result == date(2026, 3, 1)

    def test_quarterly(self):
        """Quarterly rule."""
        result = compute_next_due_date(
            "quarterly",
            "2026-01-01",
            reference_date=date(2026, 4, 1),
        )
        assert result == date(2026, 4, 1)

    def test_yearly(self):
        """Yearly rule."""
        result = compute_next_due_date(
            "yearly",
            "2025-03-01",
            reference_date=date(2026, 3, 2),
        )
        assert result == date(2026, 3, 1)

    def test_no_last_generated(self):
        """When last_generated is None, generates from 1st of current month."""
        result = compute_next_due_date(
            "monthly",
            None,
            reference_date=date(2026, 3, 15),
        )
        # hledger generates from 1st of the month; monthly lands on Mar 1
        assert result == date(2026, 3, 1)

    def test_no_last_generated_daily(self):
        """Daily rule with no last_generated is immediately due."""
        result = compute_next_due_date(
            "daily",
            None,
            reference_date=date(2026, 3, 15),
        )
        # hledger generates daily from Mar 1; first date is Mar 1
        assert result == date(2026, 3, 1)

    def test_every_n_days(self):
        """Every 3 days rule."""
        result = compute_next_due_date(
            "every 3 days",
            "2026-03-01",
            reference_date=date(2026, 3, 5),
        )
        assert result == date(2026, 3, 4)

    def test_every_n_months(self):
        """Every 2 months rule."""
        result = compute_next_due_date(
            "every 2 months",
            "2026-01-15",
            reference_date=date(2026, 3, 20),
        )
        assert result == date(2026, 3, 15)

    def test_every_3rd_thursday(self):
        """Every 3rd thursday rule (complex hledger expression)."""
        result = compute_next_due_date(
            "every 3rd thursday",
            "2026-02-19",
            reference_date=date(2026, 3, 20),
        )
        assert result == date(2026, 3, 19)

    def test_every_friday(self):
        """Every friday rule."""
        result = compute_next_due_date(
            "every friday",
            "2026-02-27",
            reference_date=date(2026, 3, 10),
        )
        assert result == date(2026, 3, 6)


class TestComputeAllDueDates:
    """Tests for compute_all_due_dates."""

    def test_single_due(self):
        """One monthly occurrence due."""
        dates = compute_all_due_dates(
            "monthly",
            "2026-02-01",
            up_to=date(2026, 3, 2),
        )
        assert dates == [date(2026, 3, 1)]

    def test_multiple_due(self):
        """Multiple monthly occurrences when app was not opened."""
        dates = compute_all_due_dates(
            "monthly",
            "2025-12-01",
            up_to=date(2026, 3, 2),
        )
        assert dates == [
            date(2026, 1, 1),
            date(2026, 2, 1),
            date(2026, 3, 1),
        ]

    def test_none_due(self):
        """No occurrences due when recently generated."""
        dates = compute_all_due_dates(
            "monthly",
            "2026-03-01",
            up_to=date(2026, 3, 2),
        )
        assert dates == []

    def test_weekly_multiple(self):
        """Multiple weekly occurrences."""
        dates = compute_all_due_dates(
            "weekly",
            "2026-02-15",
            up_to=date(2026, 3, 2),
        )
        assert dates == [
            date(2026, 2, 22),
            date(2026, 3, 1),
        ]

    def test_no_last_generated(self):
        """No last_generated with monthly rule generates from 1st of month."""
        dates = compute_all_due_dates(
            "monthly",
            None,
            up_to=date(2026, 3, 2),
        )
        # hledger generates from 1st of the up_to month; monthly on Mar 1
        assert dates == [date(2026, 3, 1)]

    def test_every_3rd_thursday_multiple(self):
        """Multiple 3rd Thursday occurrences."""
        dates = compute_all_due_dates(
            "every 3rd thursday",
            "2026-02-19",
            up_to=date(2026, 4, 20),
        )
        assert dates == [
            date(2026, 3, 19),
            date(2026, 4, 16),
        ]

    def test_every_friday_multiple(self):
        """Multiple Friday occurrences."""
        dates = compute_all_due_dates(
            "every friday",
            "2026-02-27",
            up_to=date(2026, 3, 14),
        )
        assert dates == [
            date(2026, 3, 6),
            date(2026, 3, 13),
        ]


class TestFindPendingGenerations:
    """Tests for find_pending_generations."""

    def test_mix_pending_and_uptodate(self):
        """Finds rules with pending dates and skips up-to-date ones."""
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        rules = [
            RecurringRule(
                rule_id="r1",
                period_expr="monthly",
                description="Rule 1",
                postings=[
                    Posting(
                        account="Expenses:A",
                        amounts=[Amount(commodity="€", quantity=Decimal("100.00"), style=style)],
                    ),
                    Posting(account="Assets:Bank"),
                ],
                last_generated="2026-02-01",
            ),
            RecurringRule(
                rule_id="r2",
                period_expr="monthly",
                description="Rule 2",
                postings=[
                    Posting(
                        account="Expenses:B",
                        amounts=[Amount(commodity="€", quantity=Decimal("200.00"), style=style)],
                    ),
                    Posting(account="Assets:Bank"),
                ],
                last_generated="2026-03-01",
            ),
        ]
        pending = find_pending_generations(rules, up_to=date(2026, 3, 2))
        assert len(pending) == 1
        assert pending[0][0].rule_id == "r1"
        assert pending[0][1] == [date(2026, 3, 1)]

    def test_all_uptodate(self):
        """No pending when all rules are up to date."""
        rules = [
            RecurringRule(
                rule_id="r1",
                period_expr="monthly",
                description="Rule 1",
                last_generated="2026-03-01",
            ),
        ]
        pending = find_pending_generations(rules, up_to=date(2026, 3, 2))
        assert pending == []


class TestBuildTransactionFromRule:
    """Tests for build_transaction_from_rule."""

    def test_basic_build(self):
        """Build a transaction from a rule."""
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        rule = RecurringRule(
            rule_id="rent-001",
            period_expr="monthly",
            description="Rent payment",
            postings=[
                Posting(
                    account="Expenses:Rent",
                    amounts=[Amount(commodity="€", quantity=Decimal("800.00"), style=style)],
                ),
                Posting(account="Assets:Bank:Checking"),
            ],
            status=TransactionStatus.CLEARED,
        )
        txn = build_transaction_from_rule(rule, date(2026, 3, 1))

        assert txn.date == "2026-03-01"
        assert txn.description == "Rent payment"
        assert txn.status == TransactionStatus.CLEARED
        assert "recurring-id:rent-001" in txn.comment
        assert "recurring-date:2026-03-01" in txn.comment
        assert len(txn.postings) == 2
        assert txn.postings[0].account == "Expenses:Rent"
        assert txn.postings[0].amounts[0].quantity == Decimal("800.00")
        assert txn.postings[1].account == "Assets:Bank:Checking"
        assert txn.postings[1].amounts == []

    def test_with_user_comment(self):
        """Rule comment is preserved in generated transaction."""
        rule = RecurringRule(
            rule_id="test-001",
            period_expr="monthly",
            description="Test",
            comment="auto-pay",
        )
        txn = build_transaction_from_rule(rule, date(2026, 3, 1))
        assert "auto-pay" in txn.comment
        assert "recurring-id:test-001" in txn.comment
