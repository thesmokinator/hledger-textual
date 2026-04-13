"""Recurring transactions file management: read/write periodic rules in recurring.journal.

Recurring rules are stored as hledger periodic transactions (``~ period``)
in a dedicated ``recurring.journal`` file that lives next to the main journal.
Each rule carries a ``; rule-id:XXX`` tag in its comment for tracking
which transactions have already been generated.
All write operations follow the same backup/validate/restore pattern used
in ``budget.py``.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from hledger_textual.amountutil import parse_amount_string as _parse_amount_string_raw
from hledger_textual.fileutil import safe_write_with_validation
from hledger_textual.hledger import HledgerError, check_journal, load_transactions, run_hledger
from hledger_textual.journal import JournalError, append_transaction
from hledger_textual.models import Amount, AmountStyle, Posting, RecurringRule, Transaction

RECURRING_FILENAME = "recurring.journal"

SUPPORTED_PERIODS: list[str] = [
    "daily",
    "weekly",
    "biweekly",
    "monthly",
    "bimonthly",
    "quarterly",
    "yearly",
]

_INCLUDE_RE = re.compile(r"^\s*include\s+recurring\.journal\s*$", re.MULTILINE)

# Matches: ~ period_expr [from YYYY-MM-DD] [to YYYY-MM-DD]  [; rule-id:xxx [description]]
_HEADER_RE = re.compile(
    r"^~\s+(\S+)"
    r"(?:\s+from\s+(\d{4}-\d{2}-\d{2}))?"
    r"(?:\s+to\s+(\d{4}-\d{2}-\d{2}))?"
    r"\s*(?:;\s*rule-id:(\S+)(?:\s+(.+))?)?"
    r"\s*$"
)

# Posting with amount: at least 4 spaces indent, account, 2+ spaces, amount
_POSTING_RE = re.compile(r"^\s{4,}(\S.+?)\s{2,}(\S+)\s*$")


class RecurringError(Exception):
    """Raised when a recurring file operation fails."""


def ensure_recurring_file(journal_file: Path) -> Path:
    """Create recurring.journal if missing and add include directive to the main journal.

    Args:
        journal_file: Path to the main hledger journal file.

    Returns:
        Path to the recurring.journal file.
    """
    recurring_file = journal_file.parent / RECURRING_FILENAME

    if not recurring_file.exists():
        recurring_file.write_text("", encoding="utf-8")

    journal_text = journal_file.read_text(encoding="utf-8")
    if not _INCLUDE_RE.search(journal_text):
        include_line = f"include {RECURRING_FILENAME}\n"
        if journal_text and not journal_text.startswith("\n"):
            include_line += "\n"
        journal_file.write_text(include_line + journal_text, encoding="utf-8")

    return recurring_file


def _parse_amount_string(s: str) -> tuple[Decimal, str]:
    """Parse an amount string, wrapping ValueError as RecurringError."""
    try:
        return _parse_amount_string_raw(s)
    except ValueError as exc:
        raise RecurringError(str(exc)) from exc


def _parse_posting_line(line: str) -> Posting | None:
    """Parse a posting line from a periodic transaction block.

    Args:
        line: A line from the recurring.journal file.

    Returns:
        A Posting object if the line is a valid posting, or None.
    """
    if not re.match(r"^\s{4,}", line):
        return None

    stripped = line.strip()
    if not stripped:
        return None

    # Try posting with amount (account  amount format)
    m = _POSTING_RE.match(line)
    if m:
        account = m.group(1).strip()
        amount_str = m.group(2).strip()
        try:
            quantity, commodity = _parse_amount_string(amount_str)
            style = AmountStyle(
                commodity_side="L",
                commodity_spaced=False,
                precision=max(
                    abs(quantity.as_tuple().exponent)
                    if isinstance(quantity.as_tuple().exponent, int)
                    else 2,
                    2,
                ),
            )
            return Posting(
                account=account,
                amounts=[Amount(commodity=commodity, quantity=quantity, style=style)],
            )
        except RecurringError:
            pass

    # Balancing posting (no amount — just the account name)
    return Posting(account=stripped, amounts=[])


def parse_recurring_rules(path: Path) -> list[RecurringRule]:
    """Parse recurring rules from a recurring.journal file.

    Reads ``~ period [from date]`` periodic transaction blocks and extracts
    account + amount postings, tracking each rule by its ``rule-id`` tag.

    Args:
        path: Path to the recurring.journal file.

    Returns:
        A list of RecurringRule objects (only rules with a rule-id tag).
    """
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8")
    if not content.strip():
        return []

    rules: list[RecurringRule] = []
    current_header: dict | None = None
    current_postings: list[Posting] = []

    def _flush() -> None:
        """Append the current rule to the list."""
        if current_header is None:
            return
        if not current_header.get("rule_id"):
            return
        rules.append(
            RecurringRule(
                rule_id=current_header["rule_id"],
                period_expr=current_header["period_expr"],
                description=current_header["description"],
                start_date=current_header["start_date"],
                end_date=current_header["end_date"],
                postings=current_postings[:],
            )
        )

    for line in content.splitlines():
        header_match = _HEADER_RE.match(line)
        if header_match:
            _flush()
            current_postings = []
            current_header = {
                "period_expr": header_match.group(1),
                "start_date": header_match.group(2),
                "end_date": header_match.group(3),
                "rule_id": header_match.group(4) or "",
                "description": (header_match.group(5) or "").strip(),
            }
            continue

        if current_header is not None:
            # Non-indented non-empty line ends the block
            if line and not line[0].isspace():
                _flush()
                current_header = None
                current_postings = []
                continue

            if not line.strip():
                continue

            posting = _parse_posting_line(line)
            if posting is not None:
                current_postings.append(posting)

    _flush()
    return rules


def _format_recurring_file(rules: list[RecurringRule]) -> str:
    """Format recurring rules into the recurring.journal file content.

    Args:
        rules: The recurring rules to format.

    Returns:
        The formatted file content string.
    """
    if not rules:
        return ""

    blocks: list[str] = []

    for rule in rules:
        # Build header: ~ period_expr [from date] [to date]  ; rule-id:xxx [description]
        header = f"~ {rule.period_expr}"
        if rule.start_date:
            header += f" from {rule.start_date}"
        if rule.end_date:
            header += f" to {rule.end_date}"

        comment_parts = [f"rule-id:{rule.rule_id}"]
        if rule.description:
            comment_parts.append(rule.description)
        header += f"  ; {' '.join(comment_parts)}"

        lines = [header]

        # Calculate alignment widths
        postings_with_amounts = [p for p in rule.postings if p.amounts]
        if postings_with_amounts:
            max_account = max(len(p.account) for p in rule.postings)
            account_width = max(max_account + 4, 40)
        else:
            account_width = 40

        for posting in rule.postings:
            if posting.amounts:
                amount_str = posting.amounts[0].format()
                padding = " " * (account_width - len(posting.account))
                lines.append(f"    {posting.account}{padding}{amount_str}")
            else:
                lines.append(f"    {posting.account}")

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) + "\n"


def write_recurring_rules(
    recurring_path: Path,
    rules: list[RecurringRule],
    journal_file: Path,
) -> None:
    """Write recurring rules to the recurring.journal file.

    Uses backup/validate/restore pattern for safety.

    Args:
        recurring_path: Path to the recurring.journal file.
        rules: The recurring rules to write.
        journal_file: Path to the main journal file (for validation).

    Raises:
        RecurringError: If validation fails (file is restored from backup).
    """
    safe_write_with_validation(
        target_file=recurring_path,
        content=_format_recurring_file(rules),
        journal_file=journal_file,
        validate=check_journal,
        error_cls=RecurringError,
        context="Recurring",
    )


def add_recurring_rule(
    recurring_path: Path,
    rule: RecurringRule,
    journal_file: Path,
) -> None:
    """Add a new recurring rule.

    Args:
        recurring_path: Path to the recurring.journal file.
        rule: The recurring rule to add.
        journal_file: Path to the main journal file.

    Raises:
        RecurringError: If a rule with the same ID already exists or validation fails.
    """
    rules = parse_recurring_rules(recurring_path)
    if any(r.rule_id == rule.rule_id for r in rules):
        raise RecurringError(f"Recurring rule already exists with id: {rule.rule_id}")
    rules.append(rule)
    write_recurring_rules(recurring_path, rules, journal_file)


def update_recurring_rule(
    recurring_path: Path,
    rule_id: str,
    new_rule: RecurringRule,
    journal_file: Path,
) -> None:
    """Update an existing recurring rule.

    Args:
        recurring_path: Path to the recurring.journal file.
        rule_id: The ID of the rule to update.
        new_rule: The replacement recurring rule.
        journal_file: Path to the main journal file.

    Raises:
        RecurringError: If the rule is not found or validation fails.
    """
    rules = parse_recurring_rules(recurring_path)
    found = False
    for i, r in enumerate(rules):
        if r.rule_id == rule_id:
            rules[i] = new_rule
            found = True
            break
    if not found:
        raise RecurringError(f"No recurring rule found with id: {rule_id}")
    write_recurring_rules(recurring_path, rules, journal_file)


def delete_recurring_rule(
    recurring_path: Path,
    rule_id: str,
    journal_file: Path,
) -> None:
    """Delete a recurring rule by ID.

    Args:
        recurring_path: Path to the recurring.journal file.
        rule_id: The ID of the rule to delete.
        journal_file: Path to the main journal file.

    Raises:
        RecurringError: If the rule is not found or validation fails.
    """
    rules = parse_recurring_rules(recurring_path)
    new_rules = [r for r in rules if r.rule_id != rule_id]
    if len(new_rules) == len(rules):
        raise RecurringError(f"No recurring rule found with id: {rule_id}")
    write_recurring_rules(recurring_path, new_rules, journal_file)


def _generate_occurrences(start: date, period: str, end: date) -> list[date]:
    """Generate all occurrence dates from start to end (inclusive) for a given period.

    For month-based periods (monthly, bimonthly, quarterly, yearly) the
    canonical day-of-month from ``start`` is preserved across all advances.
    When a target month has fewer days than the canonical day, the result is
    clamped to the last day of that month.

    Args:
        start: The first occurrence date.
        period: One of the SUPPORTED_PERIODS values.
        end: The last allowed date (inclusive).

    Returns:
        List of dates on which the rule fires between start and end.
    """
    dates: list[date] = []
    # Track the canonical day-of-month for month-based periods so that
    # clamping in short months does not permanently reduce future dates.
    canonical_day = start.day
    current = start

    while current <= end:
        dates.append(current)

        if period == "daily":
            current = current + timedelta(days=1)
        elif period == "weekly":
            current = current + timedelta(weeks=1)
        elif period == "biweekly":
            current = current + timedelta(weeks=2)
        elif period == "monthly":
            month = current.month + 1
            year = current.year
            if month > 12:
                month = 1
                year += 1
            day = min(canonical_day, calendar.monthrange(year, month)[1])
            current = current.replace(year=year, month=month, day=day)
        elif period == "bimonthly":
            month = current.month + 2
            year = current.year
            while month > 12:
                month -= 12
                year += 1
            day = min(canonical_day, calendar.monthrange(year, month)[1])
            current = current.replace(year=year, month=month, day=day)
        elif period == "quarterly":
            month = current.month + 3
            year = current.year
            while month > 12:
                month -= 12
                year += 1
            day = min(canonical_day, calendar.monthrange(year, month)[1])
            current = current.replace(year=year, month=month, day=day)
        elif period == "yearly":
            new_year = current.year + 1
            day = min(canonical_day, calendar.monthrange(new_year, current.month)[1])
            current = current.replace(year=new_year, day=day)
        else:
            break

    return dates


def validate_period_expr(expr: str) -> bool:
    """Check whether an hledger period expression is syntactically valid.

    Creates a temporary journal with a minimal periodic transaction using the
    given expression and runs ``hledger print --forecast`` to validate.

    Args:
        expr: The period expression to validate (e.g. ``"every 2 weeks"``).

    Returns:
        ``True`` if hledger accepts the expression, ``False`` otherwise.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_journal = Path(tmpdir) / "test.journal"
        temp_journal.write_text(
            f"~ {expr}\n"
            "    expenses:test    €1.00\n"
            "    assets:test\n",
            encoding="utf-8",
        )
        try:
            run_hledger(
                "print",
                "--forecast=2000-01-01..2000-12-31",
                "-O", "json",
                file=temp_journal,
            )
            return True
        except HledgerError:
            return False


def _get_occurrence_dates_hledger(
    rule: RecurringRule,
    start: date,
    end: date,
) -> list[date]:
    """Generate occurrence dates for a custom period expression using hledger --forecast.

    Creates a minimal temporary journal containing only the periodic transaction
    for the given rule, then runs ``hledger print --forecast`` to obtain the
    dates that hledger would generate within ``[start, end]``.

    Args:
        rule: The recurring rule with a custom period expression.
        start: The start date (inclusive).
        end: The end date (inclusive).

    Returns:
        List of dates on which the rule fires between *start* and *end*.
    """
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_journal = Path(tmpdir) / "forecast.journal"
        temp_journal.write_text(
            f"~ {rule.period_expr} from {start.isoformat()}\n"
            "    expenses:test    €1.00\n"
            "    assets:test\n",
            encoding="utf-8",
        )
        forecast_range = f"{start.isoformat()}..{end.isoformat()}"
        try:
            output = run_hledger(
                "print",
                f"--forecast={forecast_range}",
                "-O", "json",
                file=temp_journal,
            )
            if not output.strip():
                return []
            data = json.loads(output)
            result: list[date] = []
            for txn in data:
                raw_date = txn.get("tdate", "")
                if raw_date:
                    try:
                        result.append(date.fromisoformat(raw_date))
                    except ValueError:
                        pass
            return result
        except (HledgerError, json.JSONDecodeError):
            return []


def compute_pending(
    rule: RecurringRule,
    journal_file: Path,
    today: date,
) -> list[date]:
    """Compute pending (not-yet-generated) dates for a recurring rule.

    Generates all occurrence dates from rule.start_date up to today, then
    subtracts dates that already have a transaction tagged with the rule's ID.

    Args:
        rule: The recurring rule to check.
        journal_file: Path to the main journal file.
        today: The reference date for "today" (inclusive end).

    Returns:
        List of dates that have not yet been generated.
    """
    if not rule.start_date:
        return []

    try:
        start = date.fromisoformat(rule.start_date)
    except ValueError:
        return []

    _, last_day = calendar.monthrange(today.year, today.month)
    end = today.replace(day=last_day)
    if rule.end_date:
        try:
            end = min(end, date.fromisoformat(rule.end_date))
        except ValueError:
            pass

    if rule.period_expr in SUPPORTED_PERIODS:
        all_dates = _generate_occurrences(start, rule.period_expr, end)
    else:
        all_dates = _get_occurrence_dates_hledger(rule, start, end)

    # Load already-generated transactions tagged with this rule's ID
    try:
        generated = load_transactions(
            journal_file, query=f"tag:rule-id={rule.rule_id}"
        )
    except HledgerError:
        generated = []

    generated_dates = {txn.date for txn in generated}

    return [d for d in all_dates if d.isoformat() not in generated_dates]


def generate_transactions(
    rule: RecurringRule,
    dates: list[date],
    journal_file: Path,
) -> None:
    """Generate and append transactions for the given rule and dates.

    Each generated transaction carries a ``rule-id:XXX`` comment tag so that
    future runs of ``compute_pending`` can detect it.

    Args:
        rule: The recurring rule to generate from.
        dates: The dates for which to generate transactions.
        journal_file: Path to the main journal file.

    Raises:
        RecurringError: If any transaction cannot be appended.
    """
    for d in dates:
        txn = Transaction(
            index=0,
            date=d.isoformat(),
            description=rule.description,
            postings=rule.postings,
            status=rule.status,
            code=rule.code,
            comment=f"rule-id:{rule.rule_id}",
        )
        try:
            append_transaction(journal_file, txn)
        except JournalError as exc:
            raise RecurringError(
                f"Failed to generate transaction for {d}: {exc}"
            ) from exc
