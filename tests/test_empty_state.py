"""Integration tests for reusable empty states."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from textual.app import App, ComposeResult
from textual.widgets import DataTable

from hledger_textual.models import Amount, Posting, Transaction
from hledger_textual.widgets.empty_state import EmptyState
from hledger_textual.widgets.transactions_table import TransactionsTable


class _TransactionsApp(App):
    """Minimal app wrapping TransactionsTable for empty-state testing."""

    def __init__(self, journal_file: Path) -> None:
        """Initialize with a journal file path."""
        super().__init__()
        self._journal_file = journal_file

    def compose(self) -> ComposeResult:
        """Compose a single TransactionsTable."""
        yield TransactionsTable(self._journal_file)


@pytest.fixture
def empty_journal(tmp_path: Path) -> Path:
    """Create an empty journal file."""
    journal = tmp_path / "empty.journal"
    journal.write_text("")
    return journal


async def test_transactions_empty_state_toggles_when_data_appears(
    empty_journal: Path, monkeypatch
) -> None:
    """Transactions empty state appears for no rows and hides after reload."""
    loaded_transactions: list[Transaction] = []

    def load_transactions_stub(*args, **kwargs) -> list[Transaction]:
        return list(loaded_transactions)

    monkeypatch.setattr(
        "hledger_textual.widgets.transactions_table.load_transactions",
        load_transactions_stub,
    )

    app = _TransactionsApp(empty_journal)

    async with app.run_test() as pilot:
        await pilot.pause(delay=1.0)

        empty_state = app.query_one("#transactions-empty-state", EmptyState)
        table = app.query_one("#transactions-table", DataTable)
        assert empty_state.display is True
        assert table.display is False
        assert table.row_count == 0

        today = date.today().isoformat()
        loaded_transactions.append(
            Transaction(
                index=1,
                date=today,
                description="Grocery shopping",
                postings=[
                    Posting(
                        "expenses:food",
                        amounts=[Amount("€", Decimal("40.80"))],
                    ),
                    Posting("assets:bank:checking"),
                ],
            )
        )

        app.query_one(TransactionsTable).reload()
        await pilot.pause(delay=1.0)

        assert empty_state.display is False
        assert table.display is True
        assert table.row_count == 1
