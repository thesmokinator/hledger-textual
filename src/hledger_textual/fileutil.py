"""File backup/restore utilities for safe write operations."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Callable

# Serialise read-modify-write of the main journal's ``include`` directives so
# concurrent pane loads (budget + recurring) cannot clobber each other.
journal_include_lock = threading.Lock()


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write *content* to *path* atomically (temp file + ``os.replace``).

    Readers see either the old or the new complete contents, never a partially
    written file — a partial UTF-8 file raises ``UnicodeDecodeError`` in any
    worker reading the journal concurrently.

    Args:
        path: Destination file path.
        content: Full text to write.
        encoding: Text encoding (default UTF-8).
    """
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def backup(file: Path) -> Path:
    """Create a backup of a file.

    Args:
        file: Path to the file to back up.

    Returns:
        Path to the backup file.
    """
    backup_path = file.with_suffix(file.suffix + ".bak")
    shutil.copy2(file, backup_path)
    return backup_path


def restore(file: Path, backup_path: Path) -> None:
    """Restore a file from its backup.

    Args:
        file: Path to the file to restore.
        backup_path: Path to the backup file.
    """
    shutil.copy2(backup_path, file)


def cleanup_backup(backup_path: Path) -> None:
    """Remove a backup file.

    Args:
        backup_path: Path to the backup file to remove.
    """
    backup_path.unlink(missing_ok=True)


def safe_write_with_validation(
    target_file: Path,
    content: str,
    journal_file: Path,
    validate: Callable[[Path], None],
    error_cls: type[Exception],
    context: str = "file",
) -> None:
    """Write content to a file with backup/validate/restore safety.

    1. Creates a backup of *target_file*.
    2. Writes *content* to *target_file*.
    3. Calls *validate(journal_file)* to check validity.
    4. On validation failure, restores from backup and raises *error_cls*.

    Args:
        target_file: The file to write to.
        content: The new file content.
        journal_file: Path to the main journal file (passed to validate).
        validate: A callable that raises on validation failure.
        error_cls: The exception class to raise on failure.
        context: A label for error messages (e.g. "Budget", "Recurring").
    """
    bak = backup(target_file)

    try:
        atomic_write_text(target_file, content)

        try:
            validate(journal_file)
        except Exception as exc:
            restore(target_file, bak)
            cleanup_backup(bak)
            raise error_cls(
                f"{context} validation failed, changes reverted: {exc}"
            ) from exc

        cleanup_backup(bak)
    except error_cls:
        raise
    except Exception as exc:
        restore(target_file, bak)
        cleanup_backup(bak)
        raise error_cls(f"Failed to write {context.lower()}: {exc}") from exc
