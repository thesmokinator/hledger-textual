"""Tests for humanize_error (issue #158)."""

from __future__ import annotations

from hledger_textual.csv_import import CsvImportError
from hledger_textual.error_messages import humanize_error
from hledger_textual.hledger import HledgerError
from hledger_textual.journal import JournalError


class TestHledgerErrors:
    """Mapping of hledger failures to actionable messages."""

    def test_missing_binary(self):
        """A missing hledger binary points at the install page."""
        title, body = humanize_error(
            HledgerError("hledger not found. Please install it: https://hledger.org")
        )
        assert title == "hledger not found"
        assert "hledger.org/install" in body

    def test_missing_journal(self):
        """A missing data file names the path."""
        title, body = humanize_error(
            HledgerError(
                'hledger command failed: hledger: Error: data file '
                '"/nonexistent/x.journal" was not found.'
            )
        )
        assert title == "Journal file not found"
        assert "/nonexistent/x.journal" in body

    def test_syntax_error_names_the_line(self):
        """A parse error extracts the line number and the explanation."""
        title, body = humanize_error(
            HledgerError(
                "hledger command failed: hledger: Error: /tmp/b.journal:2:23:\n"
                "  |\n"
                "2 |     expenses:food  abc\n"
                "  |                       ^\n"
                "unexpected newline"
            )
        )
        assert title == "Journal syntax error"
        assert "line 2" in body
        assert "unexpected newline" in body

    def test_permission_denied(self):
        """Permission problems are surfaced as such."""
        title, body = humanize_error(
            HledgerError("hledger command failed: permission denied: /tmp/x.journal")
        )
        assert title == "Permission denied"
        assert "/tmp/x.journal" in body

    def test_unknown_hledger_error_keeps_the_message(self):
        """An unmapped hledger failure keeps its detail and invites a report."""
        title, body = humanize_error(
            HledgerError("hledger command failed: something odd happened")
        )
        assert title == "hledger error"
        assert "something odd happened" in body
        assert "open an issue" in body


class TestOtherErrors:
    """Mapping of filesystem and application errors."""

    def test_file_not_found(self):
        """A Python FileNotFoundError names the path."""
        title, body = humanize_error(FileNotFoundError(2, "No such file", "/tmp/a.csv"))
        assert title == "File not found"
        assert "/tmp/a.csv" in body

    def test_permission_error(self):
        """A Python PermissionError explains the fix."""
        title, body = humanize_error(PermissionError(13, "Denied", "/tmp/a.journal"))
        assert title == "Permission denied"
        assert "/tmp/a.journal" in body

    def test_journal_error(self):
        """Journal write failures are explained."""
        title, body = humanize_error(JournalError("Transaction was not found"))
        assert title == "Could not update the journal"
        assert "Transaction was not found" in body
        assert "writable" in body

    def test_csv_import_error(self):
        """CSV import failures keep their specific message."""
        title, body = humanize_error(CsvImportError("Missing amount column"))
        assert title == "CSV import failed"
        assert body == "Missing amount column"

    def test_unexpected_error(self):
        """Unknown errors fall back to the message plus a report hint."""
        title, body = humanize_error(RuntimeError("boom"))
        assert title == "Unexpected error"
        assert "boom" in body
        assert "open an issue" in body
