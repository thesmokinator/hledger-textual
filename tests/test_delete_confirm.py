"""Tests for the delete confirmation modal."""

from __future__ import annotations

from decimal import Decimal

import pytest

from hledger_tui.models import Amount, AmountStyle, Posting, Transaction, TransactionStatus
from hledger_tui.screens.delete_confirm import DeleteConfirmModal


@pytest.fixture
def modal_transaction() -> Transaction:
    """A transaction for delete modal testing."""
    style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
    return Transaction(
        index=1,
        date="2026-01-15",
        description="Test purchase",
        status=TransactionStatus.CLEARED,
        postings=[
            Posting(
                account="expenses:food",
                amounts=[Amount(commodity="€", quantity=Decimal("40.80"), style=style)],
            ),
            Posting(
                account="assets:bank",
                amounts=[Amount(commodity="€", quantity=Decimal("-40.80"), style=style)],
            ),
        ],
    )


class TestDeleteConfirmModal:
    """Tests for the DeleteConfirmModal."""

    async def test_modal_shows_transaction_summary(self, modal_transaction: Transaction):
        """Modal displays the transaction description and accounts."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    DeleteConfirmModal(modal_transaction),
                    callback=lambda _: None,
                )

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            summary = app.screen.query_one("#delete-summary")
            rendered = str(summary.renderable)
            assert "Test purchase" in rendered
            assert "expenses:food" in rendered

    async def test_delete_button_dismisses_true(self, modal_transaction: Transaction):
        """Clicking Delete button dismisses with True."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        results = []

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    DeleteConfirmModal(modal_transaction),
                    callback=lambda r: results.append(r),
                )

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            delete_btn = app.screen.query_one("#btn-delete")
            await pilot.click(delete_btn)
            await pilot.pause()
            assert results == [True]

    async def test_cancel_button_dismisses_false(self, modal_transaction: Transaction):
        """Clicking Cancel button dismisses with False."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        results = []

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    DeleteConfirmModal(modal_transaction),
                    callback=lambda r: results.append(r),
                )

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cancel_btn = app.screen.query_one("#btn-cancel")
            await pilot.click(cancel_btn)
            await pilot.pause()
            assert results == [False]

    async def test_escape_dismisses_false(self, modal_transaction: Transaction):
        """Pressing Escape dismisses with False."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        results = []

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    DeleteConfirmModal(modal_transaction),
                    callback=lambda r: results.append(r),
                )

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert results == [False]
