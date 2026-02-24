"""Tests for hledger CLI reader."""

from decimal import Decimal
from pathlib import Path

import pytest

from hledger_tui.hledger import HledgerError, load_accounts, load_descriptions, load_transactions
from hledger_tui.models import TransactionStatus

from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


class TestLoadTransactions:
    """Tests for load_transactions."""

    def test_loads_all_transactions(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        assert len(txns) == 3

    def test_first_transaction_fields(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        txn = txns[0]
        assert txn.date == "2026-01-15"
        assert txn.description == "Grocery shopping"
        assert txn.status == TransactionStatus.CLEARED
        assert txn.code == "INV-001"
        assert txn.comment == "weekly groceries"

    def test_postings_parsed(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        txn = txns[0]
        assert len(txn.postings) == 2
        assert txn.postings[0].account == "expenses:food:groceries"
        assert txn.postings[0].amounts[0].commodity == "€"
        assert txn.postings[0].amounts[0].quantity == Decimal("40.80")

    def test_amounts_use_decimal(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        amount = txns[1].postings[0].amounts[0]
        assert isinstance(amount.quantity, Decimal)
        assert amount.quantity == Decimal("3000.00")

    def test_source_positions(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        assert txns[0].source_pos is not None
        start, end = txns[0].source_pos
        assert start.source_line == 3
        assert end.source_line == 6

    def test_pending_status(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        assert txns[2].status == TransactionStatus.PENDING

    def test_unmarked_status(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        assert txns[1].status == TransactionStatus.UNMARKED

    def test_three_postings(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        assert len(txns[2].postings) == 3

    def test_invalid_file_raises(self, tmp_path: Path):
        bad_file = tmp_path / "bad.journal"
        bad_file.write_text("this is not valid journal content\n")
        with pytest.raises(HledgerError):
            load_transactions(bad_file)


class TestLoadAccounts:
    """Tests for load_accounts."""

    def test_loads_accounts(self, sample_journal_path: Path):
        accounts = load_accounts(sample_journal_path)
        assert "expenses:food:groceries" in accounts
        assert "assets:bank:checking" in accounts
        assert "income:salary" in accounts

    def test_account_count(self, sample_journal_path: Path):
        accounts = load_accounts(sample_journal_path)
        assert len(accounts) == 5


class TestLoadDescriptions:
    """Tests for load_descriptions."""

    def test_loads_descriptions(self, sample_journal_path: Path):
        descriptions = load_descriptions(sample_journal_path)
        assert "Grocery shopping" in descriptions
        assert "Salary" in descriptions
        assert "Office supplies" in descriptions

    def test_description_count(self, sample_journal_path: Path):
        descriptions = load_descriptions(sample_journal_path)
        assert len(descriptions) == 3
