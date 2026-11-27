"""Global hledger query state shared by every transaction-backed pane (#281).

The global query composes with the shared period selection (AND semantics:
space-separated hledger matchers) and survives period navigation.  Blank
means "no global filter" and behaves exactly like today.
"""

from __future__ import annotations

from pathlib import Path

from hledger_textual.hledger import HledgerError, run_hledger


class InvalidQueryError(ValueError):
    """Raised when hledger rejects a global query string."""


def compose_query(*parts: str | None) -> str | None:
    """Join query parts with single spaces, skipping blank ones.

    Args:
        *parts: Query fragments (period expressions, user queries, ...).

    Returns:
        The composed query, or ``None`` when every part is blank.
    """
    composed = " ".join(part.strip() for part in parts if part and part.strip())
    return composed or None


def validate_query(file: str | Path, query: str) -> None:
    """Validate *query* with hledger itself before applying it.

    Runs a limited ``print`` so validation never loads the whole journal.
    Blank queries are a no-op (clearing the filter is always valid).

    Args:
        file: Path to the journal file.
        query: The hledger query string to validate.

    Raises:
        InvalidQueryError: If hledger rejects the query.
    """
    if not query.strip():
        return
    try:
        run_hledger("print", *query.split(), "-n", "1", file=file)
    except HledgerError as exc:
        raise InvalidQueryError(f"Invalid query {query!r}: {exc}") from exc
