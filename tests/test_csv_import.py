"""Unit tests for the csv_import backend module."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from unittest.mock import MagicMock, patch

from hledger_textual.csv_import import (
    CsvImportError,
    _slugify,
    auto_detect_field_mapping,
    check_duplicates,
    delete_rules_file,
    detect_date_format,
    detect_header_row,
    detect_separator,
    execute_import,
    find_companion_rules,
    generate_rules_content,
    get_rules_dir,
    list_rules_files,
    parse_rules_file,
    preview_import,
    read_csv_preview,
    save_rules_file,
    validate_rules_content,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_CSV = FIXTURES / "sample_bank.csv"
SAMPLE_RULES = FIXTURES / "sample_bank.rules"

_has_hledger = shutil.which("hledger") is not None


# ---------------------------------------------------------------------------
# Auto-detection tests
# ---------------------------------------------------------------------------


class TestDetectSeparator:
    """Tests for detect_separator."""

    def test_comma_separated(self, tmp_path: Path) -> None:
        """Comma-separated CSV should detect ','."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        assert detect_separator(csv_file) == ","

    def test_semicolon_separated(self, tmp_path: Path) -> None:
        """Semicolon-separated CSV should detect ';'."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("a;b;c\n1;2;3\n", encoding="utf-8")
        assert detect_separator(csv_file) == ";"

    def test_tab_separated(self, tmp_path: Path) -> None:
        """Tab-separated CSV should detect tab."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("a\tb\tc\n1\t2\t3\n", encoding="utf-8")
        assert detect_separator(csv_file) == "\t"

    def test_fallback_on_bad_file(self, tmp_path: Path) -> None:
        """Non-existent file should fall back to ','."""
        assert detect_separator(tmp_path / "nonexistent.csv") == ","

    def test_sample_fixture(self) -> None:
        """The sample fixture should detect ','."""
        assert detect_separator(SAMPLE_CSV) == ","


class TestDetectDateFormat:
    """Tests for detect_date_format."""

    def test_iso_format(self) -> None:
        """ISO dates should return %Y-%m-%d."""
        assert detect_date_format(["2026-01-15", "2026-02-28"]) == "%Y-%m-%d"

    def test_european_format(self) -> None:
        """DD/MM/YYYY should be detected."""
        assert detect_date_format(["15/01/2026", "28/02/2026"]) == "%d/%m/%Y"

    def test_dot_format(self) -> None:
        """DD.MM.YYYY should be detected."""
        assert detect_date_format(["15.01.2026", "28.02.2026"]) == "%d.%m.%Y"

    def test_empty_samples(self) -> None:
        """Empty samples should return the default."""
        assert detect_date_format([]) == "%Y-%m-%d"

    def test_mixed_formats_fallback(self) -> None:
        """Inconsistent formats should fall back to default."""
        assert detect_date_format(["2026-01-15", "15/01/2026"]) == "%Y-%m-%d"


class TestDetectHeaderRow:
    """Tests for detect_header_row."""

    def test_has_header(self) -> None:
        """The sample fixture has a header row."""
        has_header, cols = detect_header_row(SAMPLE_CSV, ",")
        assert has_header is True
        assert "Date" in cols
        assert "Description" in cols

    def test_no_header(self, tmp_path: Path) -> None:
        """CSV starting with data should detect no header."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("2026-01-01,Groceries,-50.00\n", encoding="utf-8")
        has_header, cols = detect_header_row(csv_file, ",")
        assert has_header is False
        assert cols[0] == "Col 1"

    def test_empty_file(self, tmp_path: Path) -> None:
        """Empty CSV should return no header and empty columns."""
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("", encoding="utf-8")
        has_header, cols = detect_header_row(csv_file, ",")
        assert has_header is False
        assert cols == []


class TestAutoDetectFieldMapping:
    """Tests for auto_detect_field_mapping."""

    def test_by_column_names(self) -> None:
        """Column names like 'Date', 'Description', 'Amount' should be mapped."""
        names = ["Date", "Description", "Amount", "Balance"]
        samples = [["01/01/2026", "Opening Balance", "5000.00", "5000.00"]]
        mapping = auto_detect_field_mapping(names, samples)
        assert mapping[0] == "date"
        assert mapping[1] == "description"
        assert mapping[2] == "amount"
        assert mapping[3] == ""  # Balance doesn't map to a standard field

    def test_by_sample_values(self) -> None:
        """Generic column names should still be mapped via sample values."""
        names = ["Col 1", "Col 2", "Col 3"]
        samples = [
            ["2026-01-01", "Grocery shopping at the market", "-45.00"],
            ["2026-01-02", "Netflix monthly subscription", "-15.99"],
        ]
        mapping = auto_detect_field_mapping(names, samples)
        assert mapping[0] == "date"
        assert mapping[2] == "amount"

    def test_credit_debit_columns(self) -> None:
        """Columns named 'Credit' and 'Debit' should map to amount-in/out."""
        names = ["Date", "Details", "Debit", "Credit"]
        samples = [["01/01/2026", "Groceries", "50.00", ""]]
        mapping = auto_detect_field_mapping(names, samples)
        assert mapping[2] == "amount-out"
        assert mapping[3] == "amount-in"


class TestReadCsvPreview:
    """Tests for read_csv_preview."""

    def test_reads_data_rows(self) -> None:
        """Should read data rows, skipping header."""
        rows = read_csv_preview(SAMPLE_CSV, ",", skip=1, max_rows=3)
        assert len(rows) == 3
        assert rows[0][1] == "Opening Balance"

    def test_respects_max_rows(self) -> None:
        """Should stop at max_rows."""
        rows = read_csv_preview(SAMPLE_CSV, ",", skip=1, max_rows=2)
        assert len(rows) == 2

    def test_no_skip(self) -> None:
        """Without skip, first row is the header."""
        rows = read_csv_preview(SAMPLE_CSV, ",", skip=0, max_rows=1)
        assert rows[0][0] == "Date"


# ---------------------------------------------------------------------------
# Rules file parsing & generation
# ---------------------------------------------------------------------------


class TestParseRulesFile:
    """Tests for parse_rules_file."""

    def test_parse_sample_rules(self) -> None:
        """Parsing the sample rules file should extract all metadata."""
        rules = parse_rules_file(SAMPLE_RULES)
        assert rules.name == "Sample Bank"
        assert rules.skip == 1
        assert rules.date_format == "%d/%m/%Y"
        assert rules.currency == "\u20ac"
        assert rules.account1 == "assets:bank:checking"
        assert len(rules.conditional_rules) == 12
        assert rules.conditional_rules[0] == (
            "whole foods|grocery store",
            "expenses:groceries",
        )

    def test_fields_parsed(self) -> None:
        """The fields directive should be parsed into a list."""
        rules = parse_rules_file(SAMPLE_RULES)
        assert "date" in rules.field_mapping
        assert "description" in rules.field_mapping
        assert "amount" in rules.field_mapping


class TestParseRulesFileEdgeCases:
    """Edge-case tests for parse_rules_file."""

    def _write_rules(self, tmp_path: Path, content: str, stem: str = "mybank") -> Path:
        path = tmp_path / f"{stem}.rules"
        path.write_text(content, encoding="utf-8")
        return path

    def test_tab_separator_tab_keyword(self, tmp_path: Path) -> None:
        """``separator tab`` should be stored as a real tab character."""
        rules = parse_rules_file(self._write_rules(tmp_path, "separator tab\n"))
        assert rules.separator == "\t"

    def test_tab_separator_backslash_t(self, tmp_path: Path) -> None:
        r"""``separator \t`` literal should be stored as a real tab character."""
        rules = parse_rules_file(self._write_rules(tmp_path, r"separator \t" + "\n"))
        assert rules.separator == "\t"

    def test_european_dot_date_format(self, tmp_path: Path) -> None:
        """European dot-separated date format should be stored verbatim."""
        rules = parse_rules_file(
            self._write_rules(tmp_path, "date-format %d.%m.%Y\n")
        )
        assert rules.date_format == "%d.%m.%Y"

    def test_skip_bare_defaults_to_one(self, tmp_path: Path) -> None:
        """``skip`` without a number should default to 1."""
        rules = parse_rules_file(self._write_rules(tmp_path, "skip\n"))
        assert rules.skip == 1

    def test_conditional_without_account2_skipped(self, tmp_path: Path) -> None:
        """A conditional block with no ``account2`` should not appear in results."""
        content = "if groceries\n  ; just a comment\n"
        rules = parse_rules_file(self._write_rules(tmp_path, content))
        assert rules.conditional_rules == []

    def test_name_falls_back_to_stem(self, tmp_path: Path) -> None:
        """When no ``; name:`` comment is present the stem is used as name."""
        rules = parse_rules_file(self._write_rules(tmp_path, "skip 1\n", stem="fallback-bank"))
        assert rules.name == "fallback-bank"

    def test_multiple_conditionals_all_captured(self, tmp_path: Path) -> None:
        """Multiple conditional blocks should all be captured in order."""
        content = textwrap.dedent("""\
            if groceries
              account2 expenses:groceries
            if netflix
              account2 expenses:entertainment
            if pharmacy|drugstore
              account2 expenses:health
        """)
        rules = parse_rules_file(self._write_rules(tmp_path, content))
        assert len(rules.conditional_rules) == 3
        assert rules.conditional_rules[0] == ("groceries", "expenses:groceries")
        assert rules.conditional_rules[2] == ("pharmacy|drugstore", "expenses:health")


class TestGenerateRulesContent:
    """Tests for generate_rules_content."""

    def test_roundtrip(self) -> None:
        """Generate → parse should preserve key metadata."""
        content = generate_rules_content(
            name="Test Bank",
            separator=";",
            date_format="%d/%m/%Y",
            skip=1,
            field_mapping=["date", "description", "amount", ""],
            currency="EUR",
            account1="assets:bank:test",
            conditional_rules=[("groceries", "expenses:food")],
        )
        assert "; name: Test Bank" in content
        assert "skip 1" in content
        assert "separator ;" in content
        assert "date-format %d/%m/%Y" in content
        assert "fields date, description, amount, " in content
        assert "currency EUR" in content
        assert "account1 assets:bank:test" in content
        assert "if groceries" in content
        assert "account2 expenses:food" in content

    def test_comma_separator_omitted(self) -> None:
        """Comma separator (default) should not be written."""
        content = generate_rules_content(
            name="X", separator=",", date_format="", skip=0,
            field_mapping=[], currency="", account1="", conditional_rules=[],
        )
        assert "separator" not in content

    def test_tab_separator(self) -> None:
        r"""Tab separator should be written as \\t."""
        content = generate_rules_content(
            name="X", separator="\t", date_format="", skip=0,
            field_mapping=[], currency="", account1="", conditional_rules=[],
        )
        assert "separator \\t" in content


class TestSaveAndDeleteRulesFile:
    """Tests for save_rules_file and delete_rules_file."""

    def test_save_creates_file(self, tmp_path: Path) -> None:
        """Saving should create a .rules file with the right name."""
        path = save_rules_file(tmp_path, "My Bank", "content here")
        assert path.exists()
        assert path.name == "my-bank.rules"
        assert path.read_text(encoding="utf-8") == "content here"

    def test_delete_removes_file(self, tmp_path: Path) -> None:
        """Deleting should remove the file."""
        path = save_rules_file(tmp_path, "To Delete", "x")
        assert path.exists()
        delete_rules_file(path)
        assert not path.exists()

    def test_delete_nonexistent_no_error(self, tmp_path: Path) -> None:
        """Deleting a nonexistent file should not raise."""
        delete_rules_file(tmp_path / "nonexistent.rules")


class TestListRulesFiles:
    """Tests for list_rules_files."""

    def test_lists_all_rules(self, tmp_path: Path) -> None:
        """Should find all .rules files in the directory."""
        save_rules_file(tmp_path, "Bank A", "; name: Bank A\naccount1 a\n")
        save_rules_file(tmp_path, "Bank B", "; name: Bank B\naccount1 b\n")
        (tmp_path / "notarules.txt").write_text("ignored")
        rules = list_rules_files(tmp_path)
        assert len(rules) == 2
        names = {r.name for r in rules}
        assert "Bank A" in names
        assert "Bank B" in names

    def test_empty_dir(self, tmp_path: Path) -> None:
        """Empty directory should return empty list."""
        assert list_rules_files(tmp_path) == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        """Nonexistent directory should return empty list."""
        assert list_rules_files(tmp_path / "nope") == []


class TestFindCompanionRules:
    """Tests for find_companion_rules."""

    def test_companion_found(self, tmp_path: Path) -> None:
        """Returns path when bank.csv.rules exists next to bank.csv."""
        csv_file = tmp_path / "bank.csv"
        csv_file.write_text("date,amount\n")
        rules_file = tmp_path / "bank.csv.rules"
        rules_file.write_text("; rules\n")
        assert find_companion_rules(csv_file) == rules_file

    def test_companion_not_found(self, tmp_path: Path) -> None:
        """Returns None when no companion rules file exists."""
        csv_file = tmp_path / "bank.csv"
        csv_file.write_text("date,amount\n")
        assert find_companion_rules(csv_file) is None

    def test_ignores_rules_without_csv_infix(self, tmp_path: Path) -> None:
        """bank.rules without the .csv infix is not a companion."""
        csv_file = tmp_path / "bank.csv"
        csv_file.write_text("date,amount\n")
        (tmp_path / "bank.rules").write_text("; rules\n")
        assert find_companion_rules(csv_file) is None

    def test_companion_in_same_directory(self, tmp_path: Path) -> None:
        """Companion file must live in the same directory as the CSV."""
        subdir = tmp_path / "sub"
        subdir.mkdir()
        csv_file = subdir / "export.csv"
        csv_file.write_text("date,amount\n")
        (tmp_path / "export.csv.rules").write_text("; rules\n")  # wrong dir
        assert find_companion_rules(csv_file) is None


class TestGetRulesDir:
    """Tests for get_rules_dir."""

    def test_default_rules_dir(self, tmp_path: Path) -> None:
        """Without config, should use journal_dir/rules/."""
        journal = tmp_path / "test.journal"
        journal.write_text("")
        rules_dir = get_rules_dir(journal)
        assert rules_dir == tmp_path / "rules"
        assert rules_dir.is_dir()


class TestSlugify:
    """Tests for _slugify."""

    def test_basic(self) -> None:
        """Basic text should be lowercased and hyphenated."""
        assert _slugify("My Bank Account") == "my-bank-account"

    def test_special_chars(self) -> None:
        """Special characters should be removed."""
        assert _slugify("Bank (EUR)!") == "bank-eur"

    def test_empty(self) -> None:
        """Empty string should return 'rules'."""
        assert _slugify("") == "rules"


# ---------------------------------------------------------------------------
# Integration tests (require hledger)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_hledger, reason="hledger not installed")
class TestPreviewImport:
    """Integration tests for preview_import (require hledger)."""

    def test_preview_sample(self) -> None:
        """Should parse the sample CSV using the sample rules."""
        txns = preview_import(SAMPLE_CSV, SAMPLE_RULES)
        assert len(txns) == 26
        assert txns[0].description == "Opening Balance"
        assert txns[1].description == "Whole Foods Market"

    def test_preview_bad_rules(self, tmp_path: Path) -> None:
        """Invalid rules should raise CsvImportError."""
        bad_rules = tmp_path / "bad.rules"
        bad_rules.write_text("this is not valid\n", encoding="utf-8")
        with pytest.raises(CsvImportError):
            preview_import(SAMPLE_CSV, bad_rules)


@pytest.mark.skipif(not _has_hledger, reason="hledger not installed")
class TestValidateRulesContent:
    """Integration tests for validate_rules_content (require hledger)."""

    def test_valid_content(self) -> None:
        """Valid rules content should return None."""
        content = SAMPLE_RULES.read_text(encoding="utf-8")
        result = validate_rules_content(SAMPLE_CSV, content)
        assert result is None

    def test_invalid_content(self) -> None:
        """Invalid rules content should return an error message."""
        result = validate_rules_content(SAMPLE_CSV, "nonsense rules here\n")
        assert result is not None


@pytest.mark.skipif(not _has_hledger, reason="hledger not installed")
class TestCheckDuplicates:
    """Integration tests for check_duplicates (require hledger)."""

    def test_all_new_against_empty_journal(self, tmp_path: Path) -> None:
        """All transactions should be new against an empty journal."""
        journal = tmp_path / "test.journal"
        journal.write_text("", encoding="utf-8")
        txns = preview_import(SAMPLE_CSV, SAMPLE_RULES)
        new, dupes = check_duplicates(txns, journal)
        assert len(new) == 26
        assert len(dupes) == 0

    def test_detects_duplicates(self, tmp_path: Path) -> None:
        """Transactions already in journal should be flagged as duplicates."""
        from hledger_textual.journal import append_transaction

        journal = tmp_path / "test.journal"
        journal.write_text("", encoding="utf-8")
        txns = preview_import(SAMPLE_CSV, SAMPLE_RULES)

        # Import first transaction manually
        append_transaction(journal, txns[0])

        # Check duplicates
        new, dupes = check_duplicates(txns, journal)
        assert len(dupes) >= 1
        assert len(new) == len(txns) - len(dupes)


# ---------------------------------------------------------------------------
# execute_import — batch import with error handling
# ---------------------------------------------------------------------------


class TestExecuteImport:
    """Tests for execute_import batch error handling (no hledger required)."""

    def _make_txn(self, description: str = "Coffee shop") -> MagicMock:
        txn = MagicMock()
        txn.description = description
        return txn

    def test_returns_import_count(self, tmp_path: Path) -> None:
        """Should return the number of successfully appended transactions."""
        journal = tmp_path / "test.journal"
        journal.write_text("", encoding="utf-8")
        txns = [self._make_txn("Tx1"), self._make_txn("Tx2")]

        with (
            patch("hledger_textual.csv_import.preview_import", return_value=txns),
            patch("hledger_textual.csv_import.check_duplicates", return_value=(txns, [])),
            patch("hledger_textual.journal.append_transaction"),
        ):
            count = execute_import(SAMPLE_CSV, SAMPLE_RULES, journal)

        assert count == 2

    def test_journal_error_raises_csv_import_error(self, tmp_path: Path) -> None:
        """A JournalError during append should be wrapped as CsvImportError."""
        from hledger_textual.journal import JournalError

        journal = tmp_path / "test.journal"
        journal.write_text("", encoding="utf-8")
        txn = self._make_txn("Bad Transaction")

        with (
            patch("hledger_textual.csv_import.preview_import", return_value=[txn]),
            patch("hledger_textual.csv_import.check_duplicates", return_value=([txn], [])),
            patch(
                "hledger_textual.journal.append_transaction",
                side_effect=JournalError("disk full"),
            ),
        ):
            with pytest.raises(CsvImportError, match="Bad Transaction"):
                execute_import(SAMPLE_CSV, SAMPLE_RULES, journal)

    def test_preview_error_propagates(self, tmp_path: Path) -> None:
        """A CsvImportError from preview_import should propagate unchanged."""
        journal = tmp_path / "test.journal"
        journal.write_text("", encoding="utf-8")

        with patch(
            "hledger_textual.csv_import.preview_import",
            side_effect=CsvImportError("hledger failed: bad rules"),
        ):
            with pytest.raises(CsvImportError, match="hledger failed"):
                execute_import(SAMPLE_CSV, SAMPLE_RULES, journal)

    def test_all_duplicates_returns_zero(self, tmp_path: Path) -> None:
        """When all transactions are duplicates, import count should be 0."""
        journal = tmp_path / "test.journal"
        journal.write_text("", encoding="utf-8")
        txns = [self._make_txn("Old Tx")]

        with (
            patch("hledger_textual.csv_import.preview_import", return_value=txns),
            patch("hledger_textual.csv_import.check_duplicates", return_value=([], txns)),
        ):
            count = execute_import(SAMPLE_CSV, SAMPLE_RULES, journal)

        assert count == 0
