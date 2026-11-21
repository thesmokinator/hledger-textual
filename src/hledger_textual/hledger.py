"""Interface to the hledger CLI for reading journal data."""

from __future__ import annotations

import csv
import io
import json
import shlex
import subprocess
import threading
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from hledger_textual.cache import HledgerCache
    from hledger_textual.models import AccountDirective, AccountNode

import re

from hledger_textual.amountutil import _normalize_number_string
from hledger_textual.diskcache import disk_cache
from hledger_textual.models import (
    Amount,
    AmountStyle,
    BudgetRow,
    AccountDirective,
    JournalStats,
    PeriodSummary,
    Posting,
    ReportData,
    ReportRow,
    SourcePosition,
    Transaction,
    TransactionStatus,
)
from hledger_textual.parallel import MAX_PARALLEL_LOADS, gather_loads

_INCLUDE_LINE_RE = re.compile(r"^include\s+([^;]+?)\s*(?:;.*)?$")


class HledgerError(Exception):
    """Raised when an hledger command fails."""


# Bounds the number of concurrent hledger subprocesses across all panes and
# workers.  Panes run several loaders in parallel; this semaphore prevents a
# burst of a dozen-plus hledger processes from fighting over CPU and memory.
_HLEDGER_SEMAPHORE = threading.BoundedSemaphore(MAX_PARALLEL_LOADS)

# Commands whose output is cached on disk.  ``run_hledger("--version")`` is the
# version lookup the cache itself uses, so it must stay out of the cache;
# import/add mutate the journal and must never be skipped by a cache hit.
_UNCACHEABLE_COMMANDS = {"--version", "--help", "help", "import", "add"}


def _extra_files_from_args(args: tuple[str, ...]) -> list[str]:
    """Return files passed with ``-f``/``--file`` inside an argument tuple."""
    extra: list[str] = []
    for index, arg in enumerate(args):
        if arg in ("-f", "--file") and index + 1 < len(args):
            extra.append(args[index + 1])
        elif arg.startswith("--file="):
            extra.append(arg.split("=", 1)[1])
    return extra


def run_hledger(*args: str, file: str | Path | None = None) -> str:
    """Run an hledger command and return stdout.

    Results are served from the persistent cache when the journal (and its
    includes) plus the command arguments are unchanged.

    Args:
        *args: Arguments to pass to hledger.
        file: Path to the journal file. Added as -f argument if provided.

    Returns:
        The stdout output as a string.

    Raises:
        HledgerError: If the command fails or hledger is not found.
    """
    cmd = ["hledger", "--no-conf"]
    if file is not None:
        cmd.extend(["-f", str(file)])
    cmd.extend(args)

    # Force wide layout for balance commands so that user-level
    # hledger.conf settings (e.g. --layout=bare) don't break our CSV
    # parsing, which expects one row per account with combined balances.
    if args and args[0] == "balance" and "--layout" not in " ".join(args):
        cmd.append("--layout=wide")

    extra_files = _extra_files_from_args(args)
    cacheable = not (args and args[0] in _UNCACHEABLE_COMMANDS)
    if cacheable:
        cached = disk_cache.get(args, file=file, extra_files=extra_files)
        if cached is not None:
            return cached

    try:
        with _HLEDGER_SEMAPHORE:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
            )
    except FileNotFoundError:
        raise HledgerError(
            "hledger not found. Please install it: https://hledger.org/install.html"
        )
    except subprocess.CalledProcessError as exc:
        raise HledgerError(
            f"hledger command failed: {exc.stderr.strip()}"
        )

    if cacheable:
        disk_cache.put(args, result.stdout, file=file, extra_files=extra_files)
    return result.stdout


def get_hledger_version() -> str:
    """Return the hledger version string, or '?' if unavailable."""
    try:
        raw = run_hledger("--version").strip()
        # Strip program name prefix: "hledger 1.51.2, ..." → "1.51.2, ..."
        if raw.lower().startswith("hledger "):
            return raw[len("hledger "):].strip()
        return raw
    except HledgerError:
        return "?"


# Short aliases → full hledger query prefixes
_QUERY_ALIASES: dict[str, str] = {
    "d:": "desc:",
    "ac:": "acct:",
    "am:": "amt:",
    "t:": "tag:",
    "st:": "status:",
}

# Regex metacharacters to escape for hledger queries.  Spaces are
# intentionally excluded because hledger uses spaces as query separators
# (``query.split()``).  Python's ``re.escape`` escapes spaces as ``\ ``
# which, after splitting, leaves a trailing backslash that hledger rejects.
_HLEDGER_RE_META = re.compile(r'([\\.^$*+?{}()|[\]])')


def escape_for_hledger(text: str) -> str:
    """Escape regex metacharacters for use in an hledger query.

    Unlike :func:`re.escape`, this does **not** escape spaces so that the
    resulting string survives ``query.split()`` inside
    :func:`load_transactions`.

    Args:
        text: Raw text (typically an account name).

    Returns:
        The text with regex metacharacters backslash-escaped.
    """
    return _HLEDGER_RE_META.sub(r'\\\1', text)


def expand_search_query(query: str) -> str:
    """Expand short search aliases to full hledger query prefixes.

    Supported aliases:
        ``d:`` → ``desc:``, ``ac:`` → ``acct:``, ``am:`` → ``amt:``

    Args:
        query: Raw user input from the search bar.

    Returns:
        The query string with short aliases replaced by their full forms.
    """
    if not query:
        return query
    for alias, full in _QUERY_ALIASES.items():
        query = re.sub(
            r"(?:^|(?<=\s))" + re.escape(alias),
            full,
            query,
        )
    return query


def check_journal(file: str | Path) -> None:
    """Validate a journal file using hledger check.

    Args:
        file: Path to the journal file.

    Raises:
        HledgerError: If the journal is invalid.
    """
    run_hledger("check", file=file)


def _parse_amount(data: dict) -> Amount:
    """Parse an amount from hledger JSON.

    When a cost annotation is present (``acost``), it is parsed and stored on
    the returned :class:`Amount`.  For per-unit costs (``UnitCost`` / ``@``)
    the cost is multiplied by the quantity to produce a total cost, so callers
    always see the total EUR value regardless of annotation style.
    """
    qty_data = data["aquantity"]
    mantissa = qty_data["decimalMantissa"]
    places = qty_data["decimalPlaces"]
    quantity = Decimal(mantissa) / Decimal(10 ** places)

    style_data = data.get("astyle", {})
    digit_groups = style_data.get("asdigitgroups")
    separator = None
    sizes: list[int] = []
    if digit_groups and isinstance(digit_groups, list) and len(digit_groups) == 2:
        separator = digit_groups[0]
        sizes = digit_groups[1]

    style = AmountStyle(
        commodity_side=style_data.get("ascommodityside", "L"),
        commodity_spaced=style_data.get("ascommodityspaced", False),
        decimal_mark=style_data.get("asdecimalmark", "."),
        digit_group_separator=separator,
        digit_group_sizes=sizes,
        precision=style_data.get("asprecision", 2),
    )

    # Parse cost annotation (@/@@) if present
    cost: Amount | None = None
    acost = data.get("acost")
    if acost and isinstance(acost, dict) and "contents" in acost:
        tag = acost.get("tag", "")
        cost_amount = _parse_amount(acost["contents"])
        if tag == "UnitCost":
            cost_amount = Amount(
                commodity=cost_amount.commodity,
                quantity=abs(cost_amount.quantity * quantity),
                style=cost_amount.style,
            )
        else:
            # TotalCost (@@): hledger may store the quantity as negative for
            # sell transactions; normalise to always-positive so format()
            # produces a valid journal entry (e.g. "@@" is always positive).
            cost_amount = Amount(
                commodity=cost_amount.commodity,
                quantity=abs(cost_amount.quantity),
                style=cost_amount.style,
            )
        cost = cost_amount

    return Amount(
        commodity=data["acommodity"],
        quantity=quantity,
        style=style,
        cost=cost,
    )


def _parse_posting(data: dict) -> Posting:
    """Parse a posting from hledger JSON."""
    amounts = [_parse_amount(a) for a in data.get("pamount", [])]
    status = TransactionStatus(data.get("pstatus", "Unmarked"))

    return Posting(
        account=data["paccount"],
        amounts=amounts,
        comment=data.get("pcomment", "").strip(),
        status=status,
    )


def _parse_source_position(data: dict) -> SourcePosition:
    """Parse a source position from hledger JSON."""
    return SourcePosition(
        source_name=data["sourceName"],
        source_line=data["sourceLine"],
        source_column=data["sourceColumn"],
    )


def _parse_transaction(data: dict) -> Transaction:
    """Parse a transaction from hledger JSON."""
    postings = [_parse_posting(p) for p in data.get("tpostings", [])]
    status = TransactionStatus(data.get("tstatus", "Unmarked"))

    source_pos = None
    tsourcepos = data.get("tsourcepos", [])
    if len(tsourcepos) == 2:
        source_pos = (
            _parse_source_position(tsourcepos[0]),
            _parse_source_position(tsourcepos[1]),
        )

    return Transaction(
        index=data["tindex"],
        date=data["tdate"],
        description=data["tdescription"],
        postings=postings,
        status=status,
        code=data.get("tcode", ""),
        comment=data.get("tcomment", "").strip(),
        date2=data.get("tdate2"),
        source_pos=source_pos,
        tags=data.get("ttags", []),
    )


def load_transactions(
    file: str | Path,
    query: str | None = None,
    reverse: bool = False,
    cache: HledgerCache | None = None,
) -> list[Transaction]:
    """Load transactions from a journal file, optionally filtered by a query.

    Args:
        file: Path to the journal file.
        query: An hledger query string (e.g. 'acct:^assets:bank$'). When
            provided it is appended to the hledger print command so that only
            matching transactions are returned.
        reverse: If True, return transactions in reverse order (newest first).
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A list of Transaction objects.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    args = ["print", "-O", "json"]
    if query:
        args.extend(query.split())

    cache_key = ("load_transactions", tuple(args), str(file), reverse)
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    output = run_hledger(*args, file=file)
    data = json.loads(output)
    txns = [_parse_transaction(t) for t in data]
    result = list(reversed(txns)) if reverse else txns

    if cache is not None:
        cache.put(cache_key, result, file=file)

    return result


def load_account_balances(
    file: str | Path,
    cache: HledgerCache | None = None,
    commodity: str | None = None,
) -> list[tuple[str, str]]:
    """Load all accounts with their current balances.

    Args:
        file: Path to the journal file.
        cache: Optional cache instance to avoid repeated subprocess calls.
        commodity: Optional target commodity for conversion (``-X``).  When
            set, hledger converts every balance to this commodity using
            ``P`` price directives from the journal; unconverted commodities
            are kept as-is (hledger's ``-X`` semantics).

    Returns:
        A list of (account_name, balance_string) tuples, ordered as hledger
        returns them (alphabetical by account name).

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_account_balances", str(file), commodity)
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    args = ["--flat", "--no-total", "-O", "csv"]
    if commodity:
        args.extend(["-X", commodity, "--infer-market-prices"])
    output = run_hledger("balance", *args, file=file)
    reader = csv.reader(io.StringIO(output))
    next(reader, None)  # skip header row ("account","balance")
    result = [
        (row[0], row[1])
        for row in reader
        if len(row) >= 2 and row[0] and row[1]
    ]

    if cache is not None:
        cache.put(cache_key, result, file=file)

    return result


def _parse_tree_account(raw: str) -> tuple[str, int]:
    """Split a tree-indented hledger account cell into (name, depth).

    hledger's ``--tree`` CSV output prefixes child accounts with two
    non-breaking spaces (``\\xa0``) per hierarchy level. This helper strips
    those and returns the cleaned name plus its zero-based depth.

    Args:
        raw: The raw account cell from an hledger CSV row.

    Returns:
        A ``(name, depth)`` tuple. For top-level or flat-mode rows ``depth``
        is ``0``.
    """
    rstripped = raw.rstrip()
    stripped = rstripped.lstrip(" \xa0")
    depth = (len(rstripped) - len(stripped)) // 2
    return stripped, depth


def load_account_tree_balances(
    file: str | Path,
    commodity: str | None = None,
    cache: HledgerCache | None = None,
) -> list[AccountNode]:
    """Load accounts as a tree with hierarchical balances.

    Uses ``hledger balance --tree`` to get indented account names with
    subtotals for parent accounts.

    Args:
        file: Path to the journal file.
        commodity: Optional target commodity for conversion (``-X``).  When
            set, hledger converts every balance to this commodity using
            ``P`` price directives from the journal; unconverted commodities
            are kept as-is (hledger's ``-X`` semantics).
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A list of root-level :class:`AccountNode` instances, each with
        nested children reflecting the account hierarchy.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    from hledger_textual.models import AccountNode

    cache_key = ("load_account_tree_balances", str(file), commodity)
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    args = ["--tree", "--no-total", "-O", "csv"]
    if commodity:
        args.extend(["-X", commodity, "--infer-market-prices"])
    output = run_hledger("balance", *args, file=file)
    reader = csv.reader(io.StringIO(output))
    next(reader, None)  # skip header row

    # Build flat list with depth info from leading spaces
    flat_nodes: list[AccountNode] = []
    for row in reader:
        if len(row) < 2 or not row[0]:
            continue
        name, depth = _parse_tree_account(row[0])
        flat_nodes.append(AccountNode(
            name=name,
            full_path="",  # resolved below
            balance=row[1],
            depth=depth,
        ))

    # Resolve full_path and build parent-child relationships
    roots: list[AccountNode] = []
    stack: list[AccountNode] = []

    for node in flat_nodes:
        # Pop stack to find parent at depth - 1
        while len(stack) > node.depth:
            stack.pop()

        if stack:
            parent = stack[-1]
            node.full_path = f"{parent.full_path}:{node.name}"
            parent.children.append(node)
        else:
            node.full_path = node.name
            roots.append(node)

        # Ensure stack has exactly depth+1 entries
        if len(stack) == node.depth:
            stack.append(node)
        else:
            stack[node.depth] = node

    if cache is not None:
        cache.put(cache_key, roots, file=file)

    return roots


def load_accounts(file: str | Path) -> list[str]:
    """Load all account names from a journal file.

    Args:
        file: Path to the journal file.

    Returns:
        A sorted list of account names.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    output = run_hledger("accounts", file=file)
    return [line.strip() for line in output.strip().splitlines() if line.strip()]


def load_account_directives(file: str | Path) -> dict[str, AccountDirective]:
    """Parse ``account`` directives and their comments from a journal.

    Reads the files directly (the hledger CLI does not export directive
    comments).  ``include`` directives are followed (globs expanded), so
    notes stored in included files are visible (issue #272).  Later files
    win, mirroring hledger's "last definition wins" behaviour.

    Supports both single-line and multi-line comments::

        account expenses:groceries  ; note:Weekly shopping
            ; category:food

    Args:
        file: Path to the main journal file.

    Returns:
        A dict mapping full account names to :class:`AccountDirective`
        instances.  Only accounts that have an ``account`` directive in
        the journal (or its includes) are included.
    """
    return _load_directives_from(Path(file), frozenset())


def _load_directives_from(
    path: Path, seen: frozenset[Path]
) -> dict[str, AccountDirective]:
    """Recursively parse account directives from *path* and its includes.

    Args:
        path: Journal file to read.
        seen: Files already visited (cycle guard).
    """
    if path in seen:
        return {}

    # Imported here (not at module level) to avoid a config↔hledger cycle.
    from hledger_textual.config import _expand_include

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}

    directives: dict[str, AccountDirective] = {}
    current: AccountDirective | None = None
    include_paths: list[Path] = []

    for line in text.splitlines():
        # Match "account <name>" optionally followed by "  ; comment"
        m = re.match(r"^account\s+(\S+)\s*(?:;\s*(.*))?$", line)
        if m:
            name = m.group(1)
            comment_part = (m.group(2) or "").strip()
            tags = _parse_comment_tags(comment_part)
            current = AccountDirective(
                name=name,
                comment=comment_part,
                tags=tags,
            )
            directives[name] = current
            continue

        # Continuation comment line (indented, starts with ;)
        if current is not None:
            cm = re.match(r"^\s+;\s*(.*)$", line)
            if cm:
                extra = cm.group(1).strip()
                if current.comment:
                    current.comment += ", " + extra
                else:
                    current.comment = extra
                current.tags.update(_parse_comment_tags(extra))
                continue

        # Any non-continuation line ends the current directive
        current = None

        inc = _INCLUDE_LINE_RE.match(line)
        if inc:
            include_paths.extend(_expand_include(path, inc.group(1).strip()))

    for included in include_paths:
        directives.update(
            _load_directives_from(included, seen | {path})
        )

    return directives
def _parse_comment_tags(comment: str) -> dict[str, str]:
    """Extract ``key:value`` tags from a comment string.

    Args:
        comment: The comment text (without the leading ``;``).

    Returns:
        A dict of tag names to values.
    """
    tags: dict[str, str] = {}
    for m in re.finditer(r"(\w[\w-]*):\s*([^,;]+)", comment):
        tags[m.group(1)] = m.group(2).strip()
    return tags


def save_account_directive(
    file: str | Path,
    account: str,
    comment: str,
) -> tuple[Path, bool]:
    """Add or update an ``account`` directive in the journal (issue #272).

    The directive is written into the file that owns the account's
    postings (resolved from the transaction source positions, following
    ``include`` directives and globs).  Writes are atomic and validated
    with ``hledger check``; on failure the original bytes are restored.

    If the account cannot be located in the transactions, the directive
    is written to the main journal and the caller is told so it can say
    so in the confirmation.

    Args:
        file: Path to the main journal file.
        account: Full account name (e.g. ``"expenses:groceries"``).
        comment: The comment text (without leading ``;``).  If empty,
            any existing comment is removed but the directive is kept.

    Returns:
        ``(written_file, fell_back)``: the file that was written and
        whether the account had to be located by fallback.
    """
    path = Path(file)
    target, fell_back = _resolve_account_file(path, account)

    lines = target.read_text(encoding="utf-8").splitlines()
    comment_suffix = f"  ; {comment}" if comment else ""
    new_line = f"account {account}{comment_suffix}"

    # Try to find and replace an existing directive
    found = False
    i = 0
    while i < len(lines):
        m = re.match(r"^account\s+(\S+)", lines[i])
        if m and m.group(1) == account:
            lines[i] = new_line
            found = True
            # Remove any continuation comment lines
            while i + 1 < len(lines) and re.match(r"^\s+;", lines[i + 1]):
                lines.pop(i + 1)
            break
        i += 1

    if not found:
        # Insert after existing directives, before the first transaction
        # (first line starting with a date)
        insert_at = 0
        for idx, line in enumerate(lines):
            if re.match(r"^\d{4}[-/]", line):
                insert_at = idx
                break
        else:
            insert_at = len(lines)
        # Add a blank line separator if needed
        if insert_at > 0 and lines[insert_at - 1].strip():
            lines.insert(insert_at, "")
            insert_at += 1
        lines.insert(insert_at, new_line)
        if insert_at + 1 < len(lines) and lines[insert_at + 1].strip():
            lines.insert(insert_at + 1, "")

    # Deferred imports: fileutil/journal sit above this module in the
    # dependency graph (journal imports hledger).
    from hledger_textual.fileutil import safe_write_with_validation
    from hledger_textual.journal import JournalError

    safe_write_with_validation(
        target_file=target,
        content="\n".join(lines) + "\n",
        journal_file=path,
        validate=check_journal,
        error_cls=JournalError,
        context="Account note",
    )
    return target, fell_back


def _resolve_account_file(journal: Path, account: str) -> tuple[Path, bool]:
    """Return the file that owns *account*'s postings.

    The most recent transaction with a posting for the account wins; its
    source position names the owning file (hledger resolves includes and
    globs for us).

    Args:
        journal: Path to the main journal file.
        account: Full account name to locate.

    Returns:
        ``(owning_file, fell_back)``.  When the account cannot be located
        (no transactions, no source position, or hledger failure) the main
        journal is returned with ``fell_back=True``.
    """
    try:
        transactions = load_transactions(journal)
    except Exception:
        return journal, True

    for txn in reversed(transactions):
        if not any(p.account == account for p in txn.postings):
            continue
        if txn.source_pos is None:
            continue
        source = Path(txn.source_pos[0].source_name)
        if source.exists():
            return source, False
        break  # most recent matching transaction has an unusable position

    return journal, True


def load_descriptions(file: str | Path) -> list[str]:
    """Load all unique descriptions from a journal file.

    Args:
        file: Path to the journal file.

    Returns:
        A sorted list of unique descriptions.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    output = run_hledger("descriptions", file=file)
    return [line.strip() for line in output.strip().splitlines() if line.strip()]


def _parse_budget_amount(s: str) -> tuple[Decimal, str]:
    """Parse a budget amount string like '€500.00' or '500.00 EUR'.

    Args:
        s: The amount string from hledger CSV output.

    Returns:
        A tuple of (quantity, commodity). Returns (0, "") for unparseable values.
    """
    s = s.strip()
    if not s or s == "0":
        return Decimal("0"), ""

    # Left-side commodity: €500.00, €1.000,00
    match = re.match(r"^([^\d\s.-]+)\s*(-?[\d,.]+)$", s)
    if match:
        commodity = match.group(1)
        try:
            return Decimal(_normalize_number_string(match.group(2))), commodity
        except Exception:
            return Decimal("0"), commodity

    # Right-side commodity: 500.00 EUR, 1.000,00 EUR
    match = re.match(r"^(-?[\d,.]+)\s*([^\d\s.-]+)$", s)
    if match:
        commodity = match.group(2)
        try:
            return Decimal(_normalize_number_string(match.group(1))), commodity
        except Exception:
            return Decimal("0"), commodity

    # Plain number
    try:
        return Decimal(_normalize_number_string(s)), ""
    except Exception:
        return Decimal("0"), ""


def load_budget_report(
    file: str | Path,
    period: str,
    cache: HledgerCache | None = None,
) -> list[BudgetRow]:
    """Load budget vs actual data for a given period.

    Runs ``hledger balance --budget`` and parses the CSV output.

    Args:
        file: Path to the journal file.
        period: A period string like '2026-02' for hledger's -p flag.
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A list of BudgetRow objects with actual and budget amounts.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_budget_report", str(file), period)
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    output = run_hledger(
        "balance", "--budget", "-p", period, "-O", "csv",
        "--no-total", "Expenses",
        file=file,
    )

    if not output.strip():
        return []

    reader = csv.reader(io.StringIO(output))
    header = next(reader, None)
    if not header or len(header) < 2:
        return []

    rows: list[BudgetRow] = []
    for row in reader:
        if not row or not row[0]:
            continue

        account = row[0].strip().strip('"')

        # hledger --budget CSV has columns: Account, <period>, <period> budget
        # or: Account, <period>
        # The period column contains "actual [=budget]" format
        actual = Decimal("0")
        budget = Decimal("0")
        commodity = ""

        if len(row) >= 2:
            cell = row[1].strip().strip('"')
            # Parse "actual [=budget]" format or just "actual"
            if "=" in cell:
                # Format: "€500.00 [=€800.00]" or similar
                parts = cell.split("=")
                actual_str = parts[0].strip().rstrip("[").strip()
                budget_str = parts[1].strip().rstrip("]").strip()
                actual, commodity = _parse_budget_amount(actual_str)
                budget, _ = _parse_budget_amount(budget_str)
            else:
                actual, commodity = _parse_budget_amount(cell)

        # Check if there's a separate budget column
        if len(row) >= 3 and not budget:
            budget_cell = row[2].strip().strip('"')
            budget, bcom = _parse_budget_amount(budget_cell)
            if not commodity:
                commodity = bcom

        if account and (actual or budget):
            rows.append(BudgetRow(
                account=account,
                actual=actual,
                budget=budget,
                commodity=commodity,
            ))

    if cache is not None:
        cache.put(cache_key, rows, file=file)

    return rows


def load_multi_period_budget_report(
    file: str | Path,
    start: str,
    end: str,
    cache: HledgerCache | None = None,
) -> tuple[list[str], dict[str, list[BudgetRow]]]:
    """Load budget vs actual data for multiple months side-by-side.

    Runs ``hledger balance --budget -p START..END -M -O csv`` and parses the
    CSV output into per-account, per-period rows.

    Args:
        file: Path to the journal file.
        start: First month in ``YYYY-MM`` format (inclusive).
        end: Last month in ``YYYY-MM`` format (inclusive).
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A tuple of:
        - ``periods``: ordered list of period labels as returned by hledger
          (e.g. ``["2025-10", "2025-11", "2026-03"]``).
        - ``rows``: dict mapping account name → list of :class:`BudgetRow`
          with one entry per period (same order as ``periods``).

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_multi_period_budget_report", str(file), start, end)
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    output = run_hledger(
        "balance", "--budget", "-p", f"{start}..{end}", "-M", "-O", "csv",
        "--no-total", "Expenses",
        file=file,
    )

    if not output.strip():
        if cache is not None:
            cache.put(cache_key, ([], {}), file=file)
        return [], {}

    reader = csv.reader(io.StringIO(output))
    header = next(reader, None)
    if not header or len(header) < 2:
        if cache is not None:
            cache.put(cache_key, ([], {}), file=file)
        return [], {}

    # Header row: ["Account", "2025-10", "2025-10 budget", "2025-11", ...]
    # Identify period labels (skip "Account" and "* budget" columns).
    periods: list[str] = []
    period_indices: list[int] = []
    budget_indices: list[int] = []
    for i, col in enumerate(header):
        col = col.strip().strip('"')
        if i == 0:
            continue
        if col.endswith(" budget"):
            budget_indices.append(i)
        else:
            periods.append(col)
            period_indices.append(i)

    rows: dict[str, list[BudgetRow]] = {}
    for row in reader:
        if not row or not row[0]:
            continue
        account = row[0].strip().strip('"')
        budget_rows: list[BudgetRow] = []

        for idx, period in zip(period_indices, periods):
            actual = Decimal("0")
            budget = Decimal("0")
            commodity = ""

            if idx < len(row):
                cell = row[idx].strip().strip('"')
                if "=" in cell:
                    parts = cell.split("=")
                    actual_str = parts[0].strip().rstrip("[").strip()
                    budget_str = parts[1].strip().rstrip("]").strip()
                    actual, commodity = _parse_budget_amount(actual_str)
                    budget, _ = _parse_budget_amount(budget_str)
                elif cell:
                    actual, commodity = _parse_budget_amount(cell)

            # Try dedicated budget column if no inline budget yet
            if not budget and budget_indices:
                b_idx = budget_indices[period_indices.index(idx)] if idx in period_indices else -1
                if b_idx != -1 and b_idx < len(row):
                    budget_cell = row[b_idx].strip().strip('"')
                    budget, bcom = _parse_budget_amount(budget_cell)
                    if not commodity:
                        commodity = bcom

            budget_rows.append(BudgetRow(
                account=account,
                actual=actual,
                budget=budget,
                commodity=commodity,
            ))

        rows[account] = budget_rows

    if cache is not None:
        cache.put(cache_key, (periods, rows), file=file)

    return periods, rows


def load_journal_stats(file: str | Path) -> JournalStats:
    """Load journal statistics (transaction count, account count, commodities).

    Runs ``hledger stats`` for counts and the transaction date span, and
    ``hledger commodities`` for the list.  When the span line is absent but
    transactions exist (older hledger output formats), the span is derived
    from ``print -O json`` as a fallback.

    Args:
        file: Path to the journal file.

    Returns:
        A :class:`JournalStats` instance.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    output = run_hledger("stats", file=file)

    txn_count = 0
    acct_count = 0
    first_date: date | None = None
    last_date: date | None = None
    for line in output.splitlines():
        if re.match(r"^Txns\s+:", line):
            # "Txns                : 3 (1.0 per day)"
            match = re.search(r":\s*(\d+)", line)
            if match:
                txn_count = int(match.group(1))
        elif line.startswith("Accounts"):
            match = re.search(r":\s*(\d+)", line)
            if match:
                acct_count = int(match.group(1))
        elif re.match(r"^Txns span\s+:", line):
            # "Txns span           : 2026-01-15 to 2026-01-18 (3 days)"
            # The end is exclusive (hledger counts days between the bounds).
            match = re.search(
                r":\s*(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})", line
            )
            if match:
                try:
                    first_date = date.fromisoformat(match.group(1))
                    last_date = date.fromisoformat(match.group(2)) - timedelta(days=1)
                except ValueError:
                    first_date = last_date = None

    if txn_count > 0 and last_date is None:
        # Fallback: derive the span from the transaction list itself.
        txns = load_transactions(file)
        dates = [t.date for t in txns if t.date]
        if dates:
            first_date = date.fromisoformat(min(dates))
            last_date = date.fromisoformat(max(dates))

    commodities_output = run_hledger("commodities", file=file)
    commodities = [
        line.strip()
        for line in commodities_output.strip().splitlines()
        if line.strip()
    ]

    return JournalStats(
        transaction_count=txn_count,
        account_count=acct_count,
        commodities=commodities,
        first_date=first_date,
        last_date=last_date,
    )


def load_period_summary(
    file: str | Path,
    period: str | None = None,
    cache: HledgerCache | None = None,
    commodity: str | None = None,
) -> PeriodSummary:
    """Load income, expense, and investment totals for a single period.

    Two separate queries are used: one for income/expenses (converted to the
    target commodity when one is resolved) and one for investment accounts
    with ``-B`` (at cost) so that non-EUR commodities are converted to the
    purchase price without affecting the income/expense amounts.

    Amounts are summed per commodity and, when a target commodity is
    resolved, only that commodity contributes to the totals: hledger leaves
    commodities without a price unconverted, and adding ``0.01 BTC`` to a euro
    amount would produce a meaningless number.  Without a target the previous
    summing behaviour is kept and the total is labelled with the first
    commodity seen; the Summary's per-currency marquee shows the composition.

    Args:
        file: Path to the journal file.
        period: A period string like ``'2026-02'`` for hledger's ``-p`` flag.
            When ``None``, all transactions across the entire journal are
            included (no ``-p`` flag is passed).
        cache: Optional cache instance to avoid repeated subprocess calls.
        commodity: Optional target commodity for conversion (``-X``) applied
            to the income/expense queries only; the investments query stays at
            cost (``-B``).  Requires prices for conversion; unconverted
            commodities are excluded from the totals.

    Returns:
        A :class:`PeriodSummary` instance.  When ``commodity`` is given the
        totals only cover it.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_period_summary", str(file), period, commodity)
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    from hledger_textual.widgets.formatting import split_raw_commodities

    period_args = ("-p", period) if period else ()
    x_args = ("-X", commodity, "--infer-market-prices") if commodity else ()

    def _sum_by_commodity(output: str) -> dict[str, Decimal]:
        """Split a flat balance CSV into absolute totals per commodity."""
        totals: dict[str, Decimal] = {}
        reader = csv.reader(io.StringIO(output))
        next(reader, None)  # skip header
        for row in reader:
            if len(row) < 2 or not row[0]:
                continue
            for sub in split_raw_commodities(row[1].strip()):
                qty, com = _parse_budget_amount(sub)
                totals[com] = totals.get(com, Decimal("0")) + abs(qty)
        return totals

    # Query 1a/1b and 2 are independent: run them concurrently so the pane
    # waits for the slowest query instead of their sum.
    def _income_query() -> str:
        return run_hledger(
            "balance", "type:R",
            *period_args, *x_args, "--flat", "--no-total", "-O", "csv",
            file=file,
        )

    def _expense_query() -> str:
        return run_hledger(
            "balance", "type:X",
            *period_args, *x_args, "--flat", "--no-total", "-O", "csv",
            file=file,
        )

    def _investment_query() -> str | None:
        try:
            return run_hledger(
                "balance", "assets:investments",
                "-B",
                *period_args, "--flat", "--no-total", "-O", "csv",
                file=file,
            )
        except HledgerError:
            return None  # no investments or hledger error, keep 0

    output_r, output_x, inv_output = gather_loads(
        [_income_query, _expense_query, _investment_query]
    )
    if isinstance(output_r, Exception):
        raise output_r
    if isinstance(output_x, Exception):
        raise output_x

    # Query 1a: income/revenue accounts (type:R — respects account type metadata)
    income_by_commodity = _sum_by_commodity(output_r)

    # Query 1b: expense accounts (type:X — respects account type metadata)
    expenses_by_commodity = _sum_by_commodity(output_x)

    # Query 2: investments at cost (-B converts units to purchase price)
    investments_by_commodity: dict[str, Decimal] = {}
    if isinstance(inv_output, Exception):
        raise inv_output
    if inv_output is not None:
        inv_reader = csv.reader(io.StringIO(inv_output))
        next(inv_reader, None)  # skip header
        for row in inv_reader:
            if len(row) < 2 or not row[0]:
                continue
            qty, com = _parse_budget_amount(row[1].strip())
            if qty > 0:
                investments_by_commodity[com] = (
                    investments_by_commodity.get(com, Decimal("0")) + qty
                )

    # A conversion target was requested via -X, so trust it directly: a
    # leftover unconverted commodity in a mixed cell must not relabel the
    # converted total, and must not be added to it either.
    if commodity:
        commodity_out = commodity
        income = income_by_commodity.get(commodity, Decimal("0"))
        expenses = expenses_by_commodity.get(commodity, Decimal("0"))
        investments = investments_by_commodity.get(commodity, Decimal("0"))
    else:
        # No target resolved: keep summing every commodity and label the total
        # with the first one seen (the Summary's per-currency marquee shows the
        # actual composition).  Callers that resolve a default currency (the
        # Summary pane does) take the single-currency path above.
        commodity_out = next(
            (
                com
                for totals in (
                    income_by_commodity,
                    expenses_by_commodity,
                    investments_by_commodity,
                )
                for com in totals
            ),
            "",
        )
        income = sum(income_by_commodity.values(), Decimal("0"))
        expenses = sum(expenses_by_commodity.values(), Decimal("0"))
        investments = sum(investments_by_commodity.values(), Decimal("0"))

    result = PeriodSummary(
        income=income, expenses=expenses,
        commodity=commodity_out, investments=investments,
    )

    if cache is not None:
        cache.put(cache_key, result, file=file)

    return result


def _period_side_by_commodity(
    file: str | Path,
    side: str,
    period: str | None,
    cache: HledgerCache | None,
) -> list[tuple[str, Decimal]]:
    """Shared helper: |sum| of ``side`` (``type:R``/``type:X``) per commodity.

    Runs a flat ``balance`` CSV query and splits multi-commodity cells.  The
    result is cached per (function, file, period) — the cache key includes the
    loader name so income/expense/net entries cannot alias.
    """
    from hledger_textual.widgets.formatting import split_raw_commodities

    cache_key = (f"load_period_{side}_by_commodity", str(file), period)
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    period_args = ("-p", period) if period else ()
    output = run_hledger(
        "balance", side,
        *period_args, "--flat", "--no-total", "-O", "csv",
        file=file,
    )
    reader = csv.reader(io.StringIO(output))
    next(reader, None)  # skip header
    sums: dict[str, Decimal] = {}
    for row in reader:
        if len(row) < 2 or not row[0]:
            continue
        for sub in split_raw_commodities(row[1]):
            qty, com = _parse_budget_amount(sub)
            if com:
                sums[com] = sums.get(com, Decimal("0")) + abs(qty)

    result = sorted(sums.items())

    if cache is not None:
        cache.put(cache_key, result, file=file)

    return result


def load_period_income_by_commodity(
    file: str | Path,
    period: str | None = None,
    cache: HledgerCache | None = None,
) -> list[tuple[str, Decimal]]:
    """Income per commodity for the period (no ``-X`` conversion)."""
    return _period_side_by_commodity(file, "type:R", period, cache)


def load_period_expenses_by_commodity(
    file: str | Path,
    period: str | None = None,
    cache: HledgerCache | None = None,
) -> list[tuple[str, Decimal]]:
    """Expenses per commodity for the period (no ``-X`` conversion)."""
    return _period_side_by_commodity(file, "type:X", period, cache)


def load_period_flows_by_commodity(
    file: str | Path,
    period: str | None = None,
    cache: HledgerCache | None = None,
) -> tuple[
    list[tuple[str, Decimal]],
    list[tuple[str, Decimal]],
    list[tuple[str, Decimal]],
]:
    """Load income, expenses and net per commodity for a period.

    Fetches the raw ``type:R`` / ``type:X`` balance pairs once and derives all
    three views, so callers that need more than one of them avoid duplicate
    hledger invocations.

    Args:
        file: Path to the journal file.
        period: A period string like ``'2026-02'``, or ``None`` for all time.
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        ``(income, expenses, net)`` as sorted ``(commodity, amount)`` lists.
        ``net`` is ``income - expenses`` per commodity.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    results = gather_loads(
        [
            lambda: _period_side_by_commodity(file, "type:R", period, cache),
            lambda: _period_side_by_commodity(file, "type:X", period, cache),
        ]
    )
    income_result, expenses_result = results
    if isinstance(income_result, Exception):
        raise income_result
    if isinstance(expenses_result, Exception):
        raise expenses_result

    income = dict(income_result)
    expenses = dict(expenses_result)
    net = sorted(
        (com, income.get(com, Decimal("0")) - expenses.get(com, Decimal("0")))
        for com in income.keys() | expenses.keys()
    )
    return income_result, expenses_result, net


def load_period_net_by_commodity(
    file: str | Path,
    period: str | None = None,
    cache: HledgerCache | None = None,
) -> list[tuple[str, Decimal]]:
    """Load net income per commodity for a period, without any conversion.

    Runs the same ``type:R`` / ``type:X`` balance queries as
    :func:`load_period_summary` but never applies ``-X``, splits the
    multi-commodity CSV cells, and computes ``|income| - |expenses|`` per
    commodity.  This feeds the Summary pane's per-currency balance line.

    Args:
        file: Path to the journal file.
        period: A period string like ``'2026-02'``, or ``None`` for all time.
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A sorted list of ``(commodity, net)`` tuples.  Commodities with no
        amounts are omitted; a commodity present on only one side appears
        with its absolute net.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    return load_period_flows_by_commodity(file, period, cache)[2]


def _parse_breakdown_csv(
    output: str, commodity: str | None
) -> list[tuple[str, Decimal, str]]:
    """Parse a flat ``balance`` CSV into ``(account, amount, commodity)`` rows.

    Multi-commodity cells (``"£8.99, €14.99"``) are split into one row per
    commodity instead of being dropped, and amounts are summed per
    ``(account, commodity)`` pair.

    Args:
        output: Raw CSV output of an hledger ``balance --flat --no-total`` call.
        commodity: The conversion target (``-X``) the query used, if any.
            Rows already in this commodity are sorted first.

    Returns:
        A list of ``(account, quantity, commodity)`` tuples.  Rows in the
        target commodity come first, sorted by amount descending; rows in
        other commodities follow (values across commodities are not
        comparable), also sorted by amount descending.
    """
    from hledger_textual.widgets.formatting import split_raw_commodities

    sums: dict[tuple[str, str], Decimal] = {}
    reader = csv.reader(io.StringIO(output))
    next(reader, None)  # skip header
    for row in reader:
        if len(row) < 2 or not row[0]:
            continue
        account = row[0].strip()
        for sub in split_raw_commodities(row[1].strip()):
            qty, com = _parse_budget_amount(sub)
            if not qty:
                continue
            key = (account, com)
            sums[key] = sums.get(key, Decimal("0")) + abs(qty)

    def _sort_key(item: tuple[tuple[str, str], Decimal]) -> tuple[bool, Decimal, str]:
        (account, com), amount = item
        return (com != commodity, -amount, account)

    return [
        (account, amount, com)
        for (account, com), amount in sorted(sums.items(), key=_sort_key)
    ]


def _load_account_breakdown(
    file: str | Path,
    account_type: str,
    period: str,
    commodity: str | None = None,
    cache: HledgerCache | None = None,
) -> list[tuple[str, Decimal, str]]:
    """Load per-account breakdown for a single period.

    Args:
        file: Path to the journal file.
        account_type: The account type query (e.g. ``"type:X"`` for expenses
            or ``"type:R"`` for revenue/income).
        period: A period string like ``'2026-02'``.
        commodity: Optional target commodity for conversion (``-X``) with
            ``--infer-market-prices``, so amounts in different commodities
            become comparable.  Commodities without a price stay unchanged
            (hledger's ``-X`` semantics).
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A list of ``(account, quantity, commodity)`` tuples sorted by amount
        descending.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_account_breakdown", str(file), account_type, period, commodity)
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    args = [
        "balance", account_type,
        "-p", period, "--flat", "--no-total", "-O", "csv",
    ]
    if commodity:
        args.extend(["-X", commodity, "--infer-market-prices"])
    output = run_hledger(*args, file=file)
    result = _parse_breakdown_csv(output, commodity)

    if cache is not None:
        cache.put(cache_key, result, file=file)

    return result


def load_expense_breakdown(
    file: str | Path,
    period: str,
    commodity: str | None = None,
    cache: HledgerCache | None = None,
) -> list[tuple[str, Decimal, str]]:
    """Load per-account expense breakdown for a single period.

    Args:
        file: Path to the journal file.
        period: A period string like ``'2026-02'``.
        commodity: Optional target commodity for ``-X`` conversion.
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A list of ``(account, quantity, commodity)`` tuples sorted by amount
        descending.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    return _load_account_breakdown(file, "type:X", period, commodity, cache)


def load_income_breakdown(
    file: str | Path,
    period: str,
    commodity: str | None = None,
    cache: HledgerCache | None = None,
) -> list[tuple[str, Decimal, str]]:
    """Load per-account income breakdown for a single period.

    Args:
        file: Path to the journal file.
        period: A period string like ``'2026-02'``.
        commodity: Optional target commodity for ``-X`` conversion.
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A list of ``(account, quantity, commodity)`` tuples sorted by amount
        descending.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    return _load_account_breakdown(file, "type:R", period, commodity, cache)


def load_liabilities_breakdown(
    file: str | Path,
    commodity: str | None = None,
    cache: HledgerCache | None = None,
) -> list[tuple[str, Decimal, str]]:
    """Load per-account liabilities breakdown (total outstanding balance).

    Uses ``type:L`` to match liability accounts and returns the current
    total balance (no period filter), sorted by amount descending.

    Args:
        file: Path to the journal file.
        commodity: Optional target commodity for ``-X`` conversion, so
            liabilities held in different commodities can be compared.
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A list of ``(account, quantity, commodity)`` tuples sorted by
        amount descending.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_liabilities_breakdown", str(file), commodity)
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    args = ["balance", "type:L", "--flat", "--no-total", "-O", "csv"]
    if commodity:
        args.extend(["-X", commodity, "--infer-market-prices"])
    output = run_hledger(*args, file=file)
    result = _parse_breakdown_csv(output, commodity)

    if cache is not None:
        cache.put(cache_key, result, file=file)

    return result


def _load_investment_balance(
    file: str | Path,
    cache: HledgerCache | None = None,
) -> list[tuple[str, list[Amount]]]:
    """Load investment account balances with cost annotations.

    Uses a single ``balance -O json`` call, which (unlike the CSV output)
    preserves the cost of each lot.  Both positions and book values are
    derived from this one result.

    Args:
        file: Path to the journal file.
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A list of ``(account, amounts)`` pairs in hledger's account order.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_investment_balance", str(file))
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    output = run_hledger(
        "balance", "acct:assets:investments",
        "--flat", "--no-total", "-O", "json",
        file=file,
    )
    data = json.loads(output) if output.strip() else []
    rows = data[0] if isinstance(data, list) and data else []

    balances: list[tuple[str, list[Amount]]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 4 or not row[0]:
            continue
        amount_data = row[3] if isinstance(row[3], list) else []
        amounts = [
            _parse_amount(item) for item in amount_data if isinstance(item, dict)
        ]
        balances.append((row[0], amounts))

    if cache is not None:
        cache.put(cache_key, balances, file=file)

    return balances


def _positions_from_balances(
    balances: list[tuple[str, list[Amount]]],
) -> list[tuple[str, Decimal, str]]:
    """Derive investment positions from parsed balance amounts."""
    totals: dict[tuple[str, str], Decimal] = {}
    for account, amounts in balances:
        for amount in amounts:
            # Skip currency balances (e.g. €): the portfolio tracks units.
            if not amount.commodity or len(amount.commodity) <= 1:
                continue
            key = (account, amount.commodity)
            totals[key] = totals.get(key, Decimal("0")) + amount.quantity

    return [
        (account, quantity, commodity)
        for (account, commodity), quantity in sorted(totals.items())
        if quantity
    ]


def _cost_from_balances(
    balances: list[tuple[str, list[Amount]]],
) -> dict[str, tuple[Decimal, str]]:
    """Derive per-account book values from parsed balance amounts.

    When a balance carries a cost annotation, the total cost is used (signed by
    the position's direction).  Amounts without a cost keep their own value.
    If an account holds costs in multiple commodities, the largest book value
    wins so the result stays comparable with the portfolio's market value.
    """
    result: dict[str, tuple[Decimal, str]] = {}
    totals_by_account: dict[str, dict[str, Decimal]] = {}
    for account, amounts in balances:
        by_commodity = totals_by_account.setdefault(account, {})
        for amount in amounts:
            if not amount.quantity:
                continue
            if amount.cost is not None:
                quantity = abs(amount.cost.quantity)
                if amount.quantity < 0:
                    quantity = -quantity
                commodity = amount.cost.commodity
            else:
                quantity = amount.quantity
                commodity = amount.commodity
            by_commodity[commodity] = (
                by_commodity.get(commodity, Decimal("0")) + quantity
            )
    for account, by_commodity in totals_by_account.items():
        if not by_commodity:
            continue
        commodity = max(by_commodity, key=lambda com: abs(by_commodity[com]))
        result[account] = (by_commodity[commodity], commodity)
    return result


def load_investment_portfolio(
    file: str | Path,
    cache: HledgerCache | None = None,
) -> tuple[
    list[tuple[str, Decimal, str]],
    dict[str, tuple[Decimal, str]],
]:
    """Load positions and book values with one hledger invocation.

    Args:
        file: Path to the journal file.
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        ``(positions, cost_by_account)`` matching
        :func:`load_investment_positions` and :func:`load_investment_cost`.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_investment_portfolio", str(file))
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    balances = _load_investment_balance(file, cache)
    result = (
        _positions_from_balances(balances),
        _cost_from_balances(balances),
    )
    if cache is not None:
        cache.put(cache_key, result, file=file)
    return result


def load_investment_positions(
    file: str | Path,
    cache: HledgerCache | None = None,
) -> list[tuple[str, Decimal, str]]:
    """Load current investment positions (account, quantity, commodity).

    Returns one entry per account holding a non-EUR commodity under
    ``assets:investments``.

    Args:
        file: Path to the journal file.
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A list of ``(account, quantity, commodity)`` tuples.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_investment_positions", str(file))
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    result = _positions_from_balances(_load_investment_balance(file, cache))
    if cache is not None:
        cache.put(cache_key, result, file=file)
    return result


def load_investment_cost(
    file: str | Path,
    cache: HledgerCache | None = None,
) -> dict[str, tuple[Decimal, str]]:
    """Load the book value (purchase cost) of investment accounts.

    Args:
        file: Path to the journal file.
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A dict mapping account name to ``(amount, commodity)``.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_investment_cost", str(file))
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    result = _cost_from_balances(_load_investment_balance(file, cache))
    if cache is not None:
        cache.put(cache_key, result, file=file)
    return result


def load_investment_eur_by_account(
    file: str | Path,
    prices_file: Path,
    cache: HledgerCache | None = None,
) -> dict[str, tuple[Decimal, str]]:
    """Load the market value of investment accounts using a prices file.

    Args:
        file: Path to the journal file.
        prices_file: Path to a journal file containing ``P`` price directives.
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A dict mapping account name to ``(amount, commodity)``.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_investment_eur_by_account", str(file), str(prices_file))
    if cache is not None:
        cached = cache.get(cache_key, file=file, extra_files=[prices_file])
        if cached is not None:
            return cached

    output = run_hledger(
        "balance", "acct:assets:investments",
        "--flat", "--no-total", "-V", "-O", "csv",
        "-f", str(prices_file),
        file=file,
    )

    result: dict[str, tuple[Decimal, str]] = {}
    reader = csv.reader(io.StringIO(output))
    next(reader, None)  # skip header
    for row in reader:
        if len(row) < 2 or not row[0]:
            continue
        account = row[0].strip()
        qty, com = _parse_budget_amount(row[1].strip())
        result[account] = (qty, com)

    if cache is not None:
        cache.put(cache_key, result, file=file, extra_files=[prices_file])

    return result


def load_investment_report(
    file: str | Path,
    period_begin: str | None = None,
    period_end: str | None = None,
    commodity: str | None = None,
    cache: HledgerCache | None = None,
) -> ReportData:
    """Load a multi-period investment balance report from hledger.

    Queries ``assets:investments`` with ``hledger bal -M -O csv --flat``
    and parses the result using the same CSV format as IS/BS/CF reports.

    Args:
        file: Path to the journal file.
        period_begin: Optional begin date (``YYYY-MM-DD``) for ``-b`` flag.
        period_end: Optional end date (``YYYY-MM-DD``) for ``-e`` flag.
        commodity: Optional commodity code for ``-X`` flag.
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A :class:`ReportData` with the parsed investment data.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = (
        "load_investment_report",
        str(file),
        period_begin,
        period_end,
        commodity,
    )
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    args = ["bal", "assets:investments", "-M", "-O", "csv", "--flat"]
    if commodity:
        args.extend(["-X", commodity])
    if period_begin:
        args.extend(["-b", period_begin])
    if period_end:
        args.extend(["-e", period_end])

    output = run_hledger(*args, file=file)
    result = _parse_report_csv(output)

    if cache is not None:
        cache.put(cache_key, result, file=file)

    return result


def _parse_report_csv(output: str) -> ReportData:
    """Parse CSV output from hledger is/bs/cf into a ReportData.

    The CSV format produced by ``hledger {is|bs|cf} -M -O csv`` is:

    - Row 0: title (e.g. ``"Monthly Income Statement 2026-01..2026-02","",""``)
    - Row 1: column headers (``"Account","Jan","Feb"``)
    - Remaining rows: data — section headers have all-empty amount cells,
      totals start with ``Total:`` or ``Net:``.

    Args:
        output: Raw CSV text from hledger.

    Returns:
        A :class:`ReportData` with parsed title, headers, and rows.
    """
    if not output.strip():
        return ReportData(title="", period_headers=[], rows=[])

    reader = csv.reader(io.StringIO(output))
    rows_raw = list(reader)

    if len(rows_raw) < 2:
        return ReportData(title="", period_headers=[], rows=[])

    # Row 0: title
    title = rows_raw[0][0].strip() if rows_raw[0] else ""

    # Row 1: headers — first column is "Account", rest are period labels
    header_row = rows_raw[1]
    period_headers = [h.strip() for h in header_row[1:]] if len(header_row) > 1 else []

    # Remaining rows: data
    parsed_rows: list[ReportRow] = []
    for row in rows_raw[2:]:
        if not row:
            continue

        account, depth = _parse_tree_account(row[0])
        if not account:
            continue

        amounts = [cell.strip() for cell in row[1:]]

        is_total = account.lower().startswith("total:") or account.lower().startswith("net:")
        is_section_header = (
            not is_total
            and all(a == "" or a == "0" for a in amounts)
        )

        parsed_rows.append(ReportRow(
            account=account,
            amounts=amounts,
            is_section_header=is_section_header,
            is_total=is_total,
            depth=depth,
        ))

    return ReportData(
        title=title,
        period_headers=period_headers,
        rows=parsed_rows,
    )


def load_report(
    file: str | Path,
    report_type: str,
    period_begin: str | None = None,
    period_end: str | None = None,
    commodity: str | None = None,
    sort_amount: bool = False,
    cache: HledgerCache | None = None,
    mode: Literal["tree", "flat"] = "flat",
) -> ReportData:
    """Load a multi-period financial report from hledger.

    Supported report types: ``is`` (Income Statement), ``bs`` (Balance Sheet),
    ``cf`` (Cash Flow).

    Args:
        file: Path to the journal file.
        report_type: One of ``"is"``, ``"bs"``, or ``"cf"``.
        period_begin: Optional begin date (``YYYY-MM-DD``) for ``-b`` flag.
        period_end: Optional end date (``YYYY-MM-DD``) for ``-e`` flag.
        commodity: Optional commodity code for ``-X`` flag to convert
            multi-commodity amounts into a single commodity.
        cache: Optional cache instance to avoid repeated subprocess calls.
        mode: ``"flat"`` (default) renders fully qualified leaf accounts;
            ``"tree"`` renders a hierarchical view with parent subtotals.

    Returns:
        A :class:`ReportData` with the parsed report.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_report", str(file), report_type, period_begin, period_end, commodity, sort_amount, mode)
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    args = [report_type, "-M", "-O", "csv", "--no-elide", f"--{mode}"]
    if sort_amount:
        args.append("--sort-amount")
    if commodity:
        args.extend(["-X", commodity])
    if period_begin:
        args.extend(["-b", period_begin])
    if period_end:
        args.extend(["-e", period_end])

    output = run_hledger(*args, file=file)
    result = _parse_report_csv(output)

    if cache is not None:
        cache.put(cache_key, result, file=file)

    return result


def run_custom_report(file: str | Path, command: str) -> str:
    """Run a custom hledger command and return the raw text output.

    The ``command`` string is split with :func:`shlex.split`, so quoting
    rules follow standard shell conventions.

    Args:
        file: Path to the journal file.
        command: hledger argument string without the ``-f`` flag
            (e.g. ``"balance expenses --tree -M"``).

    Returns:
        The raw stdout output as a string.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    args = shlex.split(command)
    return run_hledger(*args, file=file)
