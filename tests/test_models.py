"""Tests for data models."""

from decimal import Decimal

from hledger_textual.models import (
    Amount,
    AmountStyle,
    BudgetRow,
    PeriodSummary,
    Posting,
    Transaction,
    TransactionStatus,
)


class TestTransactionStatus:
    """Tests for TransactionStatus enum."""

    def test_cleared_symbol(self):
        assert TransactionStatus.CLEARED.symbol == "*"

    def test_pending_symbol(self):
        assert TransactionStatus.PENDING.symbol == "!"

    def test_unmarked_symbol(self):
        assert TransactionStatus.UNMARKED.symbol == ""

    def test_from_value(self):
        assert TransactionStatus("Cleared") == TransactionStatus.CLEARED
        assert TransactionStatus("Pending") == TransactionStatus.PENDING
        assert TransactionStatus("Unmarked") == TransactionStatus.UNMARKED


class TestAmount:
    """Tests for Amount formatting."""

    def test_format_left_commodity(self):
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        amt = Amount(commodity="€", quantity=Decimal("40.80"), style=style)
        assert amt.format() == "€40.80"

    def test_format_right_commodity(self):
        style = AmountStyle(commodity_side="R", commodity_spaced=True, precision=2)
        amt = Amount(commodity="EUR", quantity=Decimal("40.80"), style=style)
        assert amt.format() == "40.80 EUR"

    def test_format_negative(self):
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        amt = Amount(commodity="€", quantity=Decimal("-40.80"), style=style)
        assert amt.format() == "-€40.80"

    def test_format_zero_precision(self):
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=0)
        amt = Amount(commodity="$", quantity=Decimal("100"), style=style)
        assert amt.format() == "$100"

    def test_format_high_precision(self):
        style = AmountStyle(commodity_side="R", commodity_spaced=True, precision=4)
        amt = Amount(commodity="BTC", quantity=Decimal("0.0001"), style=style)
        assert amt.format() == "0.0001 BTC"

    def test_format_with_cost_annotation(self):
        """Amount with a cost annotates the output with @@ and the cost amount."""
        cost_style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        cost = Amount(commodity="€", quantity=Decimal("200.00"), style=cost_style)
        style = AmountStyle(commodity_side="R", commodity_spaced=True, precision=2)
        amt = Amount(commodity="STCK", quantity=Decimal("-10.00"), style=style, cost=cost)
        assert amt.format() == "-10.00 STCK @@ €200.00"

    def test_format_without_cost_unchanged(self):
        """Amount without cost produces the same output as before."""
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        amt = Amount(commodity="€", quantity=Decimal("100.00"), style=style)
        assert amt.format() == "€100.00"

    def test_format_negative_cost_normalised(self):
        """A negative cost quantity is always written as positive in the @@ annotation."""
        cost_style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        # Simulates what hledger JSON may produce for a sell transaction.
        cost = Amount(commodity="€", quantity=Decimal("-200.00"), style=cost_style)
        style = AmountStyle(commodity_side="R", commodity_spaced=True, precision=2)
        amt = Amount(commodity="STCK", quantity=Decimal("-10.00"), style=style, cost=cost)
        assert amt.format() == "-10.00 STCK @@ €200.00"

    def test_format_european_thousands(self):
        """European format: dot as thousands separator, comma as decimal mark."""
        style = AmountStyle(
            commodity_side="L",
            commodity_spaced=True,
            decimal_mark=",",
            digit_group_separator=".",
            digit_group_sizes=[3],
            precision=2,
        )
        amt = Amount(commodity="€", quantity=Decimal("1000.00"), style=style)
        assert amt.format() == "€ 1.000,00"

    def test_format_european_large_number(self):
        """European format applies grouping to numbers with multiple groups."""
        style = AmountStyle(
            commodity_side="L",
            commodity_spaced=True,
            decimal_mark=",",
            digit_group_separator=".",
            digit_group_sizes=[3],
            precision=2,
        )
        amt = Amount(commodity="€", quantity=Decimal("1000000.00"), style=style)
        assert amt.format() == "€ 1.000.000,00"

    def test_format_european_negative(self):
        """European format is preserved for negative amounts."""
        style = AmountStyle(
            commodity_side="L",
            commodity_spaced=True,
            decimal_mark=",",
            digit_group_separator=".",
            digit_group_sizes=[3],
            precision=2,
        )
        amt = Amount(commodity="€", quantity=Decimal("-1000.00"), style=style)
        assert amt.format() == "-€ 1.000,00"

    def test_format_us_thousands(self):
        """US format: comma as thousands separator, dot as decimal mark."""
        style = AmountStyle(
            commodity_side="L",
            commodity_spaced=False,
            decimal_mark=".",
            digit_group_separator=",",
            digit_group_sizes=[3],
            precision=2,
        )
        amt = Amount(commodity="$", quantity=Decimal("1000.00"), style=style)
        assert amt.format() == "$1,000.00"

    def test_format_zero_precision_with_grouping(self):
        """Digit grouping is applied even when precision is zero."""
        style = AmountStyle(
            commodity_side="L",
            commodity_spaced=True,
            decimal_mark=",",
            digit_group_separator=".",
            digit_group_sizes=[3],
            precision=0,
        )
        amt = Amount(commodity="€", quantity=Decimal("1000"), style=style)
        assert amt.format() == "€ 1.000"


class TestTransaction:
    """Tests for Transaction properties."""

    def test_total_amount_single_commodity(self, euro_style):
        txn = Transaction(
            index=1,
            date="2026-01-01",
            description="Test",
            postings=[
                Posting(
                    account="expenses:food",
                    amounts=[Amount(commodity="€", quantity=Decimal("40.80"), style=euro_style)],
                ),
                Posting(
                    account="assets:bank",
                    amounts=[Amount(commodity="€", quantity=Decimal("-40.80"), style=euro_style)],
                ),
            ],
        )
        assert txn.total_amount == "€40.80"

    def test_total_amount_no_positive(self, euro_style):
        txn = Transaction(
            index=1,
            date="2026-01-01",
            description="Test",
            postings=[
                Posting(
                    account="expenses:food",
                    amounts=[Amount(commodity="€", quantity=Decimal("-40.80"), style=euro_style)],
                ),
            ],
        )
        assert txn.total_amount == ""

    def test_total_amount_multiple_postings(self, euro_style):
        txn = Transaction(
            index=1,
            date="2026-01-01",
            description="Test",
            postings=[
                Posting(
                    account="expenses:office",
                    amounts=[Amount(commodity="€", quantity=Decimal("25.00"), style=euro_style)],
                ),
                Posting(
                    account="expenses:shipping",
                    amounts=[Amount(commodity="€", quantity=Decimal("10.00"), style=euro_style)],
                ),
                Posting(
                    account="assets:bank",
                    amounts=[Amount(commodity="€", quantity=Decimal("-35.00"), style=euro_style)],
                ),
            ],
        )
        assert txn.total_amount == "€35.00"


class TestFindStyle:
    """Tests for Transaction._find_style."""

    def test_finds_style_for_known_commodity(self):
        """Returns the AmountStyle for a commodity present in the postings."""
        custom_style = AmountStyle(commodity_side="R", commodity_spaced=True, precision=4)
        txn = Transaction(
            index=1,
            date="2026-01-01",
            description="Test",
            postings=[
                Posting(
                    account="expenses:food",
                    amounts=[Amount(commodity="BTC", quantity=Decimal("0.001"), style=custom_style)],
                ),
            ],
        )
        style = txn._find_style("BTC")
        assert style.commodity_side == "R"
        assert style.commodity_spaced is True
        assert style.precision == 4

    def test_returns_default_style_for_unknown_commodity(self):
        """Returns a default AmountStyle when the commodity is not found."""
        txn = Transaction(
            index=1,
            date="2026-01-01",
            description="Test",
            postings=[
                Posting(
                    account="expenses:food",
                    amounts=[Amount(commodity="€", quantity=Decimal("10.00"))],
                ),
            ],
        )
        style = txn._find_style("USD")
        assert style == AmountStyle()

    def test_returns_default_style_for_empty_postings(self):
        """Returns a default AmountStyle when there are no postings."""
        txn = Transaction(index=1, date="2026-01-01", description="Test")
        assert txn._find_style("€") == AmountStyle()


class TestBudgetRow:
    """Tests for BudgetRow properties."""

    def test_remaining_under_budget(self):
        row = BudgetRow(account="Expenses:Food", actual=Decimal("500"), budget=Decimal("800"), commodity="€")
        assert row.remaining == Decimal("300")

    def test_remaining_over_budget(self):
        row = BudgetRow(account="Expenses:Food", actual=Decimal("900"), budget=Decimal("800"), commodity="€")
        assert row.remaining == Decimal("-100")

    def test_usage_pct_normal(self):
        row = BudgetRow(account="Expenses:Food", actual=Decimal("400"), budget=Decimal("800"), commodity="€")
        assert row.usage_pct == 50.0

    def test_usage_pct_over(self):
        row = BudgetRow(account="Expenses:Food", actual=Decimal("1200"), budget=Decimal("800"), commodity="€")
        assert row.usage_pct == 150.0

    def test_usage_pct_zero_budget(self):
        row = BudgetRow(account="Expenses:Food", actual=Decimal("100"), budget=Decimal("0"), commodity="€")
        assert row.usage_pct == 0.0


class TestPeriodSummary:
    """Tests for PeriodSummary properties."""

    def test_net_without_investments(self):
        """Net equals income minus expenses when investments is zero."""
        summary = PeriodSummary(
            income=Decimal("3000"), expenses=Decimal("1000"), commodity="€"
        )
        assert summary.net == Decimal("2000")

    def test_net_with_investments(self):
        """Net deducts investments: income - expenses - investments."""
        summary = PeriodSummary(
            income=Decimal("3000"),
            expenses=Decimal("1000"),
            commodity="€",
            investments=Decimal("600"),
        )
        assert summary.net == Decimal("1400")

    def test_net_negative(self):
        """Net can be negative when expenses + investments exceed income."""
        summary = PeriodSummary(
            income=Decimal("1000"),
            expenses=Decimal("800"),
            commodity="€",
            investments=Decimal("500"),
        )
        assert summary.net == Decimal("-300")


class TestTotalAmountWithCost:
    """Tests for Transaction.total_amount when postings carry cost annotations."""

    def test_cost_is_included_in_total(self):
        """The EUR cost is included in total_amount alongside the commodity qty."""
        eur_style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        etf_style = AmountStyle(commodity_side="R", commodity_spaced=True, precision=0)
        cost_amount = Amount(commodity="€", quantity=Decimal("600"), style=eur_style)
        txn = Transaction(
            index=1,
            date="2026-01-15",
            description="Buy ETF",
            postings=[
                Posting(
                    account="assets:investments:XDWD",
                    amounts=[
                        Amount(
                            commodity="XDWD",
                            quantity=Decimal("5"),
                            style=etf_style,
                            cost=cost_amount,
                        )
                    ],
                ),
                Posting(
                    account="assets:bank",
                    amounts=[
                        Amount(
                            commodity="€",
                            quantity=Decimal("-600"),
                            style=eur_style,
                        )
                    ],
                ),
            ],
        )
        total = txn.total_amount
        # Should contain both the XDWD quantity and the EUR cost
        assert "XDWD" in total
        assert "€" in total

    def test_cost_aggregates_with_same_commodity(self):
        """When cost commodity matches existing amounts, quantities are summed."""
        eur_style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        etf_style = AmountStyle(commodity_side="R", commodity_spaced=True, precision=0)
        cost_amount = Amount(commodity="€", quantity=Decimal("600"), style=eur_style)
        txn = Transaction(
            index=1,
            date="2026-01-15",
            description="Buy ETF",
            postings=[
                Posting(
                    account="assets:investments:XDWD",
                    amounts=[
                        Amount(
                            commodity="XDWD",
                            quantity=Decimal("5"),
                            style=etf_style,
                            cost=cost_amount,
                        )
                    ],
                ),
                Posting(
                    account="expenses:fees",
                    amounts=[
                        Amount(
                            commodity="€",
                            quantity=Decimal("2.50"),
                            style=eur_style,
                        )
                    ],
                ),
                Posting(
                    account="assets:bank",
                    amounts=[
                        Amount(
                            commodity="€",
                            quantity=Decimal("-602.50"),
                            style=eur_style,
                        )
                    ],
                ),
            ],
        )
        total = txn.total_amount
        # €2.50 (fee) + €600 (cost) = €602.50
        assert "€602.50" in total
