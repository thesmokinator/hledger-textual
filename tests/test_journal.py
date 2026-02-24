"""Tests for journal file manipulation."""

from pathlib import Path

import pytest

from hledger_tui.journal import (
    JournalError,
    append_transaction,
    delete_transaction,
    replace_transaction,
)
from hledger_tui.hledger import load_transactions
from hledger_tui.models import Transaction

from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


class TestAppendTransaction:
    """Tests for append_transaction."""

    def test_append_increases_count(self, tmp_journal: Path, new_transaction: Transaction):
        original = load_transactions(tmp_journal)
        append_transaction(tmp_journal, new_transaction)
        updated = load_transactions(tmp_journal)
        assert len(updated) == len(original) + 1

    def test_appended_transaction_content(self, tmp_journal: Path, new_transaction: Transaction):
        append_transaction(tmp_journal, new_transaction)
        txns = load_transactions(tmp_journal)
        last = txns[-1]
        assert last.description == "Rent payment"
        assert last.date == "2026-02-01"

    def test_no_backup_left(self, tmp_journal: Path, new_transaction: Transaction):
        append_transaction(tmp_journal, new_transaction)
        backup = tmp_journal.with_suffix(tmp_journal.suffix + ".bak")
        assert not backup.exists()


class TestDeleteTransaction:
    """Tests for delete_transaction."""

    def test_delete_reduces_count(self, tmp_journal: Path):
        txns = load_transactions(tmp_journal)
        delete_transaction(tmp_journal, txns[0])
        updated = load_transactions(tmp_journal)
        assert len(updated) == len(txns) - 1

    def test_delete_middle_transaction(self, tmp_journal: Path):
        txns = load_transactions(tmp_journal)
        delete_transaction(tmp_journal, txns[1])
        updated = load_transactions(tmp_journal)
        descriptions = [t.description for t in updated]
        assert "Salary" not in descriptions
        assert "Grocery shopping" in descriptions
        assert "Office supplies" in descriptions

    def test_delete_without_source_pos_raises(self, tmp_journal: Path):
        txn = Transaction(index=1, date="2026-01-01", description="No pos")
        with pytest.raises(JournalError, match="source position"):
            delete_transaction(tmp_journal, txn)

    def test_no_backup_left(self, tmp_journal: Path):
        txns = load_transactions(tmp_journal)
        delete_transaction(tmp_journal, txns[0])
        backup = tmp_journal.with_suffix(tmp_journal.suffix + ".bak")
        assert not backup.exists()


class TestReplaceTransaction:
    """Tests for replace_transaction."""

    def test_replace_updates_description(
        self, tmp_journal: Path, new_transaction: Transaction
    ):
        txns = load_transactions(tmp_journal)
        replace_transaction(tmp_journal, txns[0], new_transaction)
        updated = load_transactions(tmp_journal)
        descriptions = [t.description for t in updated]
        assert "Rent payment" in descriptions
        assert "Grocery shopping" not in descriptions

    def test_replace_preserves_count(
        self, tmp_journal: Path, new_transaction: Transaction
    ):
        txns = load_transactions(tmp_journal)
        original_count = len(txns)
        replace_transaction(tmp_journal, txns[0], new_transaction)
        updated = load_transactions(tmp_journal)
        assert len(updated) == original_count

    def test_replace_without_source_pos_raises(
        self, tmp_journal: Path, new_transaction: Transaction
    ):
        txn = Transaction(index=1, date="2026-01-01", description="No pos")
        with pytest.raises(JournalError, match="source position"):
            replace_transaction(tmp_journal, txn, new_transaction)

    def test_no_backup_left(
        self, tmp_journal: Path, new_transaction: Transaction
    ):
        txns = load_transactions(tmp_journal)
        replace_transaction(tmp_journal, txns[0], new_transaction)
        backup = tmp_journal.with_suffix(tmp_journal.suffix + ".bak")
        assert not backup.exists()
