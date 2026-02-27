"""Tests for journal file manipulation."""

from pathlib import Path

import pytest

from hledger_textual.journal import (
    JournalError,
    append_transaction,
    delete_transaction,
    replace_transaction,
)
from hledger_textual.hledger import HledgerError, load_transactions
from hledger_textual.models import SourcePosition, Transaction

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


class TestValidationFailure:
    """Tests for backup/restore when hledger validation fails after a write."""

    def test_append_restores_original_on_invalid_journal(
        self, tmp_journal: Path, new_transaction: Transaction, monkeypatch
    ):
        """Original content is restored when hledger check rejects the result."""
        original = tmp_journal.read_text()

        def _fail_check(file):
            raise HledgerError("journal invalid")

        monkeypatch.setattr("hledger_textual.journal.check_journal", _fail_check)

        with pytest.raises(JournalError, match="validation failed"):
            append_transaction(tmp_journal, new_transaction)

        assert tmp_journal.read_text() == original
        assert not tmp_journal.with_suffix(tmp_journal.suffix + ".bak").exists()

    def test_replace_restores_original_on_invalid_journal(
        self, tmp_journal: Path, new_transaction: Transaction, monkeypatch
    ):
        """Replace restores original content when validation fails."""
        txns = load_transactions(tmp_journal)
        original = tmp_journal.read_text()

        def _fail_check(file):
            raise HledgerError("journal invalid")

        monkeypatch.setattr("hledger_textual.journal.check_journal", _fail_check)

        with pytest.raises(JournalError, match="validation failed"):
            replace_transaction(tmp_journal, txns[0], new_transaction)

        assert tmp_journal.read_text() == original
        assert not tmp_journal.with_suffix(tmp_journal.suffix + ".bak").exists()

    def test_delete_restores_original_on_invalid_journal(
        self, tmp_journal: Path, monkeypatch
    ):
        """Delete restores original content when validation fails."""
        txns = load_transactions(tmp_journal)
        original = tmp_journal.read_text()

        def _fail_check(file):
            raise HledgerError("journal invalid")

        monkeypatch.setattr("hledger_textual.journal.check_journal", _fail_check)

        with pytest.raises(JournalError, match="validation failed"):
            delete_transaction(tmp_journal, txns[0])

        assert tmp_journal.read_text() == original
        assert not tmp_journal.with_suffix(tmp_journal.suffix + ".bak").exists()


class TestExceptExceptionPaths:
    """Tests for the generic except-Exception safety net in each operation."""

    def test_append_restores_on_format_exception(
        self, tmp_journal: Path, new_transaction: Transaction, monkeypatch
    ):
        """append_transaction restores the file when format_transaction raises."""
        original = tmp_journal.read_text()

        def _fail_format(txn):
            raise RuntimeError("format failed")

        monkeypatch.setattr("hledger_textual.journal.format_transaction", _fail_format)

        with pytest.raises(JournalError, match="Failed to append"):
            append_transaction(tmp_journal, new_transaction)

        assert tmp_journal.read_text() == original
        assert not tmp_journal.with_suffix(tmp_journal.suffix + ".bak").exists()

    def test_replace_restores_on_format_exception(
        self, tmp_journal: Path, new_transaction: Transaction, monkeypatch
    ):
        """replace_transaction restores the file when format_transaction raises."""
        txns = load_transactions(tmp_journal)
        original = tmp_journal.read_text()

        def _fail_format(txn):
            raise RuntimeError("format failed")

        monkeypatch.setattr("hledger_textual.journal.format_transaction", _fail_format)

        with pytest.raises(JournalError, match="Failed to replace"):
            replace_transaction(tmp_journal, txns[0], new_transaction)

        assert tmp_journal.read_text() == original
        assert not tmp_journal.with_suffix(tmp_journal.suffix + ".bak").exists()

    def test_delete_restores_on_out_of_bounds_source_pos(self, tmp_journal: Path):
        """delete_transaction restores the file when source positions are invalid."""
        original = tmp_journal.read_text()

        # A transaction whose source_pos points far beyond the file causes
        # an IndexError inside the try block, triggering the except Exception path.
        fake_txn = Transaction(
            index=999,
            date="2026-01-01",
            description="Out of bounds",
            source_pos=(
                SourcePosition("test.journal", 1000, 1),
                SourcePosition("test.journal", 1003, 1),
            ),
        )

        with pytest.raises(JournalError, match="Failed to delete"):
            delete_transaction(tmp_journal, fake_txn)

        assert tmp_journal.read_text() == original
        assert not tmp_journal.with_suffix(tmp_journal.suffix + ".bak").exists()


class TestAppendEdgeCases:
    """Edge cases for append_transaction."""

    def test_append_to_file_without_trailing_newline(
        self, tmp_journal: Path, new_transaction: Transaction
    ):
        """append_transaction correctly handles files that don't end with '\\n'."""
        content = tmp_journal.read_text().rstrip("\n")
        tmp_journal.write_text(content)

        append_transaction(tmp_journal, new_transaction)

        result = tmp_journal.read_text()
        assert "Rent payment" in result
