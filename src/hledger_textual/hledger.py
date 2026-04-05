"""Interface to the hledger CLI for reading journal data."""

from __future__ import annotations

import csv
import io
import json
import shlex
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import Literal

import re

from hledger_textual.models import (
    Amount,
    AmountStyle,
    BudgetRow,
    JournalStats,
    PeriodSummary,
    Posting,
    ReportData,
    ReportRow,
    SourcePosition,
    Transaction,
    TransactionStatus,
)


class HledgerError(Exception):
    """Raised when an hledger command fails."""


def run_hledger(*args: str, file: str | Path | None = None) -> str:
    """Run an hledger command and return stdout.

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

    try:
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
    cache: "HledgerCache | None" = None,
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
    cache: "HledgerCache | None" = None,
) -> list[tuple[str, str]]:
    """Load all accounts with their current balances.

    Args:
        file: Path to the journal file.
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A list of (account_name, balance_string) tuples, ordered as hledger
        returns them (alphabetical by account name).

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_account_balances", str(file))
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    output = run_hledger("balance", "--flat", "--no-total", "-O", "csv", file=file)
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


def load_account_tree_balances(file: str | Path) -> list["AccountNode"]:
    """Load accounts as a tree with hierarchical balances.

    Uses ``hledger balance --tree`` to get indented account names with
    subtotals for parent accounts.

    Args:
        file: Path to the journal file.

    Returns:
        A list of root-level :class:`AccountNode` instances, each with
        nested children reflecting the account hierarchy.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    from hledger_textual.models import AccountNode

    output = run_hledger("balance", "--tree", "--no-total", "-O", "csv", file=file)
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


def load_account_directives(file: str | Path) -> dict[str, "AccountDirective"]:
    """Parse ``account`` directives and their comments from a journal file.

    Reads the file directly (the hledger CLI does not export directive
    comments).  Supports both single-line and multi-line comments::

        account expenses:groceries  ; note:Weekly shopping
            ; category:food

    Args:
        file: Path to the journal file.

    Returns:
        A dict mapping full account names to :class:`AccountDirective`
        instances.  Only accounts that have an ``account`` directive in
        the file are included.
    """
    from hledger_textual.models import AccountDirective

    path = Path(file)
    if not path.exists():
        return {}

    directives: dict[str, AccountDirective] = {}
    current: AccountDirective | None = None

    for line in path.read_text(encoding="utf-8").splitlines():
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
) -> None:
    """Add or update an ``account`` directive in the journal file.

    If the account already has a directive, its comment is replaced.
    Otherwise a new directive is appended at the top of the file (after
    any leading comments/blanks).

    Args:
        file: Path to the journal file.
        account: Full account name (e.g. ``"expenses:groceries"``).
        comment: The comment text (without leading ``;``).  If empty,
            any existing comment is removed but the directive is kept.
    """
    path = Path(file)
    lines = path.read_text(encoding="utf-8").splitlines()
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
        # Insert before the first transaction (first line starting with a date)
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

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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

    # Left-side commodity: €500.00
    match = re.match(r"^([^\d\s.-]+)\s*(-?[\d,.]+)$", s)
    if match:
        commodity = match.group(1)
        num_str = match.group(2).replace(",", "")
        try:
            return Decimal(num_str), commodity
        except Exception:
            return Decimal("0"), commodity

    # Right-side commodity: 500.00 EUR
    match = re.match(r"^(-?[\d,.]+)\s*([^\d\s.-]+)$", s)
    if match:
        num_str = match.group(1).replace(",", "")
        commodity = match.group(2)
        try:
            return Decimal(num_str), commodity
        except Exception:
            return Decimal("0"), commodity

    # Plain number
    try:
        return Decimal(s.replace(",", "")), ""
    except Exception:
        return Decimal("0"), ""


def load_budget_report(
    file: str | Path,
    period: str,
    cache: "HledgerCache | None" = None,
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
) -> tuple[list[str], dict[str, list[BudgetRow]]]:
    """Load budget vs actual data for multiple months side-by-side.

    Runs ``hledger balance --budget -p START..END -M -O csv`` and parses the
    CSV output into per-account, per-period rows.

    Args:
        file: Path to the journal file.
        start: First month in ``YYYY-MM`` format (inclusive).
        end: Last month in ``YYYY-MM`` format (inclusive).

    Returns:
        A tuple of:
        - ``periods``: ordered list of period labels as returned by hledger
          (e.g. ``["2025-10", "2025-11", "2026-03"]``).
        - ``rows``: dict mapping account name → list of :class:`BudgetRow`
          with one entry per period (same order as ``periods``).

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    output = run_hledger(
        "balance", "--budget", "-p", f"{start}..{end}", "-M", "-O", "csv",
        "--no-total", "Expenses",
        file=file,
    )

    if not output.strip():
        return [], {}

    reader = csv.reader(io.StringIO(output))
    header = next(reader, None)
    if not header or len(header) < 2:
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

    return periods, rows


def load_journal_stats(file: str | Path) -> JournalStats:
    """Load journal statistics (transaction count, account count, commodities).

    Runs ``hledger stats`` for counts and ``hledger commodities`` for the list.

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
    )


def load_period_summary(
    file: str | Path,
    period: str | None = None,
    cache: "HledgerCache | None" = None,
) -> PeriodSummary:
    """Load income, expense, and investment totals for a single period.

    Two separate queries are used: one for income/expenses (unmodified) and
    one for investment accounts with ``-B`` (at cost) so that non-EUR
    commodities are converted to the purchase price without affecting the
    income/expense amounts.

    Args:
        file: Path to the journal file.
        period: A period string like ``'2026-02'`` for hledger's ``-p`` flag.
            When ``None``, all transactions across the entire journal are
            included (no ``-p`` flag is passed).
        cache: Optional cache instance to avoid repeated subprocess calls.

    Returns:
        A :class:`PeriodSummary` instance.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    cache_key = ("load_period_summary", str(file), period)
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    period_args = ("-p", period) if period else ()

    # Query 1a: income/revenue accounts (type:R — respects account type metadata)
    income = Decimal("0")
    expenses = Decimal("0")
    commodity = ""

    output_r = run_hledger(
        "balance", "type:R",
        *period_args, "--flat", "--no-total", "-O", "csv",
        file=file,
    )
    reader_r = csv.reader(io.StringIO(output_r))
    next(reader_r, None)  # skip header
    for row in reader_r:
        if len(row) < 2 or not row[0]:
            continue
        qty, com = _parse_budget_amount(row[1].strip())
        if not commodity and com:
            commodity = com
        income += abs(qty)

    # Query 1b: expense accounts (type:X — respects account type metadata)
    output_x = run_hledger(
        "balance", "type:X",
        *period_args, "--flat", "--no-total", "-O", "csv",
        file=file,
    )
    reader_x = csv.reader(io.StringIO(output_x))
    next(reader_x, None)  # skip header
    for row in reader_x:
        if len(row) < 2 or not row[0]:
            continue
        qty, com = _parse_budget_amount(row[1].strip())
        if not commodity and com:
            commodity = com
        expenses += abs(qty)

    # Query 2: investments at cost (-B converts units to purchase price)
    investments = Decimal("0")
    try:
        inv_output = run_hledger(
            "balance", "assets:investments",
            "-B",
            *period_args, "--flat", "--no-total", "-O", "csv",
            file=file,
        )
        inv_reader = csv.reader(io.StringIO(inv_output))
        next(inv_reader, None)  # skip header
        for row in inv_reader:
            if len(row) < 2 or not row[0]:
                continue
            qty, com = _parse_budget_amount(row[1].strip())
            if not commodity and com:
                commodity = com
            if qty > 0:
                investments += qty
    except HledgerError:
        pass  # no investments or hledger error, keep 0

    result = PeriodSummary(
        income=income, expenses=expenses,
        commodity=commodity, investments=investments,
    )

    if cache is not None:
        cache.put(cache_key, result, file=file)

    return result


def _load_account_breakdown(
    file: str | Path, account_type: str, period: str
) -> list[tuple[str, Decimal, str]]:
    """Load per-account breakdown for a single period.

    Args:
        file: Path to the journal file.
        account_type: The account type query (e.g. ``"type:X"`` for expenses
            or ``"type:R"`` for revenue/income).
        period: A period string like ``'2026-02'``.

    Returns:
        A list of ``(account, quantity, commodity)`` tuples sorted by amount
        descending.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    output = run_hledger(
        "balance", account_type,
        "-p", period, "--flat", "--no-total", "-O", "csv",
        file=file,
    )

    results: list[tuple[str, Decimal, str]] = []
    reader = csv.reader(io.StringIO(output))
    next(reader, None)  # skip header
    for row in reader:
        if len(row) < 2 or not row[0]:
            continue
        account = row[0].strip()
        qty, com = _parse_budget_amount(row[1].strip())
        if qty:
            results.append((account, abs(qty), com))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def load_expense_breakdown(
    file: str | Path, period: str
) -> list[tuple[str, Decimal, str]]:
    """Load per-account expense breakdown for a single period.

    Args:
        file: Path to the journal file.
        period: A period string like ``'2026-02'``.

    Returns:
        A list of ``(account, quantity, commodity)`` tuples sorted by amount
        descending.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    return _load_account_breakdown(file, "type:X", period)


def load_income_breakdown(
    file: str | Path, period: str
) -> list[tuple[str, Decimal, str]]:
    """Load per-account income breakdown for a single period.

    Args:
        file: Path to the journal file.
        period: A period string like ``'2026-02'``.

    Returns:
        A list of ``(account, quantity, commodity)`` tuples sorted by amount
        descending.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    return _load_account_breakdown(file, "type:R", period)


def load_liabilities_breakdown(
    file: str | Path,
) -> list[tuple[str, Decimal, str]]:
    """Load per-account liabilities breakdown (total outstanding balance).

    Uses ``type:L`` to match liability accounts and returns the current
    total balance (no period filter), sorted by amount descending.

    Args:
        file: Path to the journal file.

    Returns:
        A list of ``(account, quantity, commodity)`` tuples sorted by
        amount descending.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    output = run_hledger(
        "balance", "type:L",
        "--flat", "--no-total", "-O", "csv",
        file=file,
    )

    results: list[tuple[str, Decimal, str]] = []
    reader = csv.reader(io.StringIO(output))
    next(reader, None)  # skip header
    for row in reader:
        if len(row) < 2 or not row[0]:
            continue
        account = row[0].strip()
        qty, com = _parse_budget_amount(row[1].strip())
        if qty:
            results.append((account, abs(qty), com))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def load_investment_positions(
    file: str | Path,
) -> list[tuple[str, Decimal, str]]:
    """Load current investment positions (account, quantity, commodity).

    Returns one entry per account holding a non-EUR commodity under
    ``assets:investments``.

    Args:
        file: Path to the journal file.

    Returns:
        A list of ``(account, quantity, commodity)`` tuples.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    output = run_hledger(
        "balance", "acct:assets:investments",
        "--flat", "--no-total", "-O", "csv",
        file=file,
    )

    results: list[tuple[str, Decimal, str]] = []
    reader = csv.reader(io.StringIO(output))
    next(reader, None)  # skip header
    for row in reader:
        if len(row) < 2 or not row[0]:
            continue
        account = row[0].strip()
        qty, com = _parse_budget_amount(row[1].strip())
        # Skip pure-currency balances (e.g. €)
        if com and len(com) > 1 and qty:
            results.append((account, qty, com))

    return results


def load_investment_cost(
    file: str | Path,
) -> dict[str, tuple[Decimal, str]]:
    """Load the book value (purchase cost) of investment accounts.

    Args:
        file: Path to the journal file.

    Returns:
        A dict mapping account name to ``(amount, commodity)``.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    output = run_hledger(
        "balance", "acct:assets:investments",
        "--flat", "--no-total", "--cost", "-O", "csv",
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

    return result


def load_investment_eur_by_account(
    file: str | Path,
    prices_file: Path,
) -> dict[str, tuple[Decimal, str]]:
    """Load the market value of investment accounts using a prices file.

    Args:
        file: Path to the journal file.
        prices_file: Path to a journal file containing ``P`` price directives.

    Returns:
        A dict mapping account name to ``(amount, commodity)``.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
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

    return result


def load_investment_report(
    file: str | Path,
    period_begin: str | None = None,
    period_end: str | None = None,
    commodity: str | None = None,
) -> ReportData:
    """Load a multi-period investment balance report from hledger.

    Queries ``assets:investments`` with ``hledger bal -M -O csv --flat``
    and parses the result using the same CSV format as IS/BS/CF reports.

    Args:
        file: Path to the journal file.
        period_begin: Optional begin date (``YYYY-MM-DD``) for ``-b`` flag.
        period_end: Optional end date (``YYYY-MM-DD``) for ``-e`` flag.
        commodity: Optional commodity code for ``-X`` flag.

    Returns:
        A :class:`ReportData` with the parsed investment data.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    args = ["bal", "assets:investments", "-M", "-O", "csv", "--flat"]
    if commodity:
        args.extend(["-X", commodity])
    if period_begin:
        args.extend(["-b", period_begin])
    if period_end:
        args.extend(["-e", period_end])

    output = run_hledger(*args, file=file)
    return _parse_report_csv(output)


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
    cache: "HledgerCache | None" = None,
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
    cache_key = ("load_report", str(file), report_type, period_begin, period_end, commodity, mode)
    if cache is not None:
        cached = cache.get(cache_key, file=file)
        if cached is not None:
            return cached

    args = [report_type, "-M", "-O", "csv", "--no-elide", f"--{mode}"]
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
