"""Interface to the hledger CLI for reading journal data."""

from __future__ import annotations

import csv
import io
import json
import subprocess
from decimal import Decimal
from pathlib import Path

import re

from hledger_tui.models import (
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
    cmd = ["hledger"]
    if file is not None:
        cmd.extend(["-f", str(file)])
    cmd.extend(args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
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
    file: str | Path, query: str | None = None, reverse: bool = False
) -> list[Transaction]:
    """Load transactions from a journal file, optionally filtered by a query.

    Args:
        file: Path to the journal file.
        query: An hledger query string (e.g. 'acct:^assets:bank$'). When
            provided it is appended to the hledger print command so that only
            matching transactions are returned.
        reverse: If True, return transactions in reverse order (newest first).

    Returns:
        A list of Transaction objects.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    args = ["print", "-O", "json"]
    if query:
        args.extend(query.split())
    output = run_hledger(*args, file=file)
    data = json.loads(output)
    txns = [_parse_transaction(t) for t in data]
    return list(reversed(txns)) if reverse else txns


def load_account_balances(file: str | Path) -> list[tuple[str, str]]:
    """Load all accounts with their current balances.

    Args:
        file: Path to the journal file.

    Returns:
        A list of (account_name, balance_string) tuples, ordered as hledger
        returns them (alphabetical by account name).

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    output = run_hledger("balance", "--flat", "--no-total", "-O", "csv", file=file)
    reader = csv.reader(io.StringIO(output))
    next(reader, None)  # skip header row ("account","balance")
    return [
        (row[0], row[1])
        for row in reader
        if len(row) >= 2 and row[0] and row[1]
    ]


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


def load_budget_report(file: str | Path, period: str) -> list[BudgetRow]:
    """Load budget vs actual data for a given period.

    Runs ``hledger balance --budget`` and parses the CSV output.

    Args:
        file: Path to the journal file.
        period: A period string like '2026-02' for hledger's -p flag.

    Returns:
        A list of BudgetRow objects with actual and budget amounts.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
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

    return rows


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


def load_period_summary(file: str | Path, period: str) -> PeriodSummary:
    """Load income, expense, and investment totals for a single period.

    Two separate queries are used: one for income/expenses (unmodified) and
    one for investment accounts with ``-B`` (at cost) so that non-EUR
    commodities are converted to the purchase price without affecting the
    income/expense amounts.

    Args:
        file: Path to the journal file.
        period: A period string like ``'2026-02'`` for hledger's ``-p`` flag.

    Returns:
        A :class:`PeriodSummary` instance.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    # Query 1: income and expenses (no -B, keeps original amounts)
    output = run_hledger(
        "balance", "income", "expenses",
        "-p", period, "--flat", "--no-total", "-O", "csv",
        file=file,
    )

    income = Decimal("0")
    expenses = Decimal("0")
    commodity = ""

    reader = csv.reader(io.StringIO(output))
    next(reader, None)  # skip header
    for row in reader:
        if len(row) < 2 or not row[0]:
            continue
        account = row[0].strip().lower()
        qty, com = _parse_budget_amount(row[1].strip())
        if not commodity and com:
            commodity = com
        if account.startswith("income"):
            income += abs(qty)
        elif account.startswith("expenses"):
            expenses += abs(qty)

    # Query 2: investments at cost (-B converts units to purchase price)
    investments = Decimal("0")
    try:
        inv_output = run_hledger(
            "balance", "assets:investments",
            "-B",
            "-p", period, "--flat", "--no-total", "-O", "csv",
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
            investments += abs(qty)
    except HledgerError:
        pass  # no investments or hledger error, keep 0

    return PeriodSummary(
        income=income, expenses=expenses,
        commodity=commodity, investments=investments,
    )


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
    output = run_hledger(
        "balance", "expenses",
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

        account = row[0].strip()
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
) -> ReportData:
    """Load a multi-period financial report from hledger.

    Supported report types: ``is`` (Income Statement), ``bs`` (Balance Sheet),
    ``cf`` (Cash Flow).

    Args:
        file: Path to the journal file.
        report_type: One of ``"is"``, ``"bs"``, or ``"cf"``.
        period_begin: Optional begin date (``YYYY-MM-DD``) for ``-b`` flag.
        period_end: Optional end date (``YYYY-MM-DD``) for ``-e`` flag.

    Returns:
        A :class:`ReportData` with the parsed report.

    Raises:
        HledgerError: If hledger fails or is not found.
    """
    args = [report_type, "-M", "-O", "csv", "--no-elide"]
    if period_begin:
        args.extend(["-b", period_begin])
    if period_end:
        args.extend(["-e", period_end])

    output = run_hledger(*args, file=file)
    return _parse_report_csv(output)
