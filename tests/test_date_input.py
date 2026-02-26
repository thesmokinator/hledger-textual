"""Tests for the DateInput widget keyboard handling and auto-formatting."""

from __future__ import annotations

from textual.app import App, ComposeResult

from hledger_tui.widgets.date_input import DateInput


class _DateApp(App):
    """Minimal app with a single DateInput for isolated widget testing."""

    def compose(self) -> ComposeResult:
        """Compose a single DateInput."""
        yield DateInput(id="date")


class TestDateInputOnKey:
    """Tests for digit filtering and auto-dash insertion in DateInput._on_key."""

    async def test_digits_produce_year(self):
        """Typing 4 digits produces the year portion."""
        app = _DateApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("2", "0", "2", "6")
            assert inp.value == "2026"

    async def test_auto_inserts_first_dash(self):
        """A dash is auto-inserted after the 4-digit year."""
        app = _DateApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("2", "0", "2", "6", "0", "1")
            assert inp.value == "2026-01"

    async def test_auto_inserts_second_dash(self):
        """Both dashes are auto-inserted when the full date is typed."""
        app = _DateApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("2", "0", "2", "6", "0", "1", "1", "5")
            assert inp.value == "2026-01-15"

    async def test_letter_is_blocked(self):
        """Letter characters are not accepted."""
        app = _DateApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("a")
            assert inp.value == ""

    async def test_space_is_blocked(self):
        """Space is not accepted."""
        app = _DateApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("space")
            assert inp.value == ""

    async def test_period_is_blocked(self):
        """Period/dot is not accepted."""
        app = _DateApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.focus()
            await pilot.pause()
            await pilot.press(".")
            assert inp.value == ""

    async def test_no_more_than_eight_digits(self):
        """Typing beyond 8 digits does not change the value."""
        app = _DateApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("2", "0", "2", "6", "0", "1", "1", "5", "9", "9")
            assert inp.value == "2026-01-15"

    async def test_partial_year_only(self):
        """Typing fewer than 4 digits stays without dashes."""
        app = _DateApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("2", "0")
            assert inp.value == "20"

    async def test_year_and_partial_month(self):
        """Typing 5 digits inserts a dash and shows the partial month."""
        app = _DateApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.focus()
            await pilot.pause()
            await pilot.press("2", "0", "2", "6", "0")
            assert inp.value == "2026-0"
