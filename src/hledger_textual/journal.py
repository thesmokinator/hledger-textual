"""Journal file manipulation: append, replace, and delete transactions.

All write operations follow a safe pattern:
1. Create a backup of the journal file (.bak)
2. Perform the modification
3. Validate with `hledger check`
4. On failure, restore from backup
"""

from __future__ import annotations

import re
from enum import Enum, auto
from pathlib import Path

from hledger_textual.fileutil import backup as _backup
from hledger_textual.fileutil import cleanup_backup as _cleanup_backup
from hledger_textual.fileutil import restore as _restore
from hledger_textual.formatter import format_transaction
from hledger_textual.hledger import HledgerError, check_journal
from hledger_textual.models import Transaction

_DATE_INCLUDE_RE = re.compile(
    r"^\s*include\s+(\d{4}-\d{2}\.journal)\s*$", re.MULTILINE
)

_GLOB_INCLUDE_RE = re.compile(
    r"^\s*include\s+(\d{4})/\*\.journal\s*$", re.MULTILINE
)


class RoutingStrategy(Enum):
    """How new transactions are routed to sub-journals."""

    GLOB = auto()       # include YYYY/*.journal
    FLAT = auto()       # include YYYY-MM.journal
    FALLBACK = auto()   # no date-based includes


class JournalError(Exception):
    """Raised when a journal manipulation fails."""


def _find_date_includes(content: str) -> list[str]:
    """Return date-based include filenames found in journal content.

    Matches lines like ``include 2026-01.journal`` and returns a sorted
    list of the filenames (e.g. ``["2026-01.journal", "2026-02.journal"]``).

    Args:
        content: The text content of a journal file.

    Returns:
        List of matched filenames, or empty list if none found.
    """
    return _DATE_INCLUDE_RE.findall(content)


def _find_glob_includes(content: str) -> list[str]:
    """Return year strings from glob-based include directives.

    Matches lines like ``include 2026/*.journal`` and returns a list of
    the year strings (e.g. ``["2026"]``).

    Args:
        content: The text content of a journal file.

    Returns:
        List of matched year strings, or empty list if none found.
    """
    return _GLOB_INCLUDE_RE.findall(content)


def _detect_routing_strategy(content: str) -> tuple[RoutingStrategy, list[str]]:
    """Detect which routing strategy the journal uses.

    Checks for glob-based includes first (highest priority), then flat
    date-based includes, then falls back to direct append.

    Args:
        content: The text content of the main journal file.

    Returns:
        A tuple of (strategy, matches) where matches is:
        - For GLOB: list of year strings (e.g. ``["2026"]``)
        - For FLAT: list of filenames (e.g. ``["2026-01.journal"]``)
        - For FALLBACK: empty list
    """
    glob_years = _find_glob_includes(content)
    if glob_years:
        return RoutingStrategy.GLOB, glob_years

    date_includes = _find_date_includes(content)
    if date_includes:
        return RoutingStrategy.FLAT, date_includes

    return RoutingStrategy.FALLBACK, []


def _glob_target_path(
    main_journal: Path, transaction: Transaction
) -> tuple[Path, str]:
    """Derive the target file path and year for glob-based routing.

    Args:
        main_journal: Path to the main journal file.
        transaction: The transaction to route.

    Returns:
        A tuple of (target_path, year_string), e.g.
        ``(Path(".../2026/03.journal"), "2026")``.
    """
    year = transaction.date[:4]
    month = transaction.date[5:7]
    target = main_journal.parent / year / f"{month}.journal"
    return target, year


def _target_subjournal_name(transaction: Transaction) -> str:
    """Derive the sub-journal filename from a transaction's date.

    Args:
        transaction: A transaction whose date is in ``YYYY-MM-DD`` format.

    Returns:
        Filename like ``"2026-03.journal"``.
    """
    return transaction.date[:7] + ".journal"


def _insert_include_sorted(content: str, new_include: str) -> str:
    """Insert a date-based include directive in chronological order.

    Finds existing date-based ``include`` lines and inserts the new one
    so that all date-based includes remain sorted.  Non-date includes and
    other content are preserved in place.

    Args:
        content: The current journal file content.
        new_include: The filename to include (e.g. ``"2026-03.journal"``).

    Returns:
        Updated content with the new include directive inserted.
    """
    new_line = f"include {new_include}"
    lines = content.splitlines(keepends=True)
    # Find positions and values of existing date-based includes
    date_positions: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _DATE_INCLUDE_RE.match(line)
        if m:
            date_positions.append((i, m.group(1)))

    if not date_positions:
        # No existing date includes — append at end
        if content and not content.endswith("\n"):
            return content + "\n" + new_line + "\n"
        return content + new_line + "\n"

    # Find insertion point: before the first include that sorts after new_include
    insert_idx = None
    for pos_idx, (line_idx, filename) in enumerate(date_positions):
        if new_include < filename:
            insert_idx = line_idx
            break

    if insert_idx is None:
        # New include goes after the last date-based include
        last_line_idx = date_positions[-1][0]
        insert_idx = last_line_idx + 1

    # Ensure the new line has a trailing newline
    new_entry = new_line + "\n"
    lines.insert(insert_idx, new_entry)
    return "".join(lines)


def _insert_glob_include_sorted(content: str, new_include: str) -> str:
    """Insert a glob-based include directive in sorted order.

    Finds existing glob-based ``include`` lines (e.g. ``include 2026/*.journal``)
    and inserts the new one so that all glob includes remain sorted.

    Args:
        content: The current journal file content.
        new_include: The glob pattern to include (e.g. ``"2027/*.journal"``).

    Returns:
        Updated content with the new include directive inserted.
    """
    new_line = f"include {new_include}"
    lines = content.splitlines(keepends=True)
    # Find positions and values of existing glob-based includes
    glob_positions: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _GLOB_INCLUDE_RE.match(line)
        if m:
            glob_positions.append((i, m.group(1)))

    if not glob_positions:
        # No existing glob includes — append at end
        if content and not content.endswith("\n"):
            return content + "\n" + new_line + "\n"
        return content + new_line + "\n"

    # Extract the year from the new include for comparison
    new_year = new_include.split("/")[0]

    # Find insertion point: before the first include whose year sorts after new_year
    insert_idx = None
    for pos_idx, (line_idx, year) in enumerate(glob_positions):
        if new_year < year:
            insert_idx = line_idx
            break

    if insert_idx is None:
        # New include goes after the last glob-based include
        last_line_idx = glob_positions[-1][0]
        insert_idx = last_line_idx + 1

    new_entry = new_line + "\n"
    lines.insert(insert_idx, new_entry)
    return "".join(lines)


def _validate_and_finalize(
    main_journal: Path, source_file: Path, backup: Path
) -> None:
    """Validate the journal and handle backup cleanup/restore.

    Runs ``hledger check`` against *main_journal* (which transitively
    validates every included file).  On failure the **source_file** –
    i.e. the file that was actually modified – is restored from *backup*.

    Args:
        main_journal: Path to the top-level journal file (for validation).
        source_file: Path to the file that was modified (for backup/restore).
        backup: Path to the backup of *source_file*.

    Raises:
        JournalError: If validation fails (source_file is restored from backup).
    """
    try:
        check_journal(main_journal)
    except HledgerError as exc:
        _restore(source_file, backup)
        _cleanup_backup(backup)
        raise JournalError(f"Journal validation failed, changes reverted: {exc}")
    _cleanup_backup(backup)


def _append_to_file(
    main_journal: Path, target_file: Path, transaction: Transaction
) -> None:
    """Append a transaction to a target file and validate via the main journal.

    This is the core write logic shared by both the legacy (single-file) and
    sub-journal routing paths.

    Args:
        main_journal: Path to the top-level journal file (for validation).
        target_file: Path to the file to append to.
        transaction: The transaction to append.

    Raises:
        JournalError: If validation fails after appending.
    """
    backup = _backup(target_file)

    try:
        content = target_file.read_text(encoding="utf-8")
        if content and not content.endswith("\n\n"):
            if content.endswith("\n"):
                content += "\n"
            else:
                content += "\n\n"

        content += format_transaction(transaction) + "\n"
        target_file.write_text(content, encoding="utf-8")

        _validate_and_finalize(main_journal, target_file, backup)
    except JournalError:
        raise
    except Exception as exc:
        _restore(target_file, backup)
        _cleanup_backup(backup)
        raise JournalError(f"Failed to append transaction: {exc}")


def _append_to_new_subjournal(
    main_journal: Path,
    target_file: Path,
    target_name: str,
    transaction: Transaction,
) -> None:
    """Create a new sub-journal, add its include directive, and append a transaction.

    Handles the two-file atomic operation:
    1. Backup the main journal.
    2. Insert a sorted ``include`` directive into the main journal.
    3. Create the new sub-journal with the transaction.
    4. Validate via the main journal.
    5. On failure: restore main from backup and delete the new sub-journal.

    Args:
        main_journal: Path to the top-level journal file.
        target_file: Path to the new sub-journal to create.
        target_name: Filename of the new sub-journal (e.g. ``"2026-03.journal"``).
        transaction: The transaction to write.

    Raises:
        JournalError: If validation fails (main restored, sub-journal removed).
    """
    main_backup = _backup(main_journal)

    try:
        # Insert the include directive in sorted order
        main_content = main_journal.read_text(encoding="utf-8")
        main_content = _insert_include_sorted(main_content, target_name)
        main_journal.write_text(main_content, encoding="utf-8")

        # Create the new sub-journal with the transaction
        target_file.write_text(format_transaction(transaction) + "\n", encoding="utf-8")

        _validate_and_finalize(main_journal, main_journal, main_backup)
    except JournalError:
        # _validate_and_finalize already restored main from backup;
        # we just need to clean up the newly created sub-journal.
        if target_file.exists():
            target_file.unlink()
        raise
    except Exception as exc:
        _restore(main_journal, main_backup)
        _cleanup_backup(main_backup)
        if target_file.exists():
            target_file.unlink()
        raise JournalError(f"Failed to append transaction: {exc}")


def _append_to_new_glob_subjournal(
    main_journal: Path,
    target_file: Path,
    transaction: Transaction,
) -> None:
    """Create a new month file in an existing year directory.

    The glob include already covers new files, so the main journal
    is not modified.

    Args:
        main_journal: Path to the top-level journal file (for validation).
        target_file: Path to the new month file to create.
        transaction: The transaction to write.

    Raises:
        JournalError: If validation fails (new file is removed).
    """
    try:
        target_file.write_text(format_transaction(transaction) + "\n", encoding="utf-8")
        check_journal(main_journal)
    except HledgerError as exc:
        if target_file.exists():
            target_file.unlink()
        raise JournalError(f"Journal validation failed, changes reverted: {exc}")
    except Exception as exc:
        if target_file.exists():
            target_file.unlink()
        raise JournalError(f"Failed to append transaction: {exc}")


def _append_to_new_glob_year(
    main_journal: Path,
    target_file: Path,
    year: str,
    transaction: Transaction,
) -> None:
    """Create a new year directory, add a glob include, and write the transaction.

    Handles the multi-step operation:
    1. Backup the main journal.
    2. Insert ``include YYYY/*.journal`` in sorted order in the main journal.
    3. Create the year directory.
    4. Create the month file with the transaction.
    5. Validate via the main journal.
    6. On failure: restore main, delete month file, remove year dir if empty.

    Args:
        main_journal: Path to the top-level journal file.
        target_file: Path to the new month file (e.g. ``2027/01.journal``).
        year: The year string (e.g. ``"2027"``).
        transaction: The transaction to write.

    Raises:
        JournalError: If validation fails (all changes reverted).
    """
    main_backup = _backup(main_journal)
    year_dir = main_journal.parent / year
    year_dir_created = not year_dir.exists()

    try:
        # Insert the glob include directive in sorted order
        main_content = main_journal.read_text(encoding="utf-8")
        new_include = f"{year}/*.journal"
        main_content = _insert_glob_include_sorted(main_content, new_include)
        main_journal.write_text(main_content, encoding="utf-8")

        # Create the year directory and month file
        year_dir.mkdir(exist_ok=True)
        target_file.write_text(format_transaction(transaction) + "\n", encoding="utf-8")

        _validate_and_finalize(main_journal, main_journal, main_backup)
    except JournalError:
        # _validate_and_finalize already restored main from backup;
        # clean up the newly created files.
        if target_file.exists():
            target_file.unlink()
        if year_dir_created and year_dir.exists() and not any(year_dir.iterdir()):
            year_dir.rmdir()
        raise
    except Exception as exc:
        _restore(main_journal, main_backup)
        _cleanup_backup(main_backup)
        if target_file.exists():
            target_file.unlink()
        if year_dir_created and year_dir.exists() and not any(year_dir.iterdir()):
            year_dir.rmdir()
        raise JournalError(f"Failed to append transaction: {exc}")


def append_transaction(file: str | Path, transaction: Transaction) -> None:
    """Append a new transaction to the journal.

    Supports three routing strategies (auto-detected):

    - **Glob**: ``include YYYY/*.journal`` — routes to ``YYYY/MM.journal``
      sub-journals inside year directories.
    - **Flat**: ``include YYYY-MM.journal`` — routes to ``YYYY-MM.journal``
      sub-journals alongside the main journal.
    - **Fallback**: no date-based includes — appends directly to the main
      journal file.

    Args:
        file: Path to the journal file.
        transaction: The transaction to append.

    Raises:
        JournalError: If validation fails after appending.
    """
    main_journal = Path(file)
    main_content = main_journal.read_text(encoding="utf-8")
    strategy, matches = _detect_routing_strategy(main_content)

    if strategy == RoutingStrategy.FALLBACK:
        _append_to_file(main_journal, main_journal, transaction)
        return

    if strategy == RoutingStrategy.FLAT:
        target_name = _target_subjournal_name(transaction)
        target_file = main_journal.parent / target_name
        if target_name in matches:
            _append_to_file(main_journal, target_file, transaction)
        else:
            _append_to_new_subjournal(
                main_journal, target_file, target_name, transaction
            )
        return

    # GLOB strategy
    target_file, year = _glob_target_path(main_journal, transaction)
    if target_file.exists():
        _append_to_file(main_journal, target_file, transaction)
    elif year in matches:
        _append_to_new_glob_subjournal(main_journal, target_file, transaction)
    else:
        _append_to_new_glob_year(main_journal, target_file, year, transaction)


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

    main_journal = Path(file)
    source_file = Path(transaction.source_pos[0].source_name)
    backup = _backup(source_file)

    try:
        lines = source_file.read_text(encoding="utf-8").splitlines(keepends=True)

        start_line = transaction.source_pos[0].source_line - 1
        end_line = transaction.source_pos[1].source_line - 1

        original_lines = lines[start_line:end_line]
        if original_lines and transaction.postings == new_transaction.postings:
            header = format_transaction(new_transaction).splitlines()[0]
            line_ending = "\r\n" if original_lines[0].endswith("\r\n") else "\n"
            new_lines = [header + line_ending, *original_lines[1:]]
        else:
            new_text = format_transaction(new_transaction) + "\n"
            new_lines = new_text.splitlines(keepends=True)

        lines[start_line:end_line] = new_lines
        source_file.write_text("".join(lines), encoding="utf-8")

        _validate_and_finalize(main_journal, source_file, backup)
    except JournalError:
        raise
    except Exception as exc:
        _restore(source_file, backup)
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

    main_journal = Path(file)
    source_file = Path(transaction.source_pos[0].source_name)
    backup = _backup(source_file)

    try:
        lines = source_file.read_text(encoding="utf-8").splitlines(keepends=True)

        start_line = transaction.source_pos[0].source_line - 1
        end_line = transaction.source_pos[1].source_line - 1

        # Also remove a leading blank line if present
        if start_line > 0 and lines[start_line - 1].strip() == "":
            start_line -= 1

        del lines[start_line:end_line]
        source_file.write_text("".join(lines), encoding="utf-8")

        _validate_and_finalize(main_journal, source_file, backup)
    except JournalError:
        raise
    except Exception as exc:
        _restore(source_file, backup)
        _cleanup_backup(backup)
        raise JournalError(f"Failed to delete transaction: {exc}")
