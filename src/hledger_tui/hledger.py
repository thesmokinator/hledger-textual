"""Interface to the hledger CLI for reading journal data."""

from __future__ import annotations

import csv
import io
import json
import subprocess
from decimal import Decimal
from pathlib import Path

from hledger_tui.models import (
    Amount,
    AmountStyle,
    Posting,
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


def check_journal(file: str | Path) -> None:
    """Validate a journal file using hledger check.

    Args:
        file: Path to the journal file.

    Raises:
        HledgerError: If the journal is invalid.
    """
    run_hledger("check", file=file)


def _parse_amount(data: dict) -> Amount:
    """Parse an amount from hledger JSON."""
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

    return Amount(
        commodity=data["acommodity"],
        quantity=quantity,
        style=style,
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
