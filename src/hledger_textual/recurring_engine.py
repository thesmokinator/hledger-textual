"""Recurring transaction engine: date computation and transaction generation.

Delegates period expression validation and date computation to hledger,
enabling support for any hledger period expression (e.g. ``every 3rd thursday``,
``every friday``, ``every feb 14``).
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from datetime import date, timedelta

from hledger_textual.models import (
    Posting,
    RecurringRule,
    Transaction,
    TransactionStatus,
)

logger = logging.getLogger(__name__)


def validate_period_expression(period_expr: str) -> tuple[bool, str]:
    """Validate a period expression using hledger check.

    Writes a minimal periodic transaction rule to a temporary file and asks
    hledger to check it.  This supports the full range of hledger period
    expressions.

    Args:
        period_expr: The period expression to validate.

    Returns:
        A tuple of ``(is_valid, error_message)``.  ``error_message`` is empty
        when the expression is valid.
    """
    expr = period_expr.strip()
    if not expr:
        return (False, "Period expression is empty")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".journal", delete=True
    ) as f:
        f.write(f"~ {expr}\n    a  $1\n    b\n")
        f.flush()

        try:
            result = subprocess.run(
                ["hledger", "check", "-f", f.name],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            return (False, "hledger is not installed")
        except subprocess.TimeoutExpired:
            return (False, "Validation timed out")

    if result.returncode == 0:
        return (True, "")

    # Extract the most descriptive error line from stderr.
    stderr = result.stderr.strip()
    lines = stderr.splitlines()
    for line in lines:
        lower = line.lower()
        if "unexpected" in lower or "expecting" in lower:
            return (False, line.strip())
    error = lines[-1].strip() if lines else "Unknown validation error"
    return (False, error)


def compute_all_due_dates(
    period_expr: str,
    last_generated: str | None,
    up_to: date,
) -> list[date]:
    """Compute all due dates between *last_generated* and *up_to* (inclusive).

    Uses ``hledger print --forecast`` to compute dates.  When
    *last_generated* is provided, the period expression is anchored with a
    ``from <last_generated>`` clause so that hledger generates dates aligned
    to the original schedule.

    Args:
        period_expr: The period expression (e.g. ``"monthly"``,
            ``"every friday"``).
        last_generated: ISO date string of the last generation, or ``None``.
        up_to: The upper bound date (inclusive).

    Returns:
        A sorted list of due dates.
    """
    if last_generated:
        start_date = date.fromisoformat(last_generated) + timedelta(days=1)
        period_line = f"~ {period_expr} from {last_generated}"
    else:
        start_date = up_to.replace(day=1)
        period_line = f"~ {period_expr}"

    end_date = up_to + timedelta(days=1)  # hledger forecast end is exclusive

    if start_date >= end_date:
        return []

    forecast_range = f"{start_date.isoformat()}..{end_date.isoformat()}"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".journal", delete=True
    ) as f:
        f.write(f"{period_line}\n    a  $1\n    b\n")
        f.flush()

        try:
            result = subprocess.run(
                [
                    "hledger",
                    "print",
                    f"--forecast={forecast_range}",
                    "-f",
                    f.name,
                    "-O",
                    "json",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning(
                "hledger not available or timed out for date computation"
            )
            return []

    if result.returncode != 0:
        logger.warning("hledger forecast failed: %s", result.stderr.strip())
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("Failed to parse hledger JSON output")
        return []

    return sorted(date.fromisoformat(txn["tdate"]) for txn in data)


def compute_next_due_date(
    period_expr: str,
    last_generated: str | None,
    reference_date: date | None = None,
) -> date | None:
    """Compute the next due date for a recurring rule.

    Delegates to :func:`compute_all_due_dates` and returns the earliest date.

    Args:
        period_expr: The period expression (e.g. ``"monthly"``).
        last_generated: ISO date string of the last generation, or ``None``.
        reference_date: The reference "today" date (defaults to today).

    Returns:
        The next due date, or ``None`` if no date is due yet.
    """
    if reference_date is None:
        reference_date = date.today()

    dates = compute_all_due_dates(period_expr, last_generated, reference_date)
    return dates[0] if dates else None


def find_pending_generations(
    rules: list[RecurringRule],
    up_to: date | None = None,
) -> list[tuple[RecurringRule, list[date]]]:
    """Find all rules with pending (ungenerated) transactions.

    Args:
        rules: The list of recurring rules.
        up_to: The upper bound date (defaults to today).

    Returns:
        A list of (rule, pending_dates) tuples, only for rules with pending dates.
    """
    if up_to is None:
        up_to = date.today()

    result: list[tuple[RecurringRule, list[date]]] = []
    for rule in rules:
        dates = compute_all_due_dates(rule.period_expr, rule.last_generated, up_to)
        if dates:
            result.append((rule, dates))
    return result


def build_transaction_from_rule(rule: RecurringRule, target_date: date) -> Transaction:
    """Build a Transaction object from a recurring rule for a specific date.

    The generated transaction includes a comment with recurring metadata
    for traceability.

    Args:
        rule: The recurring rule.
        target_date: The date for the generated transaction.

    Returns:
        A Transaction object ready to be appended to the journal.
    """
    # Build comment with recurring metadata
    comment_parts: list[str] = []
    comment_parts.append(f"recurring-id:{rule.rule_id}")
    comment_parts.append(f"recurring-date:{target_date.isoformat()}")
    if rule.comment:
        comment_parts.append(rule.comment)
    comment = ", ".join(comment_parts)

    # Deep copy postings
    postings: list[Posting] = []
    for p in rule.postings:
        postings.append(
            Posting(
                account=p.account,
                amounts=list(p.amounts),
                comment=p.comment,
                status=p.status,
            )
        )

    return Transaction(
        index=0,
        date=target_date.isoformat(),
        description=rule.description,
        status=rule.status,
        code=rule.code,
        comment=comment,
        postings=postings,
    )
