"""Tests for the TransactionsTable widget internals."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from textual.app import App, ComposeResult
from textual.widgets import Input

from hledger_tui.app import HledgerTuiApp
from hledger_tui.widgets.transactions_table import TransactionsTable
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


@pytest.fixture
def multi_month_journal(tmp_path: Path) -> Path:
    """A journal with transactions in the current and previous month."""
    today = date.today()
    cur = today.replace(day=1)
    prev_month = cur.month - 1
    prev_year = cur.year
    if prev_month < 1:
        prev_month, prev_year = 12, prev_year - 1
    prev = cur.replace(year=prev_year, month=prev_month)
    content = (
        f"{cur.isoformat()} * Current month txn\n"
        "    expenses:food              €10.00\n"
        "    assets:bank:checking\n"
        "\n"
        f"{prev.isoformat()} * Previous month txn\n"
        "    expenses:food              €20.00\n"
        "    assets:bank:checking\n"
    )
    journal = tmp_path / "multi.journal"
    journal.write_text(content)
    return journal


# ------------------------------------------------------------------
# Month query helper tests (pure, no hledger needed)
# ------------------------------------------------------------------


class TestMonthQuery:
    """Tests for the _month_query helper on TransactionsTable."""

    def test_month_query_format(self):
        """_month_query returns hledger date:YYYY-MM format."""
        table = TransactionsTable.__new__(TransactionsTable)
        table._current_month = date(2026, 2, 1)
        assert table._month_query() == "date:2026-02"

    def test_period_label_format(self):
        """_period_label returns a human-readable month label."""
        table = TransactionsTable.__new__(TransactionsTable)
        table._current_month = date(2026, 2, 1)
        assert table._period_label() == "February 2026"


# ------------------------------------------------------------------
# Integration tests (require hledger)
# ------------------------------------------------------------------


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestTransactionsTableMount:
    """Tests for TransactionsTable initial mount."""

    async def test_table_mounts_with_rows(self, table_journal: Path):
        """Table loads current-month transactions on mount."""
        app = _TableApp(table_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            table = app.query_one("#transactions-table")
            assert table.row_count == 2

    async def test_period_nav_visible(self, table_journal: Path):
        """Month navigation bar is visible (not pinned)."""
        app = _TableApp(table_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            nav = app.query_one("#txn-period-nav")
            assert not nav.has_class("hidden")


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestTransactionsTableMonthNav:
    """Tests for month-based navigation."""

    async def test_prev_month_navigates(self, multi_month_journal: Path):
        """Navigating to the previous month shows previous-month transactions."""
        app = _TableApp(multi_month_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            table = app.query_one("#transactions-table")
            assert table.row_count == 1  # only current month txn
            txn_table = app.query_one(TransactionsTable)
            txn_table.prev_month()
            await pilot.pause(delay=1.0)
            assert table.row_count == 1  # only previous month txn

    async def test_next_month_after_prev_returns(self, multi_month_journal: Path):
        """Navigating back to the current month after prev_month."""
        app = _TableApp(multi_month_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            txn_table = app.query_one(TransactionsTable)
            txn_table.prev_month()
            await pilot.pause(delay=1.0)
            txn_table.next_month()
            await pilot.pause(delay=1.0)
            table = app.query_one("#transactions-table")
            assert table.row_count == 1  # back to current month


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestTransactionsTableSearch:
    """Tests for hledger-query search functionality."""

    async def test_show_filter_reveals_search_bar(self, table_journal: Path):
        """show_filter makes the filter bar visible."""
        app = _TableApp(table_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            txn_table = app.query_one(TransactionsTable)
            txn_table.show_filter()
            await pilot.pause()
            filter_bar = txn_table.query_one(".filter-bar")
            assert filter_bar.has_class("visible")

    async def test_search_filters_by_description(self, table_journal: Path):
        """Submitting a desc: query narrows results."""
        app = _TableApp(table_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            txn_table = app.query_one(TransactionsTable)
            txn_table.show_filter()
            await pilot.pause()
            search_input = txn_table.query_one("#txn-search-input", Input)
            search_input.focus()
            search_input.value = "desc:Grocery"
            await pilot.press("enter")
            await pilot.pause(delay=1.0)
            table = app.query_one("#transactions-table")
            assert table.row_count == 1

    async def test_search_filters_by_account(self, table_journal: Path):
        """Submitting an acct: query narrows results."""
        app = _TableApp(table_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            txn_table = app.query_one(TransactionsTable)
            txn_table.show_filter()
            await pilot.pause()
            search_input = txn_table.query_one("#txn-search-input", Input)
            search_input.focus()
            search_input.value = "acct:income"
            await pilot.press("enter")
            await pilot.pause(delay=1.0)
            table = app.query_one("#transactions-table")
            assert table.row_count == 1

    async def test_dismiss_filter_restores_month_view(self, table_journal: Path):
        """dismiss_filter clears search and restores month navigation."""
        app = _TableApp(table_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            txn_table = app.query_one(TransactionsTable)
            txn_table.show_filter()
            await pilot.pause()
            search_input = txn_table.query_one("#txn-search-input", Input)
            search_input.value = "desc:Grocery"
            await pilot.press("enter")
            await pilot.pause(delay=1.0)
            result = txn_table.dismiss_filter()
            assert result is True
            await pilot.pause(delay=1.0)
            table = app.query_one("#transactions-table")
            assert table.row_count == 2  # all current-month txns restored

    async def test_dismiss_filter_returns_false_when_hidden(
        self, table_journal: Path
    ):
        """dismiss_filter returns False if the filter bar is already hidden."""
        app = _TableApp(table_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            txn_table = app.query_one(TransactionsTable)
            assert txn_table.dismiss_filter() is False


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
            await pilot.press("2")
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
            await pilot.press("2")
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
            await pilot.press("2")
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
