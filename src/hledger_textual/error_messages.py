"""Human-friendly messages for hledger and filesystem failures (issue #158)."""

from __future__ import annotations

import re
from pathlib import Path

from hledger_textual.csv_import import CsvImportError
from hledger_textual.hledger import HledgerError
from hledger_textual.journal import JournalError

_LINE_RE = re.compile(r"(?:line\s+(\d+)|:(\d+)(?:-\d+)?:\d*:?)", re.IGNORECASE)
_PATH_RE = re.compile(r"[\w./~-]+\.journal\b")


def humanize_error(exc: Exception) -> tuple[str, str]:
    """Map an exception to a short title and an actionable message.

    The pairs are meant for a toast: the title says what failed, the body says
    what the user can do about it.  Unknown errors keep the original message
    and add an invitation to report the problem.

    Args:
        exc: The exception raised by a loader, a writer or hledger itself.

    Returns:
        A ``(title, body)`` tuple.
    """
    message = str(exc).strip()

    if isinstance(exc, HledgerError):
        return _humanize_hledger_error(message)

    if isinstance(exc, JournalError):
        return (
            "Could not update the journal",
            f"{message}. Check that the file is writable and not open in another program.",
        )

    if isinstance(exc, CsvImportError):
        return ("CSV import failed", message)

    if isinstance(exc, FileNotFoundError):
        path = getattr(exc, "filename", None)
        return (
            "File not found",
            f"{path} does not exist. Check the path and try again."
            if path
            else "The file does not exist. Check the path and try again.",
        )

    if isinstance(exc, PermissionError):
        path = getattr(exc, "filename", None)
        return (
            "Permission denied",
            f"Cannot access {path}. Check the file permissions."
            if path
            else "Cannot access the file. Check the file permissions.",
        )

    return (
        "Unexpected error",
        f"{message or exc.__class__.__name__}. "
        "If this keeps happening, please open an issue.",
    )


def _humanize_hledger_error(message: str) -> tuple[str, str]:
    """Split an hledger failure into a title and an actionable body."""
    lowered = message.lower()

    if "hledger not found" in lowered:
        return (
            "hledger not found",
            "Install hledger from https://hledger.org/install.html and make sure "
            "it is on your PATH.",
        )

    detail = message
    prefix = "hledger command failed:"
    if lowered.startswith(prefix):
        detail = message[len(prefix):].strip()

    if "permission denied" in detail.lower():
        return (
            "Permission denied",
            f"hledger cannot read or write the journal: {detail}",
        )

    lowered_detail = detail.lower()
    if (
        "no such file" in lowered_detail
        or "does not exist" in lowered_detail
        or "was not found" in lowered_detail
    ):
        match = _PATH_RE.search(detail)
        path = match.group(0) if match else "the journal file"
        return (
            "Journal file not found",
            f"{path} does not exist. Check the file path in your command or config.",
        )

    line = _LINE_RE.search(detail)
    if line:
        line_number = line.group(1) or line.group(2)
        return (
            "Journal syntax error",
            f"hledger could not parse line {line_number}: {_last_line(detail)}",
        )

    return (
        "hledger error",
        f"{_last_line(detail)}. If this keeps happening, please open an issue.",
    )


def _last_line(text: str, limit: int = 300) -> str:
    """Return the last non-empty line of *text*, truncated for a toast.

    hledger prints the offending source lines first and the human-readable
    explanation last, so the last line is the useful one.
    """
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1] + "\u2026"
    return text.strip() or "Unknown error"


def short_path(path: Path) -> str:
    """Shorten a path by replacing the home directory with ``~``."""
    try:
        return str(Path("~") / path.relative_to(Path.home()))
    except ValueError:
        return str(path)
