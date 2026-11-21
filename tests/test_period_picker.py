"""Tests for the period picker modal and its pane wiring (issue #266)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from hledger_textual.app import HledgerTuiApp
from hledger_textual.models import JournalStats
from hledger_textual.period import (
    month_selection,
    year_selection,
)
from hledger_textual.screens.period_picker import PeriodPickerModal
from tests.conftest import has_hledger, wait_until


class _PickerApp(App):
    """Minimal app pushing the picker modal directly."""

    def __init__(self, stats: JournalStats | None = None) -> None:
        super().__init__()
        self._stats = stats

    def compose(self) -> ComposeResult:
        yield Static("picker test host")

    def on_mount(self) -> None:
        self.push_screen(
            PeriodPickerModal(journal_stats=self._stats), callback=self._store
        )

    def _store(self, selection) -> None:
        self._result = selection


def _picker_journal(tmp_path: Path) -> Path:
    """Journal spanning 2024-03 to 2024-05."""
    journal = tmp_path / "span.journal"
    journal.write_text(
        "2024-03-10 * A\n    expenses:food  10.00\n    assets:checking\n"
        "\n"
        "2024-05-01 * B\n    assets:checking  100.00\n    income:salary\n"
    )
    return journal


def _span_stats() -> JournalStats:
    """Stats carrying a fixed date span."""
    return JournalStats(
        transaction_count=2,
        account_count=3,
        first_date=date(2024, 3, 10),
        last_date=date(2024, 5, 1),
    )


class TestPeriodPickerModal:
    """Validation behaviour of the picker modal itself."""

    async def test_valid_period_dismisses_with_selection(self, tmp_path: Path):
        """A valid expression returns the parsed selection."""
        app = _PickerApp(stats=_span_stats())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#period-picker-input", Input).value = "2024-04"
            await pilot.press("enter")
            await pilot.pause()
            assert app._result == month_selection(date(2024, 4, 1))

    async def test_invalid_period_shows_error_and_stays_open(self, tmp_path: Path):
        """A bad expression shows an error and does not dismiss."""
        app = _PickerApp(stats=_span_stats())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#period-picker-input", Input).value = "banana"
            await pilot.press("enter")
            await pilot.pause()
            error = app.screen.query_one("#period-picker-error", Static)
            assert "Invalid period" in str(error.content)
            assert isinstance(app.screen, PeriodPickerModal)

    async def test_empty_period_shows_error(self, tmp_path: Path):
        """An empty submission is rejected."""
        app = _PickerApp(stats=_span_stats())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#period-picker-input", Input).value = "  "
            await pilot.press("enter")
            await pilot.pause()
            error = app.screen.query_one("#period-picker-error", Static)
            assert "Enter a period" in str(error.content)

    async def test_out_of_span_period_is_rejected(self, tmp_path: Path):
        """A valid expression outside the journal span gets an explanatory error."""
        app = _PickerApp(stats=_span_stats())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#period-picker-input", Input).value = "2024-09"
            await pilot.press("enter")
            await pilot.pause()
            error = app.screen.query_one("#period-picker-error", Static)
            assert "No transactions" in str(error.content)
            assert "2024-03-10" in str(error.content)
            assert "2024-05-01" in str(error.content)

    async def test_relative_aliases_work(self, tmp_path: Path):
        """``ytd`` and month/year aliases parse through the picker."""
        app = _PickerApp()  # no span stats: no validation to reject ytd
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#period-picker-input", Input).value = "ytd"
            await pilot.press("enter")
            await pilot.pause()
            assert app._result is not None

    async def test_escape_dismisses_with_none(self, tmp_path: Path):
        """Escape cancels the picker."""
        app = _PickerApp(stats=_span_stats())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app._result is None

    async def test_span_input_placeholder(self, tmp_path: Path):
        """The input placeholder shows the current selection's expression."""
        app = _PickerApp(stats=_span_stats())
        async with app.run_test() as pilot:
            await pilot.pause()
            # The host pushes the picker with current=None.
            assert (
                app.screen.query_one("#period-picker-input", Input).placeholder
                == "2024-03"
            )


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestTransactionsPickerWiring:
    """Transactions pane integration: g opens the picker, labels stay honest."""

    @pytest.fixture
    def picker_txn_app(self, tmp_path: Path) -> HledgerTuiApp:
        """App over a journal spanning several months."""
        journal = _picker_journal(tmp_path)
        return HledgerTuiApp(journal_file=journal)

    async def test_g_opens_picker_and_selecting_year_shows_year_label(
        self, picker_txn_app: HledgerTuiApp
    ):
        """Pressing g opens the modal; choosing 2024 jumps and labels "2024"."""
        from hledger_textual.screens.period_picker import PeriodPickerModal
        from hledger_textual.widgets.transactions_table import TransactionsTable

        async with picker_txn_app.run_test() as pilot:
            await pilot.pause()
            picker_txn_app._activate_section("transactions")
            await pilot.pause(delay=0.5)
            await pilot.press("g")
            await pilot.pause()
            assert isinstance(picker_txn_app.screen, PeriodPickerModal)
            picker_txn_app.screen.query_one("#period-picker-input", Input).value = "2024"
            await pilot.press("enter")
            await pilot.pause(delay=0.5)
            table = picker_txn_app.query_one(TransactionsTable)
            assert table._period == year_selection(2024)
            assert table._period_label() == "2024"

    async def test_arrows_continue_from_selected_year(
        self, picker_txn_app: HledgerTuiApp
    ):
        """Month arrows step from a jumped period, sliding the range."""
        from hledger_textual.widgets.transactions_table import TransactionsTable

        async with picker_txn_app.run_test() as pilot:
            await pilot.pause()
            picker_txn_app._activate_section("transactions")
            await pilot.pause(delay=0.5)
            picker_txn_app.query_one(TransactionsTable).goto_period(
                year_selection(2024)
            )
            await pilot.pause(delay=0.5)
            await pilot.press("right")
            await pilot.pause(delay=0.5)
            selection = picker_txn_app.period_selection
            # A 12-month range slides by one month: Feb 2024 → Jan 2025.
            assert selection.begin == date(2024, 2, 1)
            assert selection.end == date(2025, 2, 1)
            assert selection.label == "Feb 2024 → Jan 2025"

    async def test_year_step_bindings(self, picker_txn_app: HledgerTuiApp):
        """Shift+arrows step one year in the Transactions pane."""
        from hledger_textual.widgets.transactions_table import TransactionsTable

        async with picker_txn_app.run_test() as pilot:
            await pilot.pause()
            picker_txn_app._activate_section("transactions")
            await pilot.pause(delay=0.5)
            picker_txn_app.query_one(TransactionsTable).goto_period(
                month_selection(date(2024, 3, 1))
            )
            await pilot.pause(delay=0.5)
            await pilot.press("shift+left")
            await pilot.pause(delay=0.5)
            table = picker_txn_app.query_one(TransactionsTable)
            assert table._period == month_selection(date(2023, 3, 1))

    async def test_search_placeholder_lists_real_aliases(
        self, picker_txn_app: HledgerTuiApp
    ):
        """The search placeholder documents date: and hides the misleading d:."""
        from hledger_textual.widgets.transactions_table import TransactionsTable

        async with picker_txn_app.run_test() as pilot:
            await pilot.pause()
            picker_txn_app._activate_section("transactions")
            await pilot.pause(delay=0.5)
            table = picker_txn_app.query_one(TransactionsTable)
            placeholder = table.query_one("#txn-search-input", Input).placeholder
            assert "date:" in placeholder
            assert "d:" not in placeholder
            assert "status:" in placeholder

    async def test_saved_filters_still_apply(self, picker_txn_app: HledgerTuiApp):
        """Applying a saved filter still searches the whole journal."""
        from hledger_textual.widgets.transactions_table import TransactionsTable

        async with picker_txn_app.run_test() as pilot:
            await pilot.pause()
            picker_txn_app._activate_section("transactions")
            await pilot.pause(delay=0.5)
            table = picker_txn_app.query_one(TransactionsTable)
            table.apply_saved_filter("income:salary")
            await wait_until(pilot, lambda: len(table._all_transactions) == 1)
            assert table._search_query == "income:salary"
