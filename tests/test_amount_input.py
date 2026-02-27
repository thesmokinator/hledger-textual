"""Tests for the AmountInput widget keyboard handling and blur formatting."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input

from hledger_textual.widgets.amount_input import AmountInput


class _AmountApp(App):
    """Minimal app with an AmountInput for isolated widget testing."""

    def compose(self) -> ComposeResult:
        """Compose a single AmountInput and a second Input for blur testing."""
        yield AmountInput(id="amount")
        yield Input(id="other")


class TestAmountInputOnKey:
    """Tests for character filtering in AmountInput._on_key."""

    async def test_digit_is_inserted(self):
        """Digit characters pass through and are inserted into the value."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            app.query_one("#amount").focus()
            await pilot.pause()
            await pilot.press("5")
            assert "5" in app.query_one("#amount", AmountInput).value

    async def test_letter_is_blocked(self):
        """Letter characters are rejected and not inserted."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            app.query_one("#amount").focus()
            await pilot.pause()
            await pilot.press("a")
            assert app.query_one("#amount", AmountInput).value == ""

    async def test_uppercase_letter_is_blocked(self):
        """Uppercase letter characters are rejected."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#amount", AmountInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("A")
            assert inp.value == ""

    async def test_decimal_point_accepted(self):
        """A single decimal point is accepted after a digit."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#amount", AmountInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("5")
            await pilot.press(".")
            assert "." in inp.value

    async def test_second_decimal_point_blocked(self):
        """A second decimal point is rejected."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#amount", AmountInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("5", ".", "2", ".")
            assert inp.value.count(".") == 1

    async def test_minus_at_position_zero_accepted(self):
        """Minus sign at cursor position 0 is accepted."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#amount", AmountInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("-")
            assert inp.value.startswith("-")

    async def test_minus_after_digit_blocked(self):
        """Minus sign after other characters is rejected."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#amount", AmountInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("5", "-")
            assert "-" not in inp.value

    async def test_second_minus_blocked(self):
        """A second minus sign is rejected even with cursor at start."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#amount", AmountInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("-", "-")
            assert inp.value.count("-") == 1

    async def test_multiple_digits_inserted(self):
        """Multiple digit keypresses accumulate correctly."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#amount", AmountInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("1", "2", "3")
            assert inp.value == "123"

    async def test_negative_amount_with_digits(self):
        """Minus followed by digits produces a negative value."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#amount", AmountInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("-", "5", "0")
            assert inp.value == "-50"


class TestAmountInputOnBlur:
    """Tests for auto-formatting in AmountInput._on_blur."""

    async def test_integer_formatted_to_two_decimals(self):
        """An integer value is formatted to 2 decimal places when focus leaves."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#amount", AmountInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("4", "9")
            app.query_one("#other").focus()
            await pilot.pause()
            assert inp.value == "49.00"

    async def test_partial_decimal_gets_trailing_zero(self):
        """A single-decimal value gets a trailing zero on blur."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#amount", AmountInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("3", ".", "5")
            app.query_one("#other").focus()
            await pilot.pause()
            assert inp.value == "3.50"

    async def test_empty_value_stays_empty(self):
        """An empty field is not modified on blur."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#amount", AmountInput)
            inp.focus()
            await pilot.pause()
            app.query_one("#other").focus()
            await pilot.pause()
            assert inp.value == ""

    async def test_already_formatted_value_unchanged(self):
        """A value already at 2 decimal places is not changed on blur."""
        app = _AmountApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#amount", AmountInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("1", "2", ".", "3", "4")
            app.query_one("#other").focus()
            await pilot.pause()
            assert inp.value == "12.34"
