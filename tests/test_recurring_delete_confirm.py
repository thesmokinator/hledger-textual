"""Tests for the RecurringDeleteConfirmModal."""

from __future__ import annotations

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
from hledger_textual.screens.recurring_delete_confirm import RecurringDeleteConfirmModal


@pytest.fixture
def recurring_rule() -> RecurringRule:
    """A recurring rule for delete modal testing."""
    style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
    return RecurringRule(
        rule_id="rent-001",
        period_expr="monthly",
        description="Rent payment",
        status=TransactionStatus.UNMARKED,
        postings=[
            Posting(
                account="expenses:rent",
                amounts=[Amount(commodity="€", quantity=Decimal("800.00"), style=style)],
            ),
            Posting(account="assets:bank", amounts=[]),
        ],
    )


class TestRecurringDeleteConfirmModal:
    """Tests for the RecurringDeleteConfirmModal."""

    async def test_modal_shows_rule_summary(self, recurring_rule: RecurringRule):
        """The modal displays the rule's period and description."""

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    RecurringDeleteConfirmModal(recurring_rule),
                    callback=lambda _: None,
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            summary = app.screen.query_one("#recurring-delete-summary")
            rendered = str(summary.renderable)
            assert "monthly" in rendered
            assert "Rent payment" in rendered

    async def test_delete_button_dismisses_true(self, recurring_rule: RecurringRule):
        """Clicking 'Delete' dismisses with True."""
        results: list[bool] = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    RecurringDeleteConfirmModal(recurring_rule),
                    callback=lambda r: results.append(r),
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            btn = app.screen.query_one("#btn-recurring-delete")
            await pilot.click(btn)
            await pilot.pause()
            assert results == [True]

    async def test_cancel_button_dismisses_false(self, recurring_rule: RecurringRule):
        """Clicking 'Cancel' dismisses with False."""
        results: list[bool] = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    RecurringDeleteConfirmModal(recurring_rule),
                    callback=lambda r: results.append(r),
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            btn = app.screen.query_one("#btn-recurring-delete-cancel")
            await pilot.click(btn)
            await pilot.pause()
            assert results == [False]

    async def test_escape_dismisses_false(self, recurring_rule: RecurringRule):
        """Pressing Escape dismisses with False."""
        results: list[bool] = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    RecurringDeleteConfirmModal(recurring_rule),
                    callback=lambda r: results.append(r),
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause(delay=0.5)
            assert results == [False]
