"""Tests for the RecurringGenerateScreen modal."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from textual.app import App, ComposeResult
from textual.widgets import Static

from hledger_textual.models import (
    Amount,
    AmountStyle,
    Posting,
    RecurringRule,
    TransactionStatus,
)
from hledger_textual.screens.recurring_generate import RecurringGenerateScreen


def _make_rule(
    rule_id: str = "test-001",
    period: str = "monthly",
    description: str = "Test payment",
    amount: Decimal = Decimal("100.00"),
) -> RecurringRule:
    """Create a RecurringRule for testing."""
    style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
    return RecurringRule(
        rule_id=rule_id,
        period_expr=period,
        description=description,
        status=TransactionStatus.UNMARKED,
        postings=[
            Posting(
                account="expenses:rent",
                amounts=[Amount(commodity="€", quantity=amount, style=style)],
            ),
            Posting(account="assets:bank", amounts=[]),
        ],
    )


@pytest.fixture
def single_rule_pending() -> list[tuple[RecurringRule, list[date]]]:
    """A single rule with two pending dates."""
    rule = _make_rule()
    return [(rule, [date(2026, 2, 1), date(2026, 3, 1)])]


@pytest.fixture
def multi_rule_pending() -> list[tuple[RecurringRule, list[date]]]:
    """Multiple rules with varying pending dates."""
    rule_a = _make_rule(rule_id="a-001", description="Rent", amount=Decimal("800.00"))
    rule_b = _make_rule(
        rule_id="b-001",
        period="weekly",
        description="Groceries",
        amount=Decimal("50.00"),
    )
    return [
        (rule_a, [date(2026, 2, 1)]),
        (rule_b, [date(2026, 2, 3), date(2026, 2, 10), date(2026, 2, 17)]),
    ]


class TestRecurringGenerateScreen:
    """Tests for the RecurringGenerateScreen modal."""

    async def test_modal_shows_summary_count(
        self, single_rule_pending: list[tuple[RecurringRule, list[date]]]
    ):
        """The summary label shows the correct transaction count."""

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    RecurringGenerateScreen(single_rule_pending),
                    callback=lambda _: None,
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            summary = app.screen.query_one("#recurring-generate-summary")
            rendered = str(summary.renderable)
            assert "2 transactions" in rendered

    async def test_modal_populates_preview_table(
        self, single_rule_pending: list[tuple[RecurringRule, list[date]]]
    ):
        """The preview DataTable is populated with the correct number of rows."""
        from textual.widgets import DataTable

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    RecurringGenerateScreen(single_rule_pending),
                    callback=lambda _: None,
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#recurring-generate-table", DataTable)
            assert table.row_count == 2

    async def test_generate_button_dismisses_true(
        self, single_rule_pending: list[tuple[RecurringRule, list[date]]]
    ):
        """Clicking 'Generate All' dismisses the modal with True."""
        results: list[bool] = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    RecurringGenerateScreen(single_rule_pending),
                    callback=lambda r: results.append(r),
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            btn = app.screen.query_one("#btn-recurring-generate")
            await pilot.click(btn)
            await pilot.pause()
            assert results == [True]

    async def test_cancel_button_dismisses_false(
        self, single_rule_pending: list[tuple[RecurringRule, list[date]]]
    ):
        """Clicking 'Cancel' dismisses the modal with False."""
        results: list[bool] = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    RecurringGenerateScreen(single_rule_pending),
                    callback=lambda r: results.append(r),
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            btn = app.screen.query_one("#btn-recurring-gen-cancel")
            await pilot.click(btn)
            await pilot.pause()
            assert results == [False]

    async def test_escape_dismisses_false(
        self, single_rule_pending: list[tuple[RecurringRule, list[date]]]
    ):
        """Pressing Escape dismisses the modal with False."""
        results: list[bool] = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    RecurringGenerateScreen(single_rule_pending),
                    callback=lambda r: results.append(r),
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause(delay=0.5)
            assert results == [False]

    async def test_multiple_dates_multiple_rows(
        self, multi_rule_pending: list[tuple[RecurringRule, list[date]]]
    ):
        """Multiple rules with multiple dates produce the correct row count."""
        from textual.widgets import DataTable

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    RecurringGenerateScreen(multi_rule_pending),
                    callback=lambda _: None,
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#recurring-generate-table", DataTable)
            # 1 date for rule_a + 3 dates for rule_b = 4 rows
            assert table.row_count == 4
            summary = app.screen.query_one("#recurring-generate-summary")
            rendered = str(summary.renderable)
            assert "4 transactions" in rendered
