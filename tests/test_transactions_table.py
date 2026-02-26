"""Tests for the TransactionsTable widget internals."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from textual.app import App, ComposeResult

from hledger_tui.app import HledgerTuiApp
from hledger_tui.widgets.transactions_table import TransactionsTable, _period_query
from tests.conftest import has_hledger


class _TableApp(App):
    """Minimal app wrapping TransactionsTable for isolated widget testing."""

    def __init__(self, journal_file: Path) -> None:
        """Initialize with a journal file path."""
        super().__init__()
        self._journal_file = journal_file

    def compose(self) -> ComposeResult:
        """Compose a single TransactionsTable."""
        yield TransactionsTable(self._journal_file)


@pytest.fixture
def table_journal(tmp_path: Path) -> Path:
    """A minimal journal with current-month transactions."""
    today = date.today()
    d1 = today.replace(day=1)
    d2 = today.replace(day=2)
    content = (
        f"{d1.isoformat()} * Grocery shopping\n"
        "    expenses:food              €40.80\n"
        "    assets:bank:checking\n"
        "\n"
        f"{d2.isoformat()} Salary\n"
        "    assets:bank:checking     €3000.00\n"
        "    income:salary\n"
    )
    journal = tmp_path / "test.journal"
    journal.write_text(content)
    return journal


@pytest.fixture
def empty_table_journal(tmp_path: Path) -> Path:
    """An empty journal for no-selection testing."""
    journal = tmp_path / "empty.journal"
    journal.write_text("")
    return journal


class TestPeriodQuery:
    """Tests for _period_query helper."""

    def test_thismonth(self):
        """'thismonth' returns hledger date:thismonth."""
        assert _period_query("thismonth") == "date:thismonth"

    def test_all(self):
        """'all' returns empty string (no date filter)."""
        assert _period_query("all") == ""

    def test_numeric_days(self):
        """Numeric period returns date range from N days ago."""
        result = _period_query("30")
        expected_start = (date.today() - timedelta(days=30)).isoformat()
        assert result == f"date:{expected_start}.."

    def test_seven_days(self):
        """7-day period returns correct start date."""
        result = _period_query("7")
        expected_start = (date.today() - timedelta(days=7)).isoformat()
        assert result == f"date:{expected_start}.."

    def test_365_days(self):
        """365-day period (1 year) returns correct start date."""
        result = _period_query("365")
        expected_start = (date.today() - timedelta(days=365)).isoformat()
        assert result == f"date:{expected_start}.."


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestTransactionsTablePeriodButtons:
    """Tests for period button click handling."""

    async def test_period_button_activates(self, table_journal: Path):
        """Clicking a period button adds the -active class to that button."""
        from textual.widgets import Button

        app = _TableApp(table_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            btn_30 = app.query_one("#period-30", Button)
            await pilot.click(btn_30)
            await pilot.pause()
            assert btn_30.has_class("-active")

    async def test_period_button_deactivates_previous(self, table_journal: Path):
        """Clicking a period button removes -active from the previously active one."""
        from textual.widgets import Button

        app = _TableApp(table_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            initial_btn = app.query_one("#period-thismonth", Button)
            assert initial_btn.has_class("-active")
            btn_30 = app.query_one("#period-30", Button)
            await pilot.click(btn_30)
            await pilot.pause()
            assert not initial_btn.has_class("-active")
            assert btn_30.has_class("-active")


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestTransactionsTableAccountFilter:
    """Tests for account filter input submission."""

    async def test_acct_filter_submit_filters_results(self, table_journal: Path):
        """Submitting the account filter reloads with only matching transactions."""
        from hledger_tui.widgets.autocomplete_input import AutocompleteInput

        app = _TableApp(table_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            txn_table = app.query_one(TransactionsTable)
            txn_table.show_filter()
            await pilot.pause()
            acct_input = txn_table.query_one("#txn-acct-input", AutocompleteInput)
            acct_input.focus()
            acct_input.value = "income"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause(delay=1.0)
            table = app.query_one("#transactions-table")
            assert table.row_count == 1


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestTransactionsTableNoSelection:
    """Tests for do_edit / do_delete when no transaction is selected."""

    async def test_do_edit_empty_table_no_form_pushed(
        self, empty_table_journal: Path
    ):
        """do_edit is a no-op when the table has no rows."""
        app = _TableApp(empty_table_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            txn_table = app.query_one(TransactionsTable)
            txn_table.do_edit()
            await pilot.pause()
            from hledger_tui.screens.transaction_form import TransactionFormScreen
            assert not isinstance(app.screen, TransactionFormScreen)

    async def test_do_delete_empty_table_no_confirm_pushed(
        self, empty_table_journal: Path
    ):
        """do_delete is a no-op when the table has no rows."""
        app = _TableApp(empty_table_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            txn_table = app.query_one(TransactionsTable)
            txn_table.do_delete()
            await pilot.pause()
            from hledger_tui.screens.delete_confirm import DeleteConfirmModal
            assert not isinstance(app.screen, DeleteConfirmModal)


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestTransactionsTableEditFlow:
    """Tests for do_replace (full edit flow) and its error path."""

    async def test_do_replace_updates_journal(self, table_journal: Path):
        """Editing a transaction and saving updates the journal file."""
        from hledger_tui.hledger import load_transactions

        app = HledgerTuiApp(journal_file=table_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            await pilot.press("e")
            await pilot.pause()
            from hledger_tui.screens.transaction_form import TransactionFormScreen
            from hledger_tui.widgets.autocomplete_input import AutocompleteInput
            assert isinstance(app.screen, TransactionFormScreen)
            app.screen.query_one("#input-description", AutocompleteInput).value = (
                "Updated grocery"
            )
            await pilot.click(app.screen.query_one("#btn-save"))
            await pilot.pause(delay=1.5)
            txns = load_transactions(table_journal)
            assert any(t.description == "Updated grocery" for t in txns)

    async def test_do_replace_journal_error_does_not_crash(
        self, table_journal: Path, monkeypatch
    ):
        """JournalError during _do_replace is caught and notified."""
        from hledger_tui.journal import JournalError

        def _raise(*args, **kwargs):
            raise JournalError("replace failed")

        monkeypatch.setattr("hledger_tui.journal.replace_transaction", _raise)
        app = HledgerTuiApp(journal_file=table_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            await pilot.press("e")
            await pilot.pause()
            from hledger_tui.screens.transaction_form import TransactionFormScreen
            from hledger_tui.widgets.autocomplete_input import AutocompleteInput
            assert isinstance(app.screen, TransactionFormScreen)
            app.screen.query_one("#input-description", AutocompleteInput).value = (
                "Updated grocery"
            )
            await pilot.click(app.screen.query_one("#btn-save"))
            await pilot.pause(delay=1.5)
            # App must not crash
            assert app.query_one("#transactions-table") is not None

    async def test_do_delete_journal_error_does_not_crash(
        self, table_journal: Path, monkeypatch
    ):
        """JournalError during _do_delete is caught and notified."""
        from hledger_tui.journal import JournalError

        def _raise(*args, **kwargs):
            raise JournalError("delete failed")

        monkeypatch.setattr("hledger_tui.journal.delete_transaction", _raise)
        app = HledgerTuiApp(journal_file=table_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            await pilot.press("d")
            await pilot.pause()
            from hledger_tui.screens.delete_confirm import DeleteConfirmModal
            assert isinstance(app.screen, DeleteConfirmModal)
            await pilot.click(app.screen.query_one("#btn-delete"))
            await pilot.pause(delay=1.5)
            assert app.query_one("#transactions-table") is not None


class TestTransactionsTableLoadErrors:
    """Tests for HledgerError handling in background load workers."""

    async def test_load_transactions_error_leaves_table_empty(
        self, table_journal: Path, monkeypatch
    ):
        """HledgerError during _load_transactions results in an empty table."""
        from hledger_tui.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("hledger failed")

        monkeypatch.setattr(
            "hledger_tui.widgets.transactions_table.load_transactions", _raise
        )
        app = _TableApp(table_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            table = app.query_one("#transactions-table")
            assert table.row_count == 0

    async def test_load_accounts_error_does_not_crash(
        self, table_journal: Path, monkeypatch
    ):
        """HledgerError during _load_accounts is silently handled."""
        from hledger_tui.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("accounts failed")

        monkeypatch.setattr(
            "hledger_tui.widgets.transactions_table.load_accounts", _raise
        )
        app = _TableApp(table_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            # App should not crash
            assert app.query_one(TransactionsTable) is not None
