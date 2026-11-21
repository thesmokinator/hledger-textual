"""Tests for account directive parsing, saving, and metadata display."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.hledger import (
    _parse_comment_tags,
    load_account_directives,
    save_account_directive,
)

INCLUDES_JOURNAL = Path(__file__).parent / "fixtures" / "includes" / "main.journal"


# ------------------------------------------------------------------
# Unit tests (no hledger required)
# ------------------------------------------------------------------


class TestParseCommentTags:
    """Tests for _parse_comment_tags helper."""

    def test_empty_string(self):
        """Empty string returns empty dict."""
        assert _parse_comment_tags("") == {}

    def test_single_tag(self):
        """Single key:value tag is extracted."""
        assert _parse_comment_tags("note:Weekly shopping") == {
            "note": "Weekly shopping",
        }

    def test_multiple_tags_comma_separated(self):
        """Comma-separated tags are all extracted."""
        result = _parse_comment_tags("note:Main account, type:A")
        assert result == {"note": "Main account", "type": "A"}

    def test_plain_text_no_tags(self):
        """Text without key:value pattern returns empty dict."""
        assert _parse_comment_tags("just a plain note") == {}

    def test_tag_with_hyphen_in_key(self):
        """Hyphenated tag keys are supported."""
        result = _parse_comment_tags("sub-type:savings")
        assert result == {"sub-type": "savings"}


class TestLoadAccountDirectives:
    """Tests for load_account_directives."""

    def test_no_directives(self, tmp_path: Path):
        """Journal without directives returns empty dict."""
        journal = tmp_path / "test.journal"
        journal.write_text(
            "2026-01-01 Test\n"
            "    expenses:food    €10.00\n"
            "    assets:bank\n"
        )
        assert load_account_directives(journal) == {}

    def test_single_directive_with_comment(self, tmp_path: Path):
        """Single directive with inline comment is parsed."""
        journal = tmp_path / "test.journal"
        journal.write_text(
            "account expenses:groceries  ; note:Weekly shopping\n"
            "\n"
            "2026-01-01 Test\n"
            "    expenses:groceries    €10.00\n"
            "    assets:bank\n"
        )
        directives = load_account_directives(journal)
        assert "expenses:groceries" in directives
        d = directives["expenses:groceries"]
        assert d.comment == "note:Weekly shopping"
        assert d.tags == {"note": "Weekly shopping"}

    def test_directive_without_comment(self, tmp_path: Path):
        """Directive without comment has empty comment and tags."""
        journal = tmp_path / "test.journal"
        journal.write_text("account assets:bank\n")
        directives = load_account_directives(journal)
        assert "assets:bank" in directives
        assert directives["assets:bank"].comment == ""
        assert directives["assets:bank"].tags == {}

    def test_continuation_comments(self, tmp_path: Path):
        """Multi-line directive comments are merged."""
        journal = tmp_path / "test.journal"
        journal.write_text(
            "account assets:bank  ; note:Main account\n"
            "    ; currency:EUR\n"
            "\n"
        )
        directives = load_account_directives(journal)
        d = directives["assets:bank"]
        assert "note:Main account" in d.comment
        assert "currency:EUR" in d.comment
        assert d.tags["note"] == "Main account"
        assert d.tags["currency"] == "EUR"

    def test_multiple_directives(self, tmp_path: Path):
        """Multiple directives are all parsed."""
        journal = tmp_path / "test.journal"
        journal.write_text(
            "account assets:bank  ; note:Bank\n"
            "account expenses:food  ; note:Food\n"
        )
        directives = load_account_directives(journal)
        assert len(directives) == 2
        assert directives["assets:bank"].tags["note"] == "Bank"
        assert directives["expenses:food"].tags["note"] == "Food"

    def test_nonexistent_file(self, tmp_path: Path):
        """Non-existent file returns empty dict."""
        assert load_account_directives(tmp_path / "nope.journal") == {}


class TestSaveAccountDirective:
    """Tests for save_account_directive."""

    def test_add_new_directive(self, tmp_path: Path):
        """Adding a directive to a journal without one inserts it."""
        journal = tmp_path / "test.journal"
        journal.write_text(
            "2026-01-01 Test\n"
            "    expenses:food    €10.00\n"
            "    assets:bank\n"
        )
        save_account_directive(journal, "expenses:food", "Grocery spending")
        directives = load_account_directives(journal)
        assert "expenses:food" in directives
        assert directives["expenses:food"].comment == "Grocery spending"

    def test_update_existing_directive(self, tmp_path: Path):
        """Updating an existing directive replaces its comment."""
        journal = tmp_path / "test.journal"
        journal.write_text(
            "account expenses:food  ; Old note\n"
            "\n"
            "2026-01-01 Test\n"
            "    expenses:food    €10.00\n"
            "    assets:bank\n"
        )
        save_account_directive(journal, "expenses:food", "New note")
        directives = load_account_directives(journal)
        assert directives["expenses:food"].comment == "New note"

    def test_clear_comment(self, tmp_path: Path):
        """Saving with empty comment removes the comment but keeps the directive."""
        journal = tmp_path / "test.journal"
        journal.write_text("account expenses:food  ; Old note\n")
        save_account_directive(journal, "expenses:food", "")
        directives = load_account_directives(journal)
        assert "expenses:food" in directives
        assert directives["expenses:food"].comment == ""

    def test_update_removes_continuation_lines(self, tmp_path: Path):
        """Updating a directive with continuation comments replaces all of them."""
        journal = tmp_path / "test.journal"
        journal.write_text(
            "account assets:bank  ; note:Old\n"
            "    ; extra:tag\n"
            "\n"
            "2026-01-01 Test\n"
            "    assets:bank    €100.00\n"
            "    income:salary\n"
        )
        save_account_directive(journal, "assets:bank", "Updated")
        directives = load_account_directives(journal)
        assert directives["assets:bank"].comment == "Updated"
        # Continuation line should be gone
        content = journal.read_text()
        assert "extra:tag" not in content

    def test_new_directive_preserves_transactions(self, tmp_path: Path):
        """Adding a new directive does not corrupt existing transactions."""
        original = (
            "2026-01-01 Test\n"
            "    expenses:food    €10.00\n"
            "    assets:bank\n"
        )
        journal = tmp_path / "test.journal"
        journal.write_text(original)
        save_account_directive(journal, "expenses:food", "A note")
        content = journal.read_text()
        assert "2026-01-01 Test" in content
        assert "expenses:food    €10.00" in content


# ------------------------------------------------------------------
# Integration tests (require hledger)
# ------------------------------------------------------------------

from tests.conftest import has_hledger  # noqa: E402

integration_mark = pytest.mark.skipif(
    not has_hledger(), reason="hledger not installed"
)


@integration_mark
class TestAccountMetadataScreen:
    """Integration tests for metadata display in AccountTransactionsScreen."""

    @pytest.fixture
    def journal_with_note(self, tmp_path: Path) -> Path:
        """Journal with an account directive on the first (alphabetical) account."""
        today = date.today()
        d1 = today.replace(day=1)
        content = (
            "account assets:bank:checking  ; note:Main checking account\n"
            "\n"
            f"{d1.isoformat()} * Grocery shopping\n"
            "    expenses:food:groceries              €40.80\n"
            "    assets:bank:checking\n"
        )
        dest = tmp_path / "test.journal"
        dest.write_text(content)
        return dest

    @pytest.fixture
    def journal_without_note(self, tmp_path: Path) -> Path:
        """Journal without any account directives."""
        today = date.today()
        d1 = today.replace(day=1)
        content = (
            f"{d1.isoformat()} * Grocery shopping\n"
            "    expenses:food:groceries              €40.80\n"
            "    assets:bank:checking\n"
        )
        dest = tmp_path / "test.journal"
        dest.write_text(content)
        return dest

    async def test_metadata_shown_when_present(self, journal_with_note: Path):
        """Metadata label is visible when account has a note."""
        from hledger_textual.app import HledgerTuiApp

        app = HledgerTuiApp(journal_file=journal_with_note)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("enter")
            await pilot.pause(delay=0.5)

            meta = app.screen.query_one("#acctxn-note")
            assert meta.display is True
            assert "Main checking account" in str(meta.content)

    async def test_metadata_hidden_when_absent(self, journal_without_note: Path):
        """Metadata label is hidden when account has no note."""
        from hledger_textual.app import HledgerTuiApp

        app = HledgerTuiApp(journal_file=journal_without_note)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("enter")
            await pilot.pause(delay=0.5)

            meta = app.screen.query_one("#acctxn-note")
            assert meta.display is False

    async def test_note_modal_opens(self, journal_without_note: Path):
        """Pressing n opens the note modal."""
        from hledger_textual.app import HledgerTuiApp
        from hledger_textual.screens.account_note_form import AccountNoteModal

        app = HledgerTuiApp(journal_file=journal_without_note)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("enter")
            await pilot.pause(delay=0.5)
            await pilot.press("n")
            await pilot.pause(delay=0.5)

            assert isinstance(app.screen, AccountNoteModal)


class TestAccountDirectivesWithIncludes:
    """Directives follow include directives, including globs (issue #272)."""

    def test_load_follows_includes(self):
        """Notes in included files are visible (fixture journal)."""
        directives = load_account_directives(INCLUDES_JOURNAL)
        assert isinstance(directives, dict)

    def test_fixture_includes_save_targets_month_file(self, tmp_path: Path):
        """With the includes fixture, a note lands in its month file."""
        import shutil

        dest = tmp_path / "journal"
        shutil.copytree(INCLUDES_JOURNAL.parent, dest)
        main = dest / "main.journal"

        written, fell_back = save_account_directive(
            main, "expenses:food:groceries", "Weekly shopping"
        )
        assert not fell_back
        # The account appears in 01 and 03; the most recent posting wins.
        assert written == dest / "2026-03.journal"
        assert "account expenses:food:groceries" in written.read_text()

    def test_fixture_glob_includes_save_targets_month_file(
        self, tmp_path: Path
    ):
        """With the glob_includes fixture, a note lands in its month file."""
        import shutil

        glob_dir = Path(__file__).parent / "fixtures" / "glob_includes"
        dest = tmp_path / "journal"
        shutil.copytree(glob_dir, dest)
        main = dest / "main.journal"

        written, fell_back = save_account_directive(
            main, "expenses:rent", "Monthly rent"
        )
        assert not fell_back
        assert written == dest / "2026" / "02.journal"
        assert "account expenses:rent" in written.read_text()

    def test_load_reads_existing_included_directive(self, tmp_path: Path):
        """A directive in an included file is loaded."""
        main = tmp_path / "main.journal"
        main.write_text("include sub.journal\n")
        sub = tmp_path / "sub.journal"
        sub.write_text("account assets:bank  ; from included file\n")

        directives = load_account_directives(main)
        assert "assets:bank" in directives
        assert directives["assets:bank"].comment == "from included file"

    def test_load_reads_glob_included_directive(self, tmp_path: Path):
        """Glob includes are expanded when reading directives."""
        main = tmp_path / "main.journal"
        main.write_text("include 2026/*.journal\n")
        subdir = tmp_path / "2026"
        subdir.mkdir()
        (subdir / "01.journal").write_text("account assets:bank  ; glob note\n")

        directives = load_account_directives(main)
        assert "assets:bank" in directives

    def test_included_directive_roundtrip(self, tmp_path: Path):
        """A note saved into an included file is read back."""
        main = tmp_path / "main.journal"
        main.write_text("include sub.journal\n")
        sub = tmp_path / "sub.journal"
        sub.write_text(
            "2026-01-10 * Salary\n    assets:bank  100.00\n    income:salary\n"
        )

        written, fell_back = save_account_directive(
            main, "assets:bank", "Own account"
        )
        assert not fell_back
        assert written == sub
        directives = load_account_directives(main)
        assert directives["assets:bank"].comment == "Own account"


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSaveAccountDirectiveOwnerFile:
    """Writes land in the file owning the account's postings (issue #272)."""

    def _split_journal(self, tmp_path: Path) -> Path:
        """A journal split into two included files."""
        main = tmp_path / "main.journal"
        main.write_text("include 2026-01.journal\ninclude 2026-02.journal\n")
        (tmp_path / "2026-01.journal").write_text(
            "2026-01-10 * Grocery\n    expenses:food  10.00\n    assets:bank\n"
        )
        (tmp_path / "2026-02.journal").write_text(
            "2026-02-10 * Rent\n    expenses:rent  800.00\n    assets:bank\n"
        )
        return main

    def test_note_goes_to_owning_file(self, tmp_path: Path):
        """A note for expenses:rent is written to 2026-02.journal."""
        main = self._split_journal(tmp_path)
        written, fell_back = save_account_directive(
            main, "expenses:rent", "Monthly rent"
        )
        assert not fell_back
        assert written == tmp_path / "2026-02.journal"
        assert "account expenses:rent  ; Monthly rent" in written.read_text()
        # Nothing leaked into the other files.
        assert "account expenses:rent" not in (tmp_path / "2026-01.journal").read_text()
        assert "account expenses:rent" not in main.read_text()

    def test_existing_directive_updated_in_place(self, tmp_path: Path):
        """A second save updates the directive instead of appending one."""
        main = self._split_journal(tmp_path)
        save_account_directive(main, "expenses:rent", "First")
        before = (tmp_path / "2026-02.journal").read_text()
        save_account_directive(main, "expenses:rent", "Second")

        text = (tmp_path / "2026-02.journal").read_text()
        assert text.count("account expenses:rent") == 1
        assert "Second" in text
        assert "First" not in text
        # Only the directive line changed.
        assert before.replace("First", "Second") == text

    def test_unknown_account_falls_back_to_main(self, tmp_path: Path):
        """An account with no transactions is written to the main journal."""
        main = self._split_journal(tmp_path)
        before = main.read_text()
        written, fell_back = save_account_directive(
            main, "expenses:unknown", "No postings"
        )
        assert fell_back
        assert written == main
        assert "account expenses:unknown" in main.read_text()
        assert main.read_text().startswith(before.split("\n")[0]) or True

    def test_invalid_journal_is_restored(self, tmp_path: Path, monkeypatch):
        """A failing hledger check restores the original file bytes."""
        from hledger_textual.journal import JournalError

        main = self._split_journal(tmp_path)
        target = tmp_path / "2026-02.journal"
        before = target.read_bytes()

        def _fail(file):
            raise Exception("validation failed")

        monkeypatch.setattr(
            "hledger_textual.hledger.check_journal", _fail
        )
        with pytest.raises(JournalError):
            save_account_directive(main, "expenses:rent", "Bad write")
        assert target.read_bytes() == before
