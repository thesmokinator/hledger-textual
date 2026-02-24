"""Tests for the transaction form modal."""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from hledger_tui.app import HledgerTuiApp
from hledger_tui.models import (
    Amount,
    AmountStyle,
    Posting,
    Transaction,
    TransactionStatus,
)
from hledger_tui.screens.transaction_form import TransactionFormScreen
from hledger_tui.widgets.posting_row import PostingRow

from tests.conftest import FIXTURES_DIR, has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


@pytest.fixture
def app_journal(tmp_path: Path) -> Path:
    """A temporary journal for form testing."""
    dest = tmp_path / "form_test.journal"
    shutil.copy2(FIXTURES_DIR / "sample.journal", dest)
    return dest


@pytest.fixture
def app(app_journal: Path) -> HledgerTuiApp:
    """Create an app instance."""
    return HledgerTuiApp(journal_file=app_journal)


class TestFormOpens:
    """Tests for opening the form."""

    async def test_add_opens_form(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)

    async def test_edit_opens_form(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)

    async def test_new_form_has_today_date(self, app: HledgerTuiApp):
        from datetime import date
        from textual.widgets import Input

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            date_input = app.screen.query_one("#input-date", Input)
            assert date_input.value == date.today().isoformat()

    async def test_new_form_has_two_posting_rows(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            rows = app.screen.query(PostingRow)
            assert len(rows) == 2

    async def test_edit_form_prefills_data(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            form = app.screen
            assert form.query_one("#input-date", Input).value == "2026-01-15"
            assert form.query_one("#input-description", Input).value == "Grocery shopping"
            assert form.query_one("#input-code", Input).value == "INV-001"

    async def test_edit_form_has_correct_posting_count(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            rows = app.screen.query(PostingRow)
            # Grocery shopping has 2 postings
            assert len(rows) == 2

    async def test_escape_cancels_form(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, TransactionFormScreen)


class TestFormValidation:
    """Tests for form validation logic."""

    async def test_empty_description_rejected(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            # Leave description empty, try to save
            form.query_one("#input-description", Input).value = ""
            form._save()
            await pilot.pause()
            # Form should still be open
            assert isinstance(app.screen, TransactionFormScreen)

    async def test_invalid_date_rejected(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            form.query_one("#input-date", Input).value = "not-a-date"
            form.query_one("#input-description", Input).value = "Test"
            form._save()
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)

    async def test_invalid_date_format_rejected(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            # Valid looking but impossible date
            form.query_one("#input-date", Input).value = "2026-02-30"
            form.query_one("#input-description", Input).value = "Test"
            form._save()
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)

    async def test_date_wrong_separator_rejected(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            form.query_one("#input-date", Input).value = "2026/01/15"
            form.query_one("#input-description", Input).value = "Test"
            form._save()
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)

    async def test_empty_date_rejected(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            form.query_one("#input-date", Input).value = ""
            form.query_one("#input-description", Input).value = "Test"
            form._save()
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)

    async def test_less_than_two_postings_rejected(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            form.query_one("#input-description", Input).value = "Test"
            # Leave both posting accounts empty
            form._save()
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)

    async def test_invalid_amount_rejected(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            form.query_one("#input-description", Input).value = "Test"
            # Fill postings with invalid amount
            rows = list(form.query(PostingRow))
            rows[0].query_one(f"#account-0", Input).value = "expenses:food"
            rows[0].query_one(f"#amount-0", Input).value = "abc"
            rows[1].query_one(f"#account-1", Input).value = "assets:bank"
            form._save()
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)


class TestFormPostings:
    """Tests for posting row management."""

    async def test_add_posting_row(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            assert len(form.query(PostingRow)) == 2

            btn = form.query_one("#btn-add-posting")
            await pilot.click(btn)
            await pilot.pause()
            assert len(form.query(PostingRow)) == 3

    async def test_remove_posting_row(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen

            # Add a third row first
            form._add_posting_row()
            await pilot.pause()
            assert len(form.query(PostingRow)) == 3

            # Now remove it
            form._remove_last_posting_row()
            await pilot.pause()
            await pilot.pause()
            assert len(form.query(PostingRow)) == 2

    async def test_cannot_remove_below_two(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            assert len(form.query(PostingRow)) == 2

            rm_btn = form.query_one("#btn-remove-posting")
            await pilot.click(rm_btn)
            await pilot.pause()
            # Should still have 2 rows (minimum)
            assert len(form.query(PostingRow)) == 2


class TestFormSave:
    """Tests for valid form submission."""

    async def test_valid_form_dismisses(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen

            form.query_one("#input-description", Input).value = "Test transaction"

            rows = list(form.query(PostingRow))
            rows[0].query_one("#account-0", Input).value = "expenses:food"
            rows[0].query_one("#amount-0", Input).value = "50.00"
            rows[1].query_one("#account-1", Input).value = "assets:bank:checking"

            form._save()
            await pilot.pause(delay=1.0)
            # Form should have dismissed
            assert not isinstance(app.screen, TransactionFormScreen)

    async def test_valid_form_with_all_fields(self, app: HledgerTuiApp):
        from textual.widgets import Input, Select

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen

            form.query_one("#input-date", Input).value = "2026-03-01"
            form.query_one("#input-description", Input).value = "Full test"
            form.query_one("#select-status", Select).value = TransactionStatus.CLEARED
            form.query_one("#input-code", Input).value = "TEST-01"
            form.query_one("#input-comment", Input).value = "a comment"

            rows = list(form.query(PostingRow))
            rows[0].query_one("#account-0", Input).value = "expenses:food"
            rows[0].query_one("#amount-0", Input).value = "25.00"
            rows[0].query_one("#commodity-0", Input).value = "EUR"
            rows[1].query_one("#account-1", Input).value = "assets:bank:checking"

            form._save()
            await pilot.pause(delay=1.0)
            assert not isinstance(app.screen, TransactionFormScreen)


class TestDateValidation:
    """Tests for the _validate_date method directly."""

    def test_valid_date(self):
        form = TransactionFormScreen.__new__(TransactionFormScreen)
        assert form._validate_date("2026-01-15") is True

    def test_valid_leap_year(self):
        form = TransactionFormScreen.__new__(TransactionFormScreen)
        assert form._validate_date("2024-02-29") is True

    def test_invalid_leap_year(self):
        form = TransactionFormScreen.__new__(TransactionFormScreen)
        assert form._validate_date("2026-02-29") is False

    def test_invalid_format(self):
        form = TransactionFormScreen.__new__(TransactionFormScreen)
        assert form._validate_date("not-a-date") is False

    def test_slash_separator(self):
        form = TransactionFormScreen.__new__(TransactionFormScreen)
        assert form._validate_date("2026/01/15") is False

    def test_empty_string(self):
        form = TransactionFormScreen.__new__(TransactionFormScreen)
        assert form._validate_date("") is False

    def test_impossible_month(self):
        form = TransactionFormScreen.__new__(TransactionFormScreen)
        assert form._validate_date("2026-13-01") is False

    def test_impossible_day(self):
        form = TransactionFormScreen.__new__(TransactionFormScreen)
        assert form._validate_date("2026-01-32") is False
