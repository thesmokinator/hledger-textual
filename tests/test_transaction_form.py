"""Tests for the transaction form modal."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.models import Amount, AmountStyle, Posting, TransactionStatus
from hledger_textual.screens.transaction_form import (
    TransactionFormScreen,
    _build_commodity_data,
    _extract_commodity_and_qty,
    parse_amount_str,
)
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
        async with app.run_test(size=(100, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)

    async def test_edit_opens_form(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)

    async def test_new_form_has_today_date(self, app: HledgerTuiApp):
        from datetime import date
        from textual.widgets import Input

        async with app.run_test(size=(100, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            date_input = app.screen.query_one("#input-date", Input)
            assert date_input.value == date.today().isoformat()

    async def test_new_form_has_two_posting_rows(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            rows = app.screen.query(PostingRow)
            assert len(rows) == 2

    async def test_edit_form_prefills_data(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 60)) as pilot:
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
        async with app.run_test(size=(100, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            rows = app.screen.query(PostingRow)
            # Grocery shopping has 2 postings
            assert len(rows) == 2

    async def test_escape_cancels_form(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 60)) as pilot:
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

    async def test_invalid_date_rejected(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 60)) as pilot:
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

        async with app.run_test(size=(100, 60)) as pilot:
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

        async with app.run_test(size=(100, 60)) as pilot:
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

        async with app.run_test(size=(100, 60)) as pilot:
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

    async def test_invalid_amount_rejected(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            form.query_one("#input-description", Input).value = "Test"
            # Fill postings with invalid amount
            rows = list(form.query(PostingRow))
            rows[0].query_one("#account-0", Input).value = "expenses:food"
            rows[0].query_one("#amount-0", Input).value = "abc"
            rows[1].query_one("#account-1", Input).value = "assets:bank"
            form._save()
            await pilot.pause()
            assert isinstance(app.screen, TransactionFormScreen)


class TestFormPostings:
    """Tests for posting row management."""

    async def test_add_posting_row(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 60)) as pilot:
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
        async with app.run_test(size=(100, 60)) as pilot:
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

    async def test_can_remove_below_two(self, app: HledgerTuiApp):
        """Posting rows can be removed below two (hledger accepts 0+ postings)."""
        async with app.run_test(size=(100, 60)) as pilot:
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
            assert len(form.query(PostingRow)) == 1


class TestFormSave:
    """Tests for valid form submission."""

    async def test_valid_form_dismisses(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 60)) as pilot:
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

        async with app.run_test(size=(100, 60)) as pilot:
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
            # commodity is now a read-only label; the amount embeds the currency instead
            rows[1].query_one("#account-1", Input).value = "assets:bank:checking"

            form._save()
            await pilot.pause(delay=1.0)
            assert not isinstance(app.screen, TransactionFormScreen)


class TestBalanceValidation:
    """Tests for pre-save balance validation."""

    async def test_unbalanced_same_commodity_is_rejected(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen

            form.query_one("#input-description", Input).value = "Unbalanced test"
            rows = list(form.query(PostingRow))
            rows[0].query_one("#account-0", Input).value = "assets:bank"
            rows[0].query_one("#amount-0", Input).value = "100.00"
            rows[1].query_one("#account-1", Input).value = "expenses:food"
            rows[1].query_one("#amount-1", Input).value = "100.00"

            form._save()
            await pilot.pause()
            # Form must NOT have dismissed — still showing the form
            assert isinstance(app.screen, TransactionFormScreen)

    async def test_balanced_same_commodity_is_accepted(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen

            form.query_one("#input-description", Input).value = "Balanced test"
            rows = list(form.query(PostingRow))
            rows[0].query_one("#account-0", Input).value = "expenses:food"
            rows[0].query_one("#amount-0", Input).value = "100.00"
            rows[1].query_one("#account-1", Input).value = "assets:bank"
            rows[1].query_one("#amount-1", Input).value = "-100.00"

            form._save()
            await pilot.pause(delay=1.0)
            # Form should dismiss when balanced
            assert not isinstance(app.screen, TransactionFormScreen)

    async def test_auto_balance_one_blank_is_accepted(self, app: HledgerTuiApp):
        from textual.widgets import Input

        async with app.run_test(size=(100, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen

            form.query_one("#input-description", Input).value = "Auto balance test"
            rows = list(form.query(PostingRow))
            rows[0].query_one("#account-0", Input).value = "expenses:food"
            rows[0].query_one("#amount-0", Input).value = "100.00"
            rows[1].query_one("#account-1", Input).value = "assets:bank"
            # Leave amount-1 blank → hledger auto-balances

            form._save()
            await pilot.pause(delay=1.0)
            assert not isinstance(app.screen, TransactionFormScreen)


class TestEuropeanStylePreservation:
    """Regression tests for issue #111.

    Editing a European-formatted transaction through the form — even when only
    the status (or another non-amount field) is touched — must not scale the
    amount by 100×.  The bug was that the form re-parsed the amount string
    through ``parse_amount_str``, which produced a default US-style
    ``AmountStyle`` and caused hledger to re-interpret the rewritten amount
    against the journal's ``commodity € 1.000,00`` directive.
    """

    @pytest.fixture
    def european_journal(self, tmp_path: Path) -> Path:
        content = (
            "commodity € 1.000,00\n"
            "\n"
            f"{_D3.isoformat()} ! café\n"
            "    expenses:food          € 10,00\n"
            "    assets:bank:checking  -€ 10,00\n"
        )
        dest = tmp_path / "european.journal"
        dest.write_text(content)
        return dest

    @pytest.fixture
    def european_app(self, european_journal: Path) -> HledgerTuiApp:
        return HledgerTuiApp(journal_file=european_journal)

    async def test_status_edit_preserves_european_amount(
        self, european_app: HledgerTuiApp, european_journal: Path
    ):
        from textual.widgets import Select

        from hledger_textual.hledger import load_transactions

        async with european_app.run_test(size=(100, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            form = european_app.screen
            assert isinstance(form, TransactionFormScreen)

            # Change only the status — leave the amount field untouched.
            form.query_one("#select-status", Select).value = TransactionStatus.CLEARED
            form._save()
            await pilot.pause(delay=1.5)
            assert not isinstance(european_app.screen, TransactionFormScreen)

        reloaded = load_transactions(european_journal)
        cafe = next(t for t in reloaded if t.description == "café")
        assert cafe.status == TransactionStatus.CLEARED
        # The bug scaled the amount from 10 to 1000 (100×).
        assert cafe.postings[0].amounts[0].quantity == Decimal("10")
        assert cafe.postings[1].amounts[0].quantity == Decimal("-10")
        # The rewritten file must retain European formatting, not fall back
        # to the US-style "€10.00" which hledger would misread as 1000.
        file_text = european_journal.read_text()
        assert "€ 10,00" in file_text
        assert "€10.00" not in file_text


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

        async with app.run_test(size=(100, 60)) as pilot:
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

        async with app.run_test(size=(100, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            desc_input = form.query_one("#input-description", AutocompleteInput)
            assert desc_input.suggester is not None

    async def test_date_uses_date_input(self, app: HledgerTuiApp):
        async with app.run_test(size=(100, 60)) as pilot:
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
        async with app.run_test(size=(100, 60)) as pilot:
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
        """New transaction form shows the configured default commodity in the hint."""
        from textual.widgets import Static

        monkeypatch.setattr(
            "hledger_textual.screens.transaction_form.load_default_commodity",
            lambda: "\u20ac",
        )
        async with app.run_test(size=(100, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            hint = form.query_one("#default-commodity-hint", Static)
            assert "\u20ac" in hint.renderable


class TestParseAmountStr:
    """Unit tests for the parse_amount_str helper."""

    def test_simple_integer(self):
        amt = parse_amount_str("100", "€")
        assert amt is not None
        assert amt.quantity == Decimal("100")
        assert amt.commodity == "€"

    def test_simple_decimal(self):
        amt = parse_amount_str("50.00", "€")
        assert amt is not None
        assert amt.quantity == Decimal("50.00")
        assert amt.commodity == "€"

    def test_negative_simple(self):
        amt = parse_amount_str("-50.00", "€")
        assert amt is not None
        assert amt.quantity == Decimal("-50.00")

    def test_currency_prefix(self):
        """Currency-prefixed amount is parsed as left-side commodity."""
        amt = parse_amount_str("€50.00", "€")
        assert amt is not None
        assert amt.commodity == "€"
        assert amt.quantity == Decimal("50.00")
        assert amt.style.commodity_side == "L"

    def test_negative_currency_prefix(self):
        amt = parse_amount_str("-€50.00", "€")
        assert amt is not None
        assert amt.quantity == Decimal("-50.00")
        assert amt.commodity == "€"

    def test_qty_commodity(self):
        """Quantity followed by commodity name is parsed as right-side commodity."""
        amt = parse_amount_str("-10.00 STCK", "€")
        assert amt is not None
        assert amt.quantity == Decimal("-10.00")
        assert amt.commodity == "STCK"
        assert amt.style.commodity_side == "R"
        assert amt.cost is None

    def test_total_cost_annotation(self):
        """@@ annotation stores the total cost directly."""
        amt = parse_amount_str("-10 STCK @@ €200.00", "€")
        assert amt is not None
        assert amt.quantity == Decimal("-10")
        assert amt.commodity == "STCK"
        assert amt.cost is not None
        assert amt.cost.commodity == "€"
        assert amt.cost.quantity == Decimal("200.00")

    def test_unit_cost_annotation_converted_to_total(self):
        """@ annotation multiplies unit price by quantity to get total cost."""
        amt = parse_amount_str("-10 STCK @ €20.00", "€")
        assert amt is not None
        assert amt.commodity == "STCK"
        assert amt.cost is not None
        assert amt.cost.commodity == "€"
        # 10 * 20.00 = 200.00
        assert amt.cost.quantity == Decimal("200.00")

    def test_invalid_returns_none(self):
        assert parse_amount_str("abc", "€") is None

    def test_empty_returns_none(self):
        assert parse_amount_str("", "€") is None

    def test_invalid_cost_returns_none(self):
        assert parse_amount_str("-10 STCK @@ invalid", "€") is None

    def test_roundtrip_format(self):
        """Amount parsed from a complex string round-trips through format()."""
        amt = parse_amount_str("-10.00 STCK @@ €200.00", "€")
        assert amt is not None
        assert amt.format() == "-10.00 STCK @@ €200.00"

    def test_negative_total_cost_normalised_to_positive(self):
        """A negative @@ cost string is normalised to a positive cost quantity."""
        amt = parse_amount_str("-10 STCK @@ -€200.00", "€")
        assert amt is not None
        assert amt.cost is not None
        assert amt.cost.quantity == Decimal("200.00")
        # format() must produce a valid hledger string (positive cost)
        assert amt.format() == "-10 STCK @@ €200.00"


class TestExtractCommodityAndQty:
    """Unit tests for _extract_commodity_and_qty."""

    def test_plain_number_returns_none(self):
        assert _extract_commodity_and_qty("50.00") is None

    def test_currency_prefix_returns_none(self):
        assert _extract_commodity_and_qty("€742.55") is None

    def test_negative_currency_prefix_returns_none(self):
        assert _extract_commodity_and_qty("-€742.55") is None

    def test_named_commodity_negative(self):
        result = _extract_commodity_and_qty("-5 XEON")
        assert result == (Decimal("-5"), "XEON", None)

    def test_named_commodity_with_total_cost(self):
        result = _extract_commodity_and_qty("-5 XEON @@ €200")
        assert result is not None
        qty, commodity, proceeds = result
        assert qty == Decimal("-5")
        assert commodity == "XEON"
        assert proceeds == Decimal("200")

    def test_named_commodity_with_total_cost_partial(self):
        """Incomplete cost annotation still extracts commodity without proceeds."""
        result = _extract_commodity_and_qty("-5 XEON @@ €7")
        assert result is not None
        qty, commodity, proceeds = result
        assert qty == Decimal("-5")
        assert commodity == "XEON"
        assert proceeds == Decimal("7")

    def test_named_commodity_positive(self):
        result = _extract_commodity_and_qty("10 STCK")
        assert result == (Decimal("10"), "STCK", None)

    def test_named_commodity_with_decimal(self):
        result = _extract_commodity_and_qty("-5.50 ETF")
        assert result is not None
        qty, commodity, proceeds = result
        assert qty == Decimal("-5.50")
        assert commodity == "ETF"
        assert proceeds is None

    def test_empty_returns_none(self):
        assert _extract_commodity_and_qty("") is None

    def test_named_commodity_with_unit_cost(self):
        """@ unit cost is converted to total proceeds (qty × unit_price)."""
        result = _extract_commodity_and_qty("-5 XEON @ €148.51")
        assert result is not None
        qty, commodity, proceeds = result
        assert qty == Decimal("-5")
        assert commodity == "XEON"
        assert proceeds == Decimal("742.55")

    def test_buy_has_no_gain_proceeds(self):
        """Positive qty (buy) still returns proceeds when annotation is present."""
        result = _extract_commodity_and_qty("10 XEON @@ €1500")
        assert result is not None
        qty, commodity, proceeds = result
        assert qty == Decimal("10")
        assert proceeds == Decimal("1500")


class TestBuildCommodityData:
    """Unit tests for _build_commodity_data."""

    def test_single_account_single_commodity(self):
        positions = [("assets:investments:etf", Decimal("100"), "XEON")]
        costs = {"assets:investments:etf": (Decimal("10000"), "€")}
        result = _build_commodity_data(positions, costs)
        assert "XEON" in result
        total_units, total_cost, currency = result["XEON"]
        assert total_units == Decimal("100")
        assert total_cost == Decimal("10000")
        assert currency == "€"

    def test_multiple_accounts_same_commodity(self):
        positions = [
            ("assets:investments:acc1", Decimal("60"), "XEON"),
            ("assets:investments:acc2", Decimal("40"), "XEON"),
        ]
        costs = {
            "assets:investments:acc1": (Decimal("6000"), "€"),
            "assets:investments:acc2": (Decimal("4200"), "€"),
        }
        result = _build_commodity_data(positions, costs)
        assert "XEON" in result
        total_units, total_cost, currency = result["XEON"]
        assert total_units == Decimal("100")
        assert total_cost == Decimal("10200")
        assert currency == "€"

    def test_account_without_cost_excludes_commodity(self):
        positions = [("assets:investments:etf", Decimal("100"), "XEON")]
        costs: dict = {}
        result = _build_commodity_data(positions, costs)
        assert "XEON" not in result

    def test_zero_units_excluded(self):
        positions = [("assets:investments:etf", Decimal("0"), "XEON")]
        costs = {"assets:investments:etf": (Decimal("0"), "€")}
        result = _build_commodity_data(positions, costs)
        assert "XEON" not in result

    def test_negative_units_excluded(self):
        positions = [("assets:investments:etf", Decimal("-5"), "XEON")]
        costs = {"assets:investments:etf": (Decimal("500"), "€")}
        result = _build_commodity_data(positions, costs)
        assert "XEON" not in result

    def test_multiple_commodities(self):
        positions = [
            ("assets:investments:etf1", Decimal("50"), "XEON"),
            ("assets:investments:etf2", Decimal("30"), "STCK"),
        ]
        costs = {
            "assets:investments:etf1": (Decimal("5000"), "€"),
            "assets:investments:etf2": (Decimal("900"), "€"),
        }
        result = _build_commodity_data(positions, costs)
        assert "XEON" in result
        assert "STCK" in result
        assert result["XEON"][0] == Decimal("50")
        assert result["STCK"][0] == Decimal("30")

    def test_partial_cost_excludes_commodity(self):
        """When one account for a commodity lacks a cost, the commodity is excluded."""
        positions = [
            ("assets:investments:acc1", Decimal("60"), "XEON"),
            ("assets:investments:acc2", Decimal("40"), "XEON"),
        ]
        costs = {
            "assets:investments:acc1": (Decimal("6000"), "€"),
            # acc2 intentionally missing
        }
        result = _build_commodity_data(positions, costs)
        assert "XEON" not in result
