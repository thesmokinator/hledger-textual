"""Tests for the PostingRow widget."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Input

from hledger_textual.widgets.autocomplete_input import AutocompleteInput
from hledger_textual.widgets.posting_row import PostingRow


class PostingRowApp(App):
    """Minimal app to test PostingRow."""

    CSS = "PostingRow { height: auto; }"

    def compose(self) -> ComposeResult:
        with Vertical():
            yield PostingRow(
                label="Debit:",
                account="expenses:food",
                amount="50.00",
                commodity="€",
                row_index=0,
                account_suggestions=["expenses:food:groceries", "assets:bank:checking"],
            )
            yield PostingRow(
                label="Credit:",
                row_index=1,
            )


class TestPostingRow:
    """Tests for PostingRow widget."""

    async def test_renders_with_initial_values(self):
        app = PostingRowApp()
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            rows = list(app.query(PostingRow))
            assert len(rows) == 2
            assert rows[0].account == "expenses:food"
            assert rows[0].amount == "50.00"
            assert rows[0].commodity == "€"

    async def test_empty_row_returns_empty_strings(self):
        app = PostingRowApp()
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            rows = list(app.query(PostingRow))
            assert rows[1].account == ""
            assert rows[1].amount == ""
            assert rows[1].commodity == ""

    async def test_account_input_is_autocomplete(self):
        app = PostingRowApp()
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            row = app.query(PostingRow).first()
            account_input = row.query_one("#account-0")
            assert isinstance(account_input, AutocompleteInput)

    async def test_account_input_has_suggester(self):
        app = PostingRowApp()
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            row = app.query(PostingRow).first()
            account_input = row.query_one("#account-0", AutocompleteInput)
            assert account_input.suggester is not None

    async def test_row_without_suggestions(self):
        app = PostingRowApp()
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            rows = list(app.query(PostingRow))
            # Second row has no suggestions
            account_input = rows[1].query_one("#account-1", AutocompleteInput)
            assert account_input.suggester is None

    async def test_modify_account_value(self):
        app = PostingRowApp()
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            row = app.query(PostingRow).first()
            row.query_one("#account-0", Input).value = "expenses:office"
            await pilot.pause()
            assert row.account == "expenses:office"

    async def test_modify_amount_value(self):
        app = PostingRowApp()
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            row = app.query(PostingRow).first()
            row.query_one("#amount-0", Input).value = "99.99"
            await pilot.pause()
            assert row.amount == "99.99"
