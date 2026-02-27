"""Journal file manipulation: append, replace, and delete transactions.

All write operations follow a safe pattern:
1. Create a backup of the journal file (.bak)
2. Perform the modification
3. Validate with `hledger check`
4. On failure, restore from backup
"""

from __future__ import annotations

import shutil
from pathlib import Path

from hledger_textual.formatter import format_transaction
from hledger_textual.hledger import HledgerError, check_journal
from hledger_textual.models import Transaction


class JournalError(Exception):
    """Raised when a journal manipulation fails."""


def _backup(file: Path) -> Path:
    """Create a backup of the journal file.

    Args:
        file: Path to the journal file.

    Returns:
        Path to the backup file.
    """
    backup_path = file.with_suffix(file.suffix + ".bak")
    shutil.copy2(file, backup_path)
    return backup_path


def _restore(file: Path, backup: Path) -> None:
    """Restore a journal file from backup.

    Args:
        file: Path to the journal file to restore.
        backup: Path to the backup file.
    """
    shutil.copy2(backup, file)


def _cleanup_backup(backup: Path) -> None:
    """Remove the backup file.

    Args:
        backup: Path to the backup file.
    """
    backup.unlink(missing_ok=True)


def _validate_and_finalize(file: Path, backup: Path) -> None:
    """Validate the journal file and handle backup cleanup/restore.

    Args:
        file: Path to the journal file.
        backup: Path to the backup file.

    Raises:
        JournalError: If validation fails (file is restored from backup).
    """
    try:
        check_journal(file)
    except HledgerError as exc:
        _restore(file, backup)
        _cleanup_backup(backup)
        raise JournalError(f"Journal validation failed, changes reverted: {exc}")
    _cleanup_backup(backup)


def append_transaction(file: str | Path, transaction: Transaction) -> None:
    """Append a new transaction to the end of the journal file.

    Args:
        file: Path to the journal file.
        transaction: The transaction to append.

    Raises:
        JournalError: If validation fails after appending.
    """
    file = Path(file)
    backup = _backup(file)

    try:
        content = file.read_text()
        # Ensure there's a blank line before the new transaction
        if content and not content.endswith("\n\n"):
            if content.endswith("\n"):
                content += "\n"
            else:
                content += "\n\n"

        content += format_transaction(transaction) + "\n"
        file.write_text(content)

        _validate_and_finalize(file, backup)
    except JournalError:
        raise
    except Exception as exc:
        _restore(file, backup)
        _cleanup_backup(backup)
        raise JournalError(f"Failed to append transaction: {exc}")


def replace_transaction(
    file: str | Path,
    transaction: Transaction,
    new_transaction: Transaction,
) -> None:
    """Replace an existing transaction in the journal file.

    Uses tsourcepos line numbers to locate the transaction in the file.

    Args:
        file: Path to the journal file.
        transaction: The original transaction (must have source_pos).
        new_transaction: The replacement transaction.

    Raises:
        JournalError: If the original transaction has no source position or
            validation fails.
    """
    if transaction.source_pos is None:
        raise JournalError("Cannot replace transaction without source position")

    file = Path(file)
    backup = _backup(file)

    try:
        lines = file.read_text().splitlines(keepends=True)

        start_line = transaction.source_pos[0].source_line - 1
        end_line = transaction.source_pos[1].source_line - 1

        new_text = format_transaction(new_transaction) + "\n"
        new_lines = new_text.splitlines(keepends=True)

        lines[start_line:end_line] = new_lines
        file.write_text("".join(lines))

        _validate_and_finalize(file, backup)
    except JournalError:
        raise
    except Exception as exc:
        _restore(file, backup)
        _cleanup_backup(backup)
        raise JournalError(f"Failed to replace transaction: {exc}")


def delete_transaction(
    file: str | Path,
    transaction: Transaction,
) -> None:
    """Delete a transaction from the journal file.

    Uses tsourcepos line numbers to locate the transaction in the file.

    Args:
        file: Path to the journal file.
        transaction: The transaction to delete (must have source_pos).

    Raises:
        JournalError: If the transaction has no source position or
            validation fails.
    """
    if transaction.source_pos is None:
        raise JournalError("Cannot delete transaction without source position")

    file = Path(file)
    backup = _backup(file)

    try:
        lines = file.read_text().splitlines(keepends=True)

        start_line = transaction.source_pos[0].source_line - 1
        end_line = transaction.source_pos[1].source_line - 1

        # Also remove a leading blank line if present
        if start_line > 0 and lines[start_line - 1].strip() == "":
            start_line -= 1

        del lines[start_line:end_line]
        file.write_text("".join(lines))

        _validate_and_finalize(file, backup)
    except JournalError:
        raise
    except Exception as exc:
        _restore(file, backup)
        _cleanup_backup(backup)
        raise JournalError(f"Failed to delete transaction: {exc}")
