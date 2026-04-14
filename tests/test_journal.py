"""Tests for journal file manipulation."""

from pathlib import Path

import pytest

from decimal import Decimal

import shutil


from hledger_textual.journal import (
    JournalError,
    RoutingStrategy,
    _detect_routing_strategy,
    _find_date_includes,
    _find_glob_includes,
    _insert_glob_include_sorted,
    _insert_include_sorted,
    _target_subjournal_name,
    append_transaction,
    delete_transaction,
    replace_transaction,
)
from hledger_textual.hledger import HledgerError, load_transactions
from hledger_textual.models import (
    Amount,
    AmountStyle,
    Posting,
    SourcePosition,
    Transaction,
    TransactionStatus,
)

from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


def _make_transaction(date: str, description: str) -> Transaction:
    """Create a minimal valid transaction for routing tests."""
    style = AmountStyle(commodity_side="L", commodity_spaced=False, decimal_mark=".", precision=2)
    return Transaction(
        index=0,
        date=date,
        description=description,
        status=TransactionStatus.UNMARKED,
        postings=[
            Posting(
                account="expenses:food:groceries",
                amounts=[Amount(commodity="€", quantity=Decimal("50.00"), style=style)],
            ),
            Posting(
                account="assets:bank:checking",
                amounts=[Amount(commodity="€", quantity=Decimal("-50.00"), style=style)],
            ),
        ],
    )


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
                SourcePosition(str(tmp_journal), 1000, 1),
                SourcePosition(str(tmp_journal), 1003, 1),
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


class TestSubJournalOperations:
    """Tests for replace/delete on transactions living in included sub-journals."""

    def test_replace_in_sub_journal(
        self, tmp_journal_with_includes: Path, new_transaction: Transaction
    ):
        """Replace a transaction in a sub-journal; main journal stays untouched."""
        main = tmp_journal_with_includes
        main_original = main.read_text()
        txns = load_transactions(main)
        original_count = len(txns)

        # Pick a transaction from the January sub-journal
        jan_txn = next(t for t in txns if t.description == "Grocery shopping")

        replace_transaction(main, jan_txn, new_transaction)

        updated = load_transactions(main)
        assert len(updated) == original_count
        descriptions = [t.description for t in updated]
        assert "Rent payment" in descriptions
        assert "Grocery shopping" not in descriptions
        # Main journal must not have been modified
        assert main.read_text() == main_original

    def test_replace_preserves_other_sub_journal(
        self, tmp_journal_with_includes: Path, new_transaction: Transaction
    ):
        """Replacing in one sub-journal leaves the other sub-journal intact."""
        main = tmp_journal_with_includes
        feb_file = main.parent / "2026-02.journal"
        feb_original = feb_file.read_text()

        txns = load_transactions(main)
        jan_txn = next(t for t in txns if t.description == "Salary")

        replace_transaction(main, jan_txn, new_transaction)

        assert feb_file.read_text() == feb_original

    def test_delete_from_sub_journal(self, tmp_journal_with_includes: Path):
        """Delete a transaction from a sub-journal; main journal stays untouched."""
        main = tmp_journal_with_includes
        main_original = main.read_text()
        txns = load_transactions(main)
        original_count = len(txns)

        feb_txn = next(t for t in txns if t.description == "Electricity bill")

        delete_transaction(main, feb_txn)

        updated = load_transactions(main)
        assert len(updated) == original_count - 1
        descriptions = [t.description for t in updated]
        assert "Electricity bill" not in descriptions
        # Main journal must not have been modified
        assert main.read_text() == main_original

    def test_no_backup_left_after_sub_journal_replace(
        self, tmp_journal_with_includes: Path, new_transaction: Transaction
    ):
        """No .bak files remain after a successful replace in a sub-journal."""
        main = tmp_journal_with_includes
        txns = load_transactions(main)
        jan_txn = next(t for t in txns if t.description == "Grocery shopping")

        replace_transaction(main, jan_txn, new_transaction)

        bak_files = list(main.parent.glob("*.bak"))
        assert bak_files == []

    def test_no_backup_left_after_sub_journal_delete(
        self, tmp_journal_with_includes: Path
    ):
        """No .bak files remain after a successful delete in a sub-journal."""
        main = tmp_journal_with_includes
        txns = load_transactions(main)
        feb_txn = next(t for t in txns if t.description == "Rent payment")

        delete_transaction(main, feb_txn)

        bak_files = list(main.parent.glob("*.bak"))
        assert bak_files == []

    def test_validation_failure_restores_sub_journal(
        self, tmp_journal_with_includes: Path, new_transaction: Transaction, monkeypatch
    ):
        """On validation failure, the sub-journal (not main) is restored."""
        main = tmp_journal_with_includes
        txns = load_transactions(main)
        jan_txn = next(t for t in txns if t.description == "Grocery shopping")

        jan_file = main.parent / "2026-01.journal"
        jan_original = jan_file.read_text()
        main_original = main.read_text()

        def _fail_check(file):
            raise HledgerError("journal invalid")

        monkeypatch.setattr("hledger_textual.journal.check_journal", _fail_check)

        with pytest.raises(JournalError, match="validation failed"):
            replace_transaction(main, jan_txn, new_transaction)

        assert jan_file.read_text() == jan_original
        assert main.read_text() == main_original
        bak_files = list(main.parent.glob("*.bak"))
        assert bak_files == []


# ---------------------------------------------------------------------------
# Unit tests for routing helpers (no hledger required)
# ---------------------------------------------------------------------------


class TestFindDateIncludes:
    """Tests for _find_date_includes."""

    def test_detects_date_includes(self):
        content = "include 2026-01.journal\ninclude 2026-02.journal\n"
        assert _find_date_includes(content) == ["2026-01.journal", "2026-02.journal"]

    def test_ignores_non_date_includes(self):
        content = "include budget.journal\ninclude accounts.journal\n"
        assert _find_date_includes(content) == []

    def test_mixed_includes(self):
        content = (
            "include budget.journal\n"
            "include 2026-01.journal\n"
            "include accounts.journal\n"
            "include 2026-02.journal\n"
        )
        assert _find_date_includes(content) == ["2026-01.journal", "2026-02.journal"]

    def test_empty_content(self):
        assert _find_date_includes("") == []

    def test_leading_whitespace(self):
        content = "  include 2026-03.journal\n"
        assert _find_date_includes(content) == ["2026-03.journal"]


class TestTargetSubjournalName:
    """Tests for _target_subjournal_name."""

    def test_derives_filename_from_date(self):
        txn = Transaction(index=0, date="2026-03-15", description="test")
        assert _target_subjournal_name(txn) == "2026-03.journal"

    def test_january(self):
        txn = Transaction(index=0, date="2026-01-01", description="test")
        assert _target_subjournal_name(txn) == "2026-01.journal"

    def test_december(self):
        txn = Transaction(index=0, date="2025-12-31", description="test")
        assert _target_subjournal_name(txn) == "2025-12.journal"


class TestInsertIncludeSorted:
    """Tests for _insert_include_sorted."""

    def test_insert_at_end(self):
        content = "include 2026-01.journal\ninclude 2026-02.journal\n"
        result = _insert_include_sorted(content, "2026-03.journal")
        assert result == (
            "include 2026-01.journal\n"
            "include 2026-02.journal\n"
            "include 2026-03.journal\n"
        )

    def test_insert_at_beginning(self):
        content = "include 2026-02.journal\ninclude 2026-03.journal\n"
        result = _insert_include_sorted(content, "2026-01.journal")
        assert result == (
            "include 2026-01.journal\n"
            "include 2026-02.journal\n"
            "include 2026-03.journal\n"
        )

    def test_insert_in_middle(self):
        content = "include 2026-01.journal\ninclude 2026-03.journal\n"
        result = _insert_include_sorted(content, "2026-02.journal")
        assert result == (
            "include 2026-01.journal\n"
            "include 2026-02.journal\n"
            "include 2026-03.journal\n"
        )

    def test_preserves_non_date_includes(self):
        content = (
            "; Main journal\n"
            "\n"
            "include 2026-01.journal\n"
            "include 2026-02.journal\n"
        )
        result = _insert_include_sorted(content, "2026-03.journal")
        assert "include 2026-03.journal\n" in result
        assert "; Main journal\n" in result
        # Verify order of date includes
        lines = result.splitlines()
        date_includes = [line for line in lines if "20" in line and ".journal" in line]
        assert date_includes == [
            "include 2026-01.journal",
            "include 2026-02.journal",
            "include 2026-03.journal",
        ]


# ---------------------------------------------------------------------------
# Integration tests for append_transaction routing
# ---------------------------------------------------------------------------


class TestAppendTransactionRouting:
    """Tests for append_transaction's sub-journal routing logic."""

    def test_routes_to_existing_subjournal(self, tmp_journal_with_includes: Path):
        """A Feb transaction is routed to the existing 2026-02.journal."""
        main = tmp_journal_with_includes
        main_original = main.read_text()
        feb_file = main.parent / "2026-02.journal"

        txn = _make_transaction("2026-02-20", "Coffee beans")
        append_transaction(main, txn)

        # Main journal must not be modified
        assert main.read_text() == main_original
        # Transaction should be in the Feb sub-journal
        assert "Coffee beans" in feb_file.read_text()
        # Visible via hledger
        all_txns = load_transactions(main)
        assert any(t.description == "Coffee beans" for t in all_txns)

    def test_creates_new_subjournal(self, tmp_journal_with_includes: Path):
        """An Apr transaction creates 2026-04.journal and adds its include."""
        main = tmp_journal_with_includes
        apr_file = main.parent / "2026-04.journal"
        assert not apr_file.exists()

        txn = _make_transaction("2026-04-10", "April groceries")
        append_transaction(main, txn)

        assert apr_file.exists()
        assert "April groceries" in apr_file.read_text()
        assert "include 2026-04.journal" in main.read_text()

    def test_new_include_is_sorted(self, tmp_journal_with_includes: Path):
        """The new include directive is inserted in chronological order."""
        main = tmp_journal_with_includes

        txn = _make_transaction("2026-04-10", "April groceries")
        append_transaction(main, txn)

        includes = _find_date_includes(main.read_text())
        assert includes == [
            "2026-01.journal", "2026-02.journal", "2026-03.journal", "2026-04.journal",
        ]

    def test_fallback_no_date_includes(self, tmp_journal: Path, new_transaction: Transaction):
        """Without date-based includes, appends directly to the main journal (legacy)."""
        original = load_transactions(tmp_journal)
        append_transaction(tmp_journal, new_transaction)
        updated = load_transactions(tmp_journal)
        assert len(updated) == len(original) + 1
        assert "Rent payment" in tmp_journal.read_text()

    def test_no_backup_left_routing_existing(self, tmp_journal_with_includes: Path):
        """No .bak files remain after routing to an existing sub-journal."""
        main = tmp_journal_with_includes
        txn = _make_transaction("2026-02-20", "Coffee beans")
        append_transaction(main, txn)

        bak_files = list(main.parent.glob("*.bak"))
        assert bak_files == []

    def test_no_backup_left_creating_new(self, tmp_journal_with_includes: Path):
        """No .bak files remain after creating a new sub-journal."""
        main = tmp_journal_with_includes
        txn = _make_transaction("2026-04-10", "April groceries")
        append_transaction(main, txn)

        bak_files = list(main.parent.glob("*.bak"))
        assert bak_files == []

    def test_validation_failure_restores_existing_subjournal(
        self, tmp_journal_with_includes: Path, monkeypatch
    ):
        """On validation failure, the existing sub-journal is restored."""
        main = tmp_journal_with_includes
        feb_file = main.parent / "2026-02.journal"
        feb_original = feb_file.read_text()
        main_original = main.read_text()

        def _fail_check(file):
            raise HledgerError("journal invalid")

        monkeypatch.setattr("hledger_textual.journal.check_journal", _fail_check)

        txn = _make_transaction("2026-02-20", "Coffee beans")
        with pytest.raises(JournalError, match="validation failed"):
            append_transaction(main, txn)

        assert feb_file.read_text() == feb_original
        assert main.read_text() == main_original
        bak_files = list(main.parent.glob("*.bak"))
        assert bak_files == []

    def test_validation_failure_removes_new_subjournal(
        self, tmp_journal_with_includes: Path, monkeypatch
    ):
        """On validation failure, the new sub-journal is removed and main is restored."""
        main = tmp_journal_with_includes
        main_original = main.read_text()
        apr_file = main.parent / "2026-04.journal"

        def _fail_check(file):
            raise HledgerError("journal invalid")

        monkeypatch.setattr("hledger_textual.journal.check_journal", _fail_check)

        txn = _make_transaction("2026-04-10", "April groceries")
        with pytest.raises(JournalError, match="validation failed"):
            append_transaction(main, txn)

        assert not apr_file.exists()
        assert main.read_text() == main_original
        bak_files = list(main.parent.glob("*.bak"))
        assert bak_files == []

    def test_routed_transaction_visible_via_hledger(self, tmp_journal_with_includes: Path):
        """A routed transaction is visible via hledger print from the main journal."""
        main = tmp_journal_with_includes
        original_count = len(load_transactions(main))

        txn = _make_transaction("2026-04-10", "April groceries")
        append_transaction(main, txn)

        all_txns = load_transactions(main)
        assert len(all_txns) == original_count + 1
        assert any(t.description == "April groceries" for t in all_txns)


# ---------------------------------------------------------------------------
# Unit tests for glob routing helpers (no hledger required)
# ---------------------------------------------------------------------------


class TestDetectRoutingStrategy:
    """Tests for _detect_routing_strategy."""

    def test_detects_glob_strategy(self):
        content = "include budget.journal\n\ninclude 2026/*.journal\n"
        strategy, matches = _detect_routing_strategy(content)
        assert strategy == RoutingStrategy.GLOB
        assert matches == ["2026"]

    def test_detects_flat_strategy(self):
        content = "include 2026-01.journal\ninclude 2026-02.journal\n"
        strategy, matches = _detect_routing_strategy(content)
        assert strategy == RoutingStrategy.FLAT
        assert matches == ["2026-01.journal", "2026-02.journal"]

    def test_detects_fallback_strategy(self):
        content = "include budget.journal\n\n2026-01-01 Test\n    expenses  €10\n    assets\n"
        strategy, matches = _detect_routing_strategy(content)
        assert strategy == RoutingStrategy.FALLBACK
        assert matches == []

    def test_empty_content(self):
        strategy, matches = _detect_routing_strategy("")
        assert strategy == RoutingStrategy.FALLBACK
        assert matches == []

    def test_glob_priority_over_flat(self):
        """When both glob and flat includes exist, glob wins."""
        content = (
            "include 2026/*.journal\n"
            "include 2025-12.journal\n"
        )
        strategy, matches = _detect_routing_strategy(content)
        assert strategy == RoutingStrategy.GLOB
        assert "2026" in matches

    def test_leading_whitespace_glob(self):
        content = "  include 2026/*.journal\n"
        strategy, matches = _detect_routing_strategy(content)
        assert strategy == RoutingStrategy.GLOB
        assert matches == ["2026"]

    def test_multiple_glob_years(self):
        content = "include 2025/*.journal\ninclude 2026/*.journal\n"
        strategy, matches = _detect_routing_strategy(content)
        assert strategy == RoutingStrategy.GLOB
        assert matches == ["2025", "2026"]


class TestInsertGlobIncludeSorted:
    """Tests for _insert_glob_include_sorted."""

    def test_insert_at_end(self):
        content = "include 2025/*.journal\ninclude 2026/*.journal\n"
        result = _insert_glob_include_sorted(content, "2027/*.journal")
        assert result == (
            "include 2025/*.journal\n"
            "include 2026/*.journal\n"
            "include 2027/*.journal\n"
        )

    def test_insert_at_beginning(self):
        content = "include 2026/*.journal\ninclude 2027/*.journal\n"
        result = _insert_glob_include_sorted(content, "2025/*.journal")
        assert result == (
            "include 2025/*.journal\n"
            "include 2026/*.journal\n"
            "include 2027/*.journal\n"
        )

    def test_insert_in_middle(self):
        content = "include 2025/*.journal\ninclude 2027/*.journal\n"
        result = _insert_glob_include_sorted(content, "2026/*.journal")
        assert result == (
            "include 2025/*.journal\n"
            "include 2026/*.journal\n"
            "include 2027/*.journal\n"
        )

    def test_no_existing_globs(self):
        content = "include budget.journal\n"
        result = _insert_glob_include_sorted(content, "2026/*.journal")
        assert result == "include budget.journal\ninclude 2026/*.journal\n"

    def test_preserves_non_glob_content(self):
        content = (
            "; Main journal\n"
            "\n"
            "include budget.journal\n"
            "\n"
            "include 2026/*.journal\n"
        )
        result = _insert_glob_include_sorted(content, "2027/*.journal")
        assert "include 2027/*.journal\n" in result
        assert "; Main journal\n" in result
        assert "include budget.journal\n" in result


# ---------------------------------------------------------------------------
# Integration tests for glob-based append_transaction routing
# ---------------------------------------------------------------------------


class TestAppendTransactionGlobRouting:
    """Tests for append_transaction's glob-based sub-journal routing."""

    def test_routes_to_existing_month_file(self, tmp_journal_with_glob_includes: Path):
        """A Feb transaction is routed to the existing 2026/02.journal."""
        main = tmp_journal_with_glob_includes
        main_original = main.read_text()
        feb_file = main.parent / "2026" / "02.journal"

        txn = _make_transaction("2026-02-20", "Coffee beans")
        append_transaction(main, txn)

        # Main journal must not be modified
        assert main.read_text() == main_original
        # Transaction should be in the Feb sub-journal
        assert "Coffee beans" in feb_file.read_text()
        # Visible via hledger
        all_txns = load_transactions(main)
        assert any(t.description == "Coffee beans" for t in all_txns)

    def test_creates_new_month_file_in_existing_year(
        self, tmp_journal_with_glob_includes: Path
    ):
        """An Apr transaction creates 2026/04.journal; main unchanged (glob covers it)."""
        main = tmp_journal_with_glob_includes
        main_original = main.read_text()
        apr_file = main.parent / "2026" / "04.journal"
        assert not apr_file.exists()

        txn = _make_transaction("2026-04-10", "April groceries")
        append_transaction(main, txn)

        assert apr_file.exists()
        assert "April groceries" in apr_file.read_text()
        # Main journal must NOT be modified — glob already covers new files
        assert main.read_text() == main_original

    def test_creates_new_year_dir_and_glob_include(
        self, tmp_journal_with_glob_includes: Path
    ):
        """A 2027 transaction creates 2027/ dir, 2027/01.journal, and adds include."""
        main = tmp_journal_with_glob_includes
        year_dir = main.parent / "2027"
        jan_file = year_dir / "01.journal"
        assert not year_dir.exists()

        txn = _make_transaction("2027-01-15", "New year groceries")
        append_transaction(main, txn)

        assert year_dir.is_dir()
        assert jan_file.exists()
        assert "New year groceries" in jan_file.read_text()
        assert "include 2027/*.journal" in main.read_text()

    def test_new_glob_include_is_sorted(self, tmp_journal_with_glob_includes: Path):
        """The new glob include directive is inserted in sorted order."""
        main = tmp_journal_with_glob_includes

        txn = _make_transaction("2027-01-15", "New year groceries")
        append_transaction(main, txn)

        glob_years = _find_glob_includes(main.read_text())
        assert glob_years == ["2026", "2027"]

    def test_no_backup_left_routing_existing_month(
        self, tmp_journal_with_glob_includes: Path
    ):
        """No .bak files remain after routing to an existing month file."""
        main = tmp_journal_with_glob_includes
        txn = _make_transaction("2026-02-20", "Coffee beans")
        append_transaction(main, txn)

        bak_files = list(main.parent.rglob("*.bak"))
        assert bak_files == []

    def test_no_backup_left_creating_new_month(
        self, tmp_journal_with_glob_includes: Path
    ):
        """No .bak files remain after creating a new month file."""
        main = tmp_journal_with_glob_includes
        txn = _make_transaction("2026-04-10", "April groceries")
        append_transaction(main, txn)

        bak_files = list(main.parent.rglob("*.bak"))
        assert bak_files == []

    def test_no_backup_left_creating_new_year(
        self, tmp_journal_with_glob_includes: Path
    ):
        """No .bak files remain after creating a new year directory."""
        main = tmp_journal_with_glob_includes
        txn = _make_transaction("2027-01-15", "New year groceries")
        append_transaction(main, txn)

        bak_files = list(main.parent.rglob("*.bak"))
        assert bak_files == []

    def test_validation_failure_restores_existing_month(
        self, tmp_journal_with_glob_includes: Path, monkeypatch
    ):
        """On validation failure, the existing month file is restored."""
        main = tmp_journal_with_glob_includes
        feb_file = main.parent / "2026" / "02.journal"
        feb_original = feb_file.read_text()
        main_original = main.read_text()

        def _fail_check(file):
            raise HledgerError("journal invalid")

        monkeypatch.setattr("hledger_textual.journal.check_journal", _fail_check)

        txn = _make_transaction("2026-02-20", "Coffee beans")
        with pytest.raises(JournalError, match="validation failed"):
            append_transaction(main, txn)

        assert feb_file.read_text() == feb_original
        assert main.read_text() == main_original
        bak_files = list(main.parent.rglob("*.bak"))
        assert bak_files == []

    def test_validation_failure_removes_new_month_file(
        self, tmp_journal_with_glob_includes: Path, monkeypatch
    ):
        """On validation failure, the new month file is removed."""
        main = tmp_journal_with_glob_includes
        main_original = main.read_text()
        apr_file = main.parent / "2026" / "04.journal"

        def _fail_check(file):
            raise HledgerError("journal invalid")

        monkeypatch.setattr("hledger_textual.journal.check_journal", _fail_check)

        txn = _make_transaction("2026-04-10", "April groceries")
        with pytest.raises(JournalError, match="validation failed"):
            append_transaction(main, txn)

        assert not apr_file.exists()
        # Main journal must not be modified (glob already covers new files)
        assert main.read_text() == main_original

    def test_validation_failure_reverts_new_year(
        self, tmp_journal_with_glob_includes: Path, monkeypatch
    ):
        """On validation failure, new year dir is removed and main is restored."""
        main = tmp_journal_with_glob_includes
        main_original = main.read_text()
        year_dir = main.parent / "2027"

        def _fail_check(file):
            raise HledgerError("journal invalid")

        monkeypatch.setattr("hledger_textual.journal.check_journal", _fail_check)

        txn = _make_transaction("2027-01-15", "New year groceries")
        with pytest.raises(JournalError, match="validation failed"):
            append_transaction(main, txn)

        assert not year_dir.exists()
        assert main.read_text() == main_original
        bak_files = list(main.parent.rglob("*.bak"))
        assert bak_files == []

    def test_routed_transaction_visible_via_hledger(
        self, tmp_journal_with_glob_includes: Path
    ):
        """A routed transaction is visible via hledger print from the main journal."""
        main = tmp_journal_with_glob_includes
        original_count = len(load_transactions(main))

        txn = _make_transaction("2026-04-10", "April groceries")
        append_transaction(main, txn)

        all_txns = load_transactions(main)
        assert len(all_txns) == original_count + 1
        assert any(t.description == "April groceries" for t in all_txns)


class TestGlobSubJournalOperations:
    """Tests for replace/delete on transactions living in glob sub-journals."""

    def test_replace_in_glob_sub_journal(
        self, tmp_journal_with_glob_includes: Path, new_transaction: Transaction
    ):
        """Replace a transaction in a glob sub-journal; main journal stays untouched."""
        main = tmp_journal_with_glob_includes
        main_original = main.read_text()
        txns = load_transactions(main)
        original_count = len(txns)

        jan_txn = next(t for t in txns if t.description == "Grocery shopping")

        replace_transaction(main, jan_txn, new_transaction)

        updated = load_transactions(main)
        assert len(updated) == original_count
        descriptions = [t.description for t in updated]
        assert "Rent payment" in descriptions
        assert "Grocery shopping" not in descriptions
        assert main.read_text() == main_original

    def test_delete_from_glob_sub_journal(self, tmp_journal_with_glob_includes: Path):
        """Delete a transaction from a glob sub-journal; main journal stays untouched."""
        main = tmp_journal_with_glob_includes
        main_original = main.read_text()
        txns = load_transactions(main)
        original_count = len(txns)

        feb_txn = next(t for t in txns if t.description == "Electricity bill")

        delete_transaction(main, feb_txn)

        updated = load_transactions(main)
        assert len(updated) == original_count - 1
        descriptions = [t.description for t in updated]
        assert "Electricity bill" not in descriptions
        assert main.read_text() == main_original


class TestEuropeanFormatPreservation:
    """Regression tests for #109: European amount format preserved after replace_transaction.

    When a transaction is loaded from a journal that uses European number formatting
    (dot as thousands separator, comma as decimal mark, e.g. €3.000,00) and is then
    written back via replace_transaction, the file must still contain European-style
    amounts.
    """

    @pytest.fixture
    def european_journal(self, tmp_path: Path, european_journal_path: Path) -> Path:
        """A temporary mutable copy of the European-format fixture journal."""
        dest = tmp_path / "european.journal"
        shutil.copy2(european_journal_path, dest)
        return dest

    def test_replace_preserves_european_thousands_separator(
        self, european_journal: Path
    ):
        """Amounts with dot-thousands stay dot-thousands after replace_transaction."""
        txns = load_transactions(european_journal)
        salary = next(t for t in txns if t.description == "Salary")

        toggled = Transaction(
            index=salary.index,
            date=salary.date,
            description=salary.description,
            status=TransactionStatus.CLEARED,
            postings=salary.postings,
            source_pos=salary.source_pos,
        )

        replace_transaction(european_journal, salary, toggled)

        content = european_journal.read_text(encoding="utf-8")
        assert "€3.000,00" in content, "European thousands separator must be preserved"

    def test_replace_preserves_european_decimal_mark(
        self, european_journal: Path
    ):
        """Amounts with comma-decimal stay comma-decimal after replace_transaction."""
        txns = load_transactions(european_journal)
        groceries = next(t for t in txns if t.description == "Groceries")

        toggled = Transaction(
            index=groceries.index,
            date=groceries.date,
            description=groceries.description,
            status=TransactionStatus.CLEARED,
            postings=groceries.postings,
            source_pos=groceries.source_pos,
        )

        replace_transaction(european_journal, groceries, toggled)

        content = european_journal.read_text(encoding="utf-8")
        assert "€150,00" in content, "European decimal mark must be preserved"

    def test_replace_does_not_introduce_dot_decimal(
        self, european_journal: Path
    ):
        """Replacing a European transaction must not produce US-style dot decimals."""
        txns = load_transactions(european_journal)
        salary = next(t for t in txns if t.description == "Salary")

        replaced = Transaction(
            index=salary.index,
            date=salary.date,
            description=salary.description,
            status=TransactionStatus.PENDING,
            postings=salary.postings,
            source_pos=salary.source_pos,
        )

        replace_transaction(european_journal, salary, replaced)

        content = european_journal.read_text(encoding="utf-8")
        assert "3000.00" not in content, "US-style dot decimal must not appear"
        assert "3.000.00" not in content, "Malformed double-dot format must not appear"
