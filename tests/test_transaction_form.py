"""Tests for the transaction form modal."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.models import Amount, AmountStyle, Posting, TransactionStatus
from hledger_textual.screens.transaction_form import TransactionFormScreen
from hledger_textual.widgets.amount_input import AmountInput
from hledger_textual.widgets.date_input import DateInput
from hledger_textual.widgets.posting_row import PostingRow

from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")

# Dates within the current month so that the default "thismonth" filter works.
# Grocery shopping has the latest date so it is the first row (cursor position)
# after the reverse sort.
_D1 = date.today().replace(day=1)
_D2 = date.today().replace(day=2)
_D3 = date.today().replace(day=3)


@pytest.fixture
def app_journal(tmp_path: Path) -> Path:
    """A temporary journal with current-month dates for form testing."""
    content = (
        "; Test journal for form integration tests\n"
        "\n"
        f"{_D1.isoformat()} Salary\n"
        "    assets:bank:checking               €3000.00\n"
        "    income:salary\n"
        "\n"
        f"{_D2.isoformat()} ! Office supplies  ; for home office\n"
        "    expenses:office                      €25.00\n"
        "    expenses:shipping                    €10.00\n"
        "    assets:bank:checking\n"
        "\n"
        f"{_D3.isoformat()} * (INV-001) Grocery shopping  ; weekly groceries\n"
        "    expenses:food:groceries              €40.80\n"
        "    assets:bank:checking\n"
    )
    dest = tmp_path / "form_test.journal"
    dest.write_text(content)
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
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)

    async def test_edit_opens_form(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)

    async def test_new_form_has_today_date(self, app: HledgerTuiApp):
        from datetime import date
        from textual.widgets import Input

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            date_input = app.screen.query_one("#input-date", Input)
            assert date_input.value == date.today().isoformat()

    async def test_new_form_has_two_posting_rows(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            rows = app.screen.query(PostingRow)
            assert len(rows) == 2

    async def test_edit_form_prefills_data(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            form = app.screen
            assert form.query_one("#input-date", Input).value == _D3.isoformat()
            assert form.query_one("#input-description", Input).value == "Grocery shopping"
            assert form.query_one("#input-code", Input).value == "INV-001"

    async def test_edit_form_has_correct_posting_count(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            rows = app.screen.query(PostingRow)
            # Grocery shopping has 2 postings
            assert len(rows) == 2

    async def test_escape_cancels_form(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("2")
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
            await pilot.press("2")
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
            await pilot.press("2")
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
            await pilot.press("2")
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
            await pilot.press("2")
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
            await pilot.press("2")
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
            await pilot.press("2")
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
            await pilot.press("2")
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
            await pilot.press("2")
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
            await pilot.press("2")
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
            await pilot.press("2")
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
            await pilot.press("2")
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
            await pilot.press("2")
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


class TestDateInputFormat:
    """Tests for DateInput._format_date and _cursor_for_digit_pos."""

    def test_empty(self):
        assert DateInput._format_date("") == ""

    def test_partial_year(self):
        assert DateInput._format_date("20") == "20"

    def test_full_year(self):
        assert DateInput._format_date("2026") == "2026"

    def test_year_and_one_month_digit(self):
        assert DateInput._format_date("20260") == "2026-0"

    def test_year_and_full_month(self):
        assert DateInput._format_date("202601") == "2026-01"

    def test_year_month_and_one_day_digit(self):
        assert DateInput._format_date("2026011") == "2026-01-1"

    def test_full_date(self):
        assert DateInput._format_date("20260115") == "2026-01-15"

    def test_truncates_extra_digits(self):
        assert DateInput._format_date("202601159") == "2026-01-15"

    def test_cursor_within_year(self):
        assert DateInput._cursor_for_digit_pos(0) == 0
        assert DateInput._cursor_for_digit_pos(4) == 4

    def test_cursor_within_month(self):
        # digit_pos 5 → cursor 6 (after first dash)
        assert DateInput._cursor_for_digit_pos(5) == 6

    def test_cursor_within_day(self):
        # digit_pos 7 → cursor 9 (after both dashes)
        assert DateInput._cursor_for_digit_pos(7) == 9

    def test_cursor_at_end(self):
        # digit_pos 8 → cursor 10 (end of YYYY-MM-DD)
        assert DateInput._cursor_for_digit_pos(8) == 10


class TestOmitBalancingAmount:
    """Tests for TransactionFormScreen._omit_balancing_amount."""

    @pytest.fixture
    def style(self):
        return AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)

    def test_clears_last_posting_when_balanced(self, style):
        postings = [
            Posting(
                account="expenses:food",
                amounts=[Amount(commodity="EUR", quantity=Decimal("50.00"), style=style)],
            ),
            Posting(
                account="assets:bank",
                amounts=[Amount(commodity="EUR", quantity=Decimal("-50.00"), style=style)],
            ),
        ]
        result = TransactionFormScreen._omit_balancing_amount(postings)
        assert len(result) == 2
        assert result[0].amounts[0].quantity == Decimal("50.00")
        assert result[1].amounts == []

    def test_preserves_amounts_when_unbalanced(self, style):
        postings = [
            Posting(
                account="expenses:food",
                amounts=[Amount(commodity="EUR", quantity=Decimal("50.00"), style=style)],
            ),
            Posting(
                account="assets:bank",
                amounts=[Amount(commodity="EUR", quantity=Decimal("-30.00"), style=style)],
            ),
        ]
        result = TransactionFormScreen._omit_balancing_amount(postings)
        assert len(result[1].amounts) == 1
        assert result[1].amounts[0].quantity == Decimal("-30.00")

    def test_preserves_amounts_with_mixed_commodities(self, style):
        postings = [
            Posting(
                account="expenses:food",
                amounts=[Amount(commodity="EUR", quantity=Decimal("50.00"), style=style)],
            ),
            Posting(
                account="assets:bank",
                amounts=[Amount(commodity="USD", quantity=Decimal("-50.00"), style=style)],
            ),
        ]
        result = TransactionFormScreen._omit_balancing_amount(postings)
        assert len(result[1].amounts) == 1

    def test_preserves_when_posting_has_no_amount(self, style):
        postings = [
            Posting(
                account="expenses:food",
                amounts=[Amount(commodity="EUR", quantity=Decimal("50.00"), style=style)],
            ),
            Posting(account="assets:bank", amounts=[]),
        ]
        result = TransactionFormScreen._omit_balancing_amount(postings)
        # Not all postings have exactly 1 amount, so no change
        assert result[1].amounts == []

    def test_preserves_with_single_posting(self, style):
        postings = [
            Posting(
                account="expenses:food",
                amounts=[Amount(commodity="EUR", quantity=Decimal("50.00"), style=style)],
            ),
        ]
        result = TransactionFormScreen._omit_balancing_amount(postings)
        assert len(result[0].amounts) == 1

    def test_three_postings_balanced(self, style):
        postings = [
            Posting(
                account="expenses:food",
                amounts=[Amount(commodity="EUR", quantity=Decimal("30.00"), style=style)],
            ),
            Posting(
                account="expenses:drink",
                amounts=[Amount(commodity="EUR", quantity=Decimal("20.00"), style=style)],
            ),
            Posting(
                account="assets:bank",
                amounts=[Amount(commodity="EUR", quantity=Decimal("-50.00"), style=style)],
            ),
        ]
        result = TransactionFormScreen._omit_balancing_amount(postings)
        assert result[0].amounts[0].quantity == Decimal("30.00")
        assert result[1].amounts[0].quantity == Decimal("20.00")
        assert result[2].amounts == []


class TestDescriptionAutocomplete:
    """Tests for description autocomplete in the form."""

    async def test_description_uses_autocomplete_input(self, app: HledgerTuiApp):
        from hledger_textual.widgets.autocomplete_input import AutocompleteInput

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            desc_input = form.query_one("#input-description")
            assert isinstance(desc_input, AutocompleteInput)

    async def test_description_has_suggester(self, app: HledgerTuiApp):
        from hledger_textual.widgets.autocomplete_input import AutocompleteInput

        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            desc_input = form.query_one("#input-description", AutocompleteInput)
            assert desc_input.suggester is not None

    async def test_date_uses_date_input(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            date_input = form.query_one("#input-date")
            assert isinstance(date_input, DateInput)


class TestAmountInputFormat:
    """Tests for AmountInput._format_amount static method."""

    def test_empty(self):
        assert AmountInput._format_amount("") == ""

    def test_integer(self):
        assert AmountInput._format_amount("49") == "49.00"

    def test_one_decimal(self):
        assert AmountInput._format_amount("2.5") == "2.50"

    def test_two_decimals(self):
        assert AmountInput._format_amount("12.34") == "12.34"

    def test_three_decimals_rounds(self):
        assert AmountInput._format_amount("1.999") == "2.00"

    def test_negative(self):
        assert AmountInput._format_amount("-49") == "-49.00"

    def test_negative_decimal(self):
        assert AmountInput._format_amount("-3.5") == "-3.50"

    def test_leading_dot(self):
        assert AmountInput._format_amount(".5") == "0.50"

    def test_zero(self):
        assert AmountInput._format_amount("0") == "0.00"

    def test_whitespace_only(self):
        assert AmountInput._format_amount("   ") == ""

    def test_invalid_returns_original(self):
        assert AmountInput._format_amount("abc") == "abc"


class TestAmountInputWidget:
    """Integration tests for AmountInput in the posting row."""

    async def test_amount_uses_amount_input(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            rows = list(form.query(PostingRow))
            amount_widget = rows[0].query_one("#amount-0")
            assert isinstance(amount_widget, AmountInput)


class TestDefaultCommodity:
    """Tests for default commodity pre-fill in new transaction form."""

    async def test_new_form_prefills_commodity_from_config(
        self, app: HledgerTuiApp, monkeypatch
    ):
        """New transaction form pre-fills the commodity field with the configured default."""
        from textual.widgets import Input

        monkeypatch.setattr(
            "hledger_textual.screens.transaction_form.load_default_commodity",
            lambda: "\u20ac",
        )
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            rows = list(form.query(PostingRow))
            commodity_val = rows[0].query_one("#commodity-0", Input).value
            assert commodity_val == "\u20ac"
