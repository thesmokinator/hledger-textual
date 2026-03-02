"""Recurring transaction file management: read/write periodic transactions.

Recurring rules are stored as hledger periodic transactions (``~ period``)
in a dedicated ``recurring.journal`` file that lives next to the main journal.
All write operations follow the same backup/validate/restore pattern used
in ``budget.py`` and ``journal.py``.
"""

from __future__ import annotations

import random
import re
import string
from decimal import Decimal, InvalidOperation
from pathlib import Path

from hledger_textual.fileutil import backup as _backup
from hledger_textual.fileutil import cleanup_backup as _cleanup_backup
from hledger_textual.fileutil import restore as _restore
from hledger_textual.hledger import HledgerError, check_journal
from hledger_textual.models import (
    Amount,
    AmountStyle,
    Posting,
    RecurringRule,
    TransactionStatus,
)

RECURRING_FILENAME = "recurring.journal"

_INCLUDE_RE = re.compile(r"^\s*include\s+recurring\.journal\s*$", re.MULTILINE)

# ~ period_expr  description  ; comment
_PERIODIC_RE = re.compile(r"^~\s+(.+?)\s{2,}(.+?)(?:\s{2,};\s*(.*))?$")

# Posting with amount: account  amount  ; comment
_POSTING_RE = re.compile(r"^\s{4,}(\S.+?)\s{2,}(\S+)\s*(?:;\s*(.*))?$")

# Balancing posting without amount
_BALANCING_RE = re.compile(r"^\s{4,}(\S[^\s;]*)\s*$")


class RecurringError(Exception):
    """Raised when a recurring file operation fails."""


def _recurring_path(journal_file: Path) -> Path:
    """Return the path to recurring.journal next to the main journal."""
    return journal_file.parent / RECURRING_FILENAME


def ensure_recurring_file(journal_file: Path) -> Path:
    """Create recurring.journal if missing and add include directive to the main journal.

    Args:
        journal_file: Path to the main hledger journal file.

    Returns:
        Path to the recurring.journal file.
    """
    recurring_file = _recurring_path(journal_file)

    if not recurring_file.exists():
        recurring_file.write_text("")

    journal_text = journal_file.read_text()
    if not _INCLUDE_RE.search(journal_text):
        include_line = f"include {RECURRING_FILENAME}\n"
        if journal_text and not journal_text.startswith("\n"):
            include_line += "\n"
        journal_file.write_text(include_line + journal_text)

    return recurring_file


def _parse_amount_string(s: str) -> tuple[Decimal, str]:
    """Parse an amount string like '€800.00' or '150.00 EUR' into (quantity, commodity).

    Args:
        s: The amount string to parse.

    Returns:
        A tuple of (quantity, commodity).

    Raises:
        RecurringError: If the amount cannot be parsed.
    """
    s = s.strip()
    if not s:
        raise RecurringError("Empty amount string")

    # Try left-side commodity: €800.00 or $500
    match = re.match(r"^([^\d\s.-]+)\s*(-?[\d.]+)$", s)
    if match:
        commodity = match.group(1)
        try:
            quantity = Decimal(match.group(2))
        except InvalidOperation:
            raise RecurringError(f"Invalid amount: {s}")
        return quantity, commodity

    # Try right-side commodity: 800.00 EUR
    match = re.match(r"^(-?[\d.]+)\s*([^\d\s.-]+)$", s)
    if match:
        try:
            quantity = Decimal(match.group(1))
        except InvalidOperation:
            raise RecurringError(f"Invalid amount: {s}")
        commodity = match.group(2)
        return quantity, commodity

    raise RecurringError(f"Cannot parse amount: {s}")


def _parse_metadata(comment: str) -> dict[str, str]:
    """Parse key:value pairs from a comment string.

    Args:
        comment: The comment string (e.g. "recurring-id:rent-001, last-generated:2026-02-01").

    Returns:
        Dictionary of parsed key-value pairs.
    """
    metadata: dict[str, str] = {}
    if not comment:
        return metadata
    for part in comment.split(","):
        part = part.strip()
        if ":" in part:
            key, _, value = part.partition(":")
            metadata[key.strip()] = value.strip()
    return metadata


def _status_from_string(s: str) -> TransactionStatus:
    """Parse a transaction status from a string symbol.

    Args:
        s: The status symbol ('*', '!', or empty).

    Returns:
        The corresponding TransactionStatus.
    """
    s = s.strip()
    if s == "*":
        return TransactionStatus.CLEARED
    if s == "!":
        return TransactionStatus.PENDING
    return TransactionStatus.UNMARKED


def parse_recurring_rules(recurring_path: Path) -> list[RecurringRule]:
    """Parse recurring rules from a recurring.journal file.

    Args:
        recurring_path: Path to the recurring.journal file.

    Returns:
        A list of RecurringRule objects.
    """
    if not recurring_path.exists():
        return []

    content = recurring_path.read_text()
    if not content.strip():
        return []

    rules: list[RecurringRule] = []
    current_rule: RecurringRule | None = None

    for line in content.splitlines():
        periodic_match = _PERIODIC_RE.match(line)
        if periodic_match:
            # Save previous rule if any
            if current_rule is not None:
                rules.append(current_rule)

            period_expr = periodic_match.group(1).strip()
            description_raw = periodic_match.group(2).strip()
            comment_raw = periodic_match.group(3) or ""

            # Parse metadata from comment
            metadata = _parse_metadata(comment_raw)
            rule_id = metadata.get("recurring-id", "")
            last_generated = metadata.get("last-generated") or None

            # Extract status symbol from description if present
            status = TransactionStatus.UNMARKED
            desc = description_raw
            if desc.startswith("* "):
                status = TransactionStatus.CLEARED
                desc = desc[2:]
            elif desc.startswith("! "):
                status = TransactionStatus.PENDING
                desc = desc[2:]

            # Extract code from description: "(CODE) rest"
            code = ""
            code_match = re.match(r"^\(([^)]*)\)\s*(.*)", desc)
            if code_match:
                code = code_match.group(1)
                desc = code_match.group(2)

            # Build user comment (everything except our internal tags)
            user_comment_parts = []
            for part in comment_raw.split(","):
                part = part.strip()
                if part and not part.startswith("recurring-id:") and not part.startswith("last-generated:"):
                    user_comment_parts.append(part)
            user_comment = ", ".join(user_comment_parts)

            current_rule = RecurringRule(
                rule_id=rule_id,
                period_expr=period_expr,
                description=desc,
                status=status,
                code=code,
                comment=user_comment,
                last_generated=last_generated,
            )
            continue

        if current_rule is not None:
            # End of block: non-indented, non-empty line that isn't a tilde
            if line and not line[0].isspace() and not line.startswith("~"):
                rules.append(current_rule)
                current_rule = None
                continue

            # Empty line within/between blocks
            if not line.strip():
                continue

            # Try posting with amount
            posting_match = _POSTING_RE.match(line)
            if posting_match:
                account = posting_match.group(1).strip()
                amount_str = posting_match.group(2).strip()
                posting_comment = posting_match.group(3) or ""
                quantity, commodity = _parse_amount_string(amount_str)
                exp = quantity.as_tuple().exponent
                precision = max(abs(exp) if isinstance(exp, int) else 2, 2)
                style = AmountStyle(
                    commodity_side="L",
                    commodity_spaced=False,
                    precision=precision,
                )
                current_rule.postings.append(
                    Posting(
                        account=account,
                        amounts=[Amount(commodity=commodity, quantity=quantity, style=style)],
                        comment=posting_comment.strip(),
                    )
                )
                continue

            # Try balancing posting (no amount)
            balancing_match = _BALANCING_RE.match(line)
            if balancing_match:
                account = balancing_match.group(1).strip()
                current_rule.postings.append(Posting(account=account))
                continue

    # Don't forget the last rule
    if current_rule is not None:
        rules.append(current_rule)

    return rules


def _format_recurring_file(rules: list[RecurringRule]) -> str:
    """Format recurring rules into the recurring.journal file content.

    Args:
        rules: The recurring rules to format.

    Returns:
        The formatted file content.
    """
    if not rules:
        return ""

    blocks: list[str] = []

    for rule in rules:
        # Build the tilde header line
        # ~ period_expr  [status] [(code)] description  ; metadata
        desc_parts: list[str] = []
        if rule.status != TransactionStatus.UNMARKED:
            desc_parts.append(rule.status.symbol)
        if rule.code:
            desc_parts.append(f"({rule.code})")
        desc_parts.append(rule.description)
        desc = " ".join(desc_parts)

        # Build comment with metadata
        comment_parts: list[str] = []
        if rule.rule_id:
            comment_parts.append(f"recurring-id:{rule.rule_id}")
        if rule.last_generated:
            comment_parts.append(f"last-generated:{rule.last_generated}")
        if rule.comment:
            comment_parts.append(rule.comment)

        header = f"~ {rule.period_expr}  {desc}"
        if comment_parts:
            header += f"  ; {', '.join(comment_parts)}"

        lines = [header]

        # Calculate alignment widths
        if rule.postings:
            max_account = max(len(p.account) for p in rule.postings)
            account_width = max(max_account + 4, 40)
        else:
            account_width = 40

        for posting in rule.postings:
            if posting.amounts:
                amount_str = posting.amounts[0].format()
                padding = " " * (account_width - len(posting.account))
                posting_line = f"    {posting.account}{padding}{amount_str}"
            else:
                posting_line = f"    {posting.account}"

            if posting.comment:
                posting_line += f"  ; {posting.comment}"

            lines.append(posting_line)

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) + "\n"


def write_recurring_rules(
    recurring_path: Path, rules: list[RecurringRule], journal_file: Path
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
    backup_path = _backup(recurring_path)

    try:
        content = _format_recurring_file(rules)
        recurring_path.write_text(content)

        try:
            check_journal(journal_file)
        except HledgerError as exc:
            _restore(recurring_path, backup_path)
            _cleanup_backup(backup_path)
            raise RecurringError(f"Recurring validation failed, changes reverted: {exc}")

        _cleanup_backup(backup_path)
    except RecurringError:
        raise
    except Exception as exc:
        _restore(recurring_path, backup_path)
        _cleanup_backup(backup_path)
        raise RecurringError(f"Failed to write recurring rules: {exc}")


def add_recurring_rule(
    recurring_path: Path, rule: RecurringRule, journal_file: Path
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
        raise RecurringError(f"Recurring rule already exists with id {rule.rule_id}")
    rules.append(rule)
    write_recurring_rules(recurring_path, rules, journal_file)


def update_recurring_rule(
    recurring_path: Path,
    old_rule_id: str,
    new_rule: RecurringRule,
    journal_file: Path,
) -> None:
    """Update an existing recurring rule.

    Args:
        recurring_path: Path to the recurring.journal file.
        old_rule_id: The rule_id of the rule to update.
        new_rule: The new recurring rule.
        journal_file: Path to the main journal file.

    Raises:
        RecurringError: If the rule is not found or validation fails.
    """
    rules = parse_recurring_rules(recurring_path)
    found = False
    for i, r in enumerate(rules):
        if r.rule_id == old_rule_id:
            rules[i] = new_rule
            found = True
            break
    if not found:
        raise RecurringError(f"No recurring rule found with id {old_rule_id}")
    write_recurring_rules(recurring_path, rules, journal_file)


def delete_recurring_rule(
    recurring_path: Path, rule_id: str, journal_file: Path
) -> None:
    """Delete a recurring rule by rule_id.

    Args:
        recurring_path: Path to the recurring.journal file.
        rule_id: The rule_id of the rule to delete.
        journal_file: Path to the main journal file.

    Raises:
        RecurringError: If the rule is not found or validation fails.
    """
    rules = parse_recurring_rules(recurring_path)
    new_rules = [r for r in rules if r.rule_id != rule_id]
    if len(new_rules) == len(rules):
        raise RecurringError(f"No recurring rule found with id {rule_id}")
    write_recurring_rules(recurring_path, new_rules, journal_file)


def update_last_generated(
    recurring_path: Path, rule_id: str, date_str: str, journal_file: Path
) -> None:
    """Update only the last_generated date for a specific rule.

    Args:
        recurring_path: Path to the recurring.journal file.
        rule_id: The rule_id of the rule to update.
        date_str: The new last_generated date string (ISO format).
        journal_file: Path to the main journal file.

    Raises:
        RecurringError: If the rule is not found or validation fails.
    """
    rules = parse_recurring_rules(recurring_path)
    found = False
    for rule in rules:
        if rule.rule_id == rule_id:
            rule.last_generated = date_str
            found = True
            break
    if not found:
        raise RecurringError(f"No recurring rule found with id {rule_id}")
    write_recurring_rules(recurring_path, rules, journal_file)


def generate_rule_id(description: str) -> str:
    """Generate a unique rule ID from a description.

    Creates a slug from the description and appends a random suffix.

    Args:
        description: The rule description.

    Returns:
        A rule ID string like "rent-payment-a1b2".
    """
    # Create slug from description
    slug = re.sub(r"[^a-z0-9]+", "-", description.lower()).strip("-")
    if not slug:
        slug = "rule"
    # Truncate long slugs
    slug = slug[:30]
    # Add random suffix
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{slug}-{suffix}"
