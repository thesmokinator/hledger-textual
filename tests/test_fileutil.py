"""Tests for file backup/restore utilities."""

from pathlib import Path
from unittest.mock import patch

import pytest

from hledger_textual.fileutil import backup, cleanup_backup, restore, safe_write_with_validation


class TestBackup:
    """Tests for backup."""

    def test_creates_bak_file(self, tmp_path: Path):
        """A .bak file is created next to the original."""
        f = tmp_path / "test.journal"
        f.write_text("original content")
        bak = backup(f)
        assert bak == tmp_path / "test.journal.bak"
        assert bak.exists()

    def test_backup_content_matches_original(self, tmp_path: Path):
        """The backup has the same content as the original."""
        f = tmp_path / "test.journal"
        f.write_text("some data")
        bak = backup(f)
        assert bak.read_text() == "some data"

    def test_original_is_unchanged(self, tmp_path: Path):
        """The original file is not modified."""
        f = tmp_path / "test.journal"
        f.write_text("keep me")
        backup(f)
        assert f.read_text() == "keep me"

    def test_compound_extension(self, tmp_path: Path):
        """Files with compound extensions get .bak appended to the last suffix."""
        f = tmp_path / "data.budget.journal"
        f.write_text("budget data")
        bak = backup(f)
        assert bak.name == "data.budget.journal.bak"
        assert bak.read_text() == "budget data"


class TestRestore:
    """Tests for restore."""

    def test_overwrites_original_with_backup(self, tmp_path: Path):
        """Restore replaces the original file content with the backup."""
        f = tmp_path / "test.journal"
        f.write_text("original")
        bak = backup(f)
        f.write_text("modified")
        restore(f, bak)
        assert f.read_text() == "original"

    def test_backup_still_exists_after_restore(self, tmp_path: Path):
        """The backup file is not removed by restore."""
        f = tmp_path / "test.journal"
        f.write_text("data")
        bak = backup(f)
        f.write_text("changed")
        restore(f, bak)
        assert bak.exists()


class TestCleanupBackup:
    """Tests for cleanup_backup."""

    def test_removes_backup_file(self, tmp_path: Path):
        """The backup file is deleted."""
        bak = tmp_path / "test.journal.bak"
        bak.write_text("backup")
        cleanup_backup(bak)
        assert not bak.exists()

    def test_no_error_when_missing(self, tmp_path: Path):
        """No exception is raised when the backup file does not exist."""
        bak = tmp_path / "nonexistent.bak"
        cleanup_backup(bak)  # should not raise


class TestRoundtrip:
    """End-to-end backup/mutate/restore/cleanup cycle."""

    def test_full_cycle(self, tmp_path: Path):
        """Backup, modify, restore, cleanup returns to original state."""
        f = tmp_path / "test.journal"
        f.write_text("original content")

        bak = backup(f)
        f.write_text("corrupted content")
        restore(f, bak)
        assert f.read_text() == "original content"

        cleanup_backup(bak)
        assert not bak.exists()
        assert f.exists()


class TestSafeWriteWithValidation:
    """Tests for safe_write_with_validation."""

    class _AppError(Exception):
        pass

    def _make_files(self, tmp_path: Path) -> tuple[Path, Path]:
        target = tmp_path / "data.journal"
        target.write_text("original content", encoding="utf-8")
        journal = tmp_path / "main.journal"
        journal.write_text("", encoding="utf-8")
        return target, journal

    def test_happy_path_writes_content(self, tmp_path: Path):
        """New content is written and backup is removed on success."""
        target, journal = self._make_files(tmp_path)

        safe_write_with_validation(target, "new content", journal, lambda p: None, self._AppError)

        assert target.read_text(encoding="utf-8") == "new content"
        assert not target.with_suffix(".journal.bak").exists()

    def test_happy_path_validate_receives_journal_file(self, tmp_path: Path):
        """The validate callable is called with the journal_file argument."""
        target, journal = self._make_files(tmp_path)
        received: list[Path] = []

        def capture_validate(p: Path) -> None:
            received.append(p)

        safe_write_with_validation(target, "x", journal, capture_validate, self._AppError)

        assert received == [journal]

    def test_validation_failure_restores_original(self, tmp_path: Path):
        """On validation failure the original content is restored."""
        target, journal = self._make_files(tmp_path)

        def bad_validate(p: Path) -> None:
            raise ValueError("parse error")

        with pytest.raises(self._AppError, match="validation failed"):
            safe_write_with_validation(target, "bad content", journal, bad_validate, self._AppError)

        assert target.read_text(encoding="utf-8") == "original content"

    def test_validation_failure_cleans_up_backup(self, tmp_path: Path):
        """The .bak file is removed after a validation failure."""
        target, journal = self._make_files(tmp_path)
        bak = target.with_suffix(".journal.bak")

        with pytest.raises(self._AppError):
            safe_write_with_validation(target, "bad", journal, lambda p: (_ for _ in ()).throw(ValueError("bad")), self._AppError)

        assert not bak.exists()

    def test_validation_failure_error_message_includes_context(self, tmp_path: Path):
        """The error message contains the context label."""
        target, journal = self._make_files(tmp_path)

        with pytest.raises(self._AppError, match="Budget validation failed"):
            safe_write_with_validation(
                target, "bad", journal, lambda p: (_ for _ in ()).throw(ValueError("x")), self._AppError, context="Budget"
            )

    def test_write_failure_restores_original(self, tmp_path: Path):
        """If write_text raises, the original content is restored."""
        target, journal = self._make_files(tmp_path)

        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            with pytest.raises(self._AppError, match="Failed to write"):
                safe_write_with_validation(target, "new", journal, lambda p: None, self._AppError)

        assert target.read_text(encoding="utf-8") == "original content"

    def test_write_failure_cleans_up_backup(self, tmp_path: Path):
        """The .bak file is removed after a write failure."""
        target, journal = self._make_files(tmp_path)
        bak = target.with_suffix(".journal.bak")

        with patch.object(Path, "write_text", side_effect=OSError("no space")):
            with pytest.raises(self._AppError):
                safe_write_with_validation(target, "new", journal, lambda p: None, self._AppError)

        assert not bak.exists()
