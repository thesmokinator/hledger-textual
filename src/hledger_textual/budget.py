"""Budget file management: read/write periodic transactions in budget.journal.

Budget rules are stored as hledger periodic transactions (``~ monthly``)
in a dedicated ``budget.journal`` file that lives next to the main journal.
All write operations follow the same backup/validate/restore pattern used
in ``journal.py``.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from hledger_textual.amountutil import parse_amount_string as _parse_amount_string_raw
from hledger_textual.fileutil import (
    atomic_write_text,
    journal_include_lock,
    safe_write_with_validation,
)
from hledger_textual.hledger import check_journal
from hledger_textual.models import Amount, AmountStyle, BudgetRule

BUDGET_FILENAME = "budget.journal"

_INCLUDE_RE = re.compile(r"^\s*include\s+budget\.journal\s*$", re.MULTILINE)
_PERIODIC_RE = re.compile(r"^~\s+monthly\b")
_POSTING_RE = re.compile(r"^\s{4,}(\S.+?)\s{2,}(\S+)\s*(?:;\s*category:\s*(.+?))?\s*$")
_BALANCING_RE = re.compile(r"^\s{4,}(Assets:Budget)\s*$")


class BudgetError(Exception):
    """Raised when a budget file operation fails."""


def _budget_path(journal_file: Path) -> Path:
    """Return the path to budget.journal next to the main journal."""
    return journal_file.parent / BUDGET_FILENAME


def ensure_budget_file(journal_file: Path) -> Path:
    """Create budget.journal if missing and add include directive to the main journal.

    Args:
        journal_file: Path to the main hledger journal file.

    Returns:
        Path to the budget.journal file.
    """
    budget_file = _budget_path(journal_file)

    if not budget_file.exists():
        budget_file.write_text("", encoding="utf-8")

    # Concurrent pane loads (budget + recurring) each read-modify-write the main
    # journal to insert their ``include`` line; serialise them and write
    # atomically so a concurrent reader never sees a partially written file.
    with journal_include_lock:
        try:
            journal_text = journal_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return budget_file
        if not _INCLUDE_RE.search(journal_text):
            include_line = f"include {BUDGET_FILENAME}\n"
            if journal_text and not journal_text.startswith("\n"):
                include_line += "\n"
            atomic_write_text(journal_file, include_line + journal_text)

    return budget_file


def _parse_amount_string(s: str) -> tuple[Decimal, str]:
    """Parse an amount string, wrapping ValueError as BudgetError."""
    try:
        return _parse_amount_string_raw(s)
    except ValueError as exc:
        raise BudgetError(str(exc)) from exc


def parse_budget_rules(budget_path: Path) -> list[BudgetRule]:
    """Parse budget rules from a budget.journal file.

    Reads the ``~ monthly`` periodic transaction block and extracts
    account + amount rules, skipping the balancing ``Assets:Budget`` posting.

    Args:
        budget_path: Path to the budget.journal file.

    Returns:
        A list of BudgetRule objects.
    """
    if not budget_path.exists():
        return []

    content = budget_path.read_text(encoding="utf-8")
    if not content.strip():
        return []

    rules: list[BudgetRule] = []
    in_periodic = False

    for line in content.splitlines():
        if _PERIODIC_RE.match(line):
            in_periodic = True
            continue

        if in_periodic:
            # End of block: non-indented, non-empty line
            if line and not line[0].isspace():
                break

            # Skip balancing account
            if _BALANCING_RE.match(line):
                continue

            # Skip empty lines
            if not line.strip():
                continue

            posting_match = _POSTING_RE.match(line)
            if posting_match:
                account = posting_match.group(1).strip()
                amount_str = posting_match.group(2).strip()
                category = (posting_match.group(3) or "").strip()
                quantity, commodity = _parse_amount_string(amount_str)
                style = AmountStyle(
                    commodity_side="L",
                    commodity_spaced=False,
                    precision=max(abs(quantity.as_tuple().exponent) if isinstance(quantity.as_tuple().exponent, int) else 2, 2),
                )
                rules.append(BudgetRule(
                    account=account,
                    amount=Amount(commodity=commodity, quantity=quantity, style=style),
                    category=category,
                ))

    return rules


def _format_budget_file(rules: list[BudgetRule]) -> str:
    """Format budget rules into the budget.journal file content.

    Args:
        rules: The budget rules to format.

    Returns:
        The formatted file content.
    """
    if not rules:
        return ""

    lines = ["~ monthly"]
    # Calculate max account width for alignment
    max_account = max(len(r.account) for r in rules)
    account_width = max(max_account + 4, 40)

    for rule in rules:
        amount_str = rule.amount.format()
        padding = " " * (account_width - len(rule.account))
        if rule.category:
            lines.append(f"    {rule.account}{padding}{amount_str}  ; category: {rule.category}")
        else:
            lines.append(f"    {rule.account}{padding}{amount_str}")

    lines.append("    Assets:Budget")
    lines.append("")
    return "\n".join(lines)


def write_budget_rules(
    budget_path: Path, rules: list[BudgetRule], journal_file: Path
) -> None:
    """Write budget rules to the budget.journal file.

    Uses backup/validate/restore pattern for safety.

    Args:
        budget_path: Path to the budget.journal file.
        rules: The budget rules to write.
        journal_file: Path to the main journal file (for validation).

    Raises:
        BudgetError: If validation fails (file is restored from backup).
    """
    safe_write_with_validation(
        target_file=budget_path,
        content=_format_budget_file(rules),
        journal_file=journal_file,
        validate=check_journal,
        error_cls=BudgetError,
        context="Budget",
    )


def add_budget_rule(
    budget_path: Path, rule: BudgetRule, journal_file: Path
) -> None:
    """Add a new budget rule.

    Args:
        budget_path: Path to the budget.journal file.
        rule: The budget rule to add.
        journal_file: Path to the main journal file.

    Raises:
        BudgetError: If the account already has a rule or validation fails.
    """
    rules = parse_budget_rules(budget_path)
    if any(r.account == rule.account for r in rules):
        raise BudgetError(f"Budget rule already exists for {rule.account}")
    rules.append(rule)
    write_budget_rules(budget_path, rules, journal_file)


def update_budget_rule(
    budget_path: Path,
    old_account: str,
    new_rule: BudgetRule,
    journal_file: Path,
) -> None:
    """Update an existing budget rule.

    Args:
        budget_path: Path to the budget.journal file.
        old_account: The account name of the rule to update.
        new_rule: The new budget rule.
        journal_file: Path to the main journal file.

    Raises:
        BudgetError: If the rule is not found or validation fails.
    """
    rules = parse_budget_rules(budget_path)
    found = False
    for i, r in enumerate(rules):
        if r.account == old_account:
            rules[i] = new_rule
            found = True
            break
    if not found:
        raise BudgetError(f"No budget rule found for {old_account}")
    write_budget_rules(budget_path, rules, journal_file)


def delete_budget_rule(
    budget_path: Path, account: str, journal_file: Path
) -> None:
    """Delete a budget rule by account name.

    Args:
        budget_path: Path to the budget.journal file.
        account: The account name of the rule to delete.
        journal_file: Path to the main journal file.

    Raises:
        BudgetError: If the rule is not found or validation fails.
    """
    rules = parse_budget_rules(budget_path)
    new_rules = [r for r in rules if r.account != account]
    if len(new_rules) == len(rules):
        raise BudgetError(f"No budget rule found for {account}")
    write_budget_rules(budget_path, new_rules, journal_file)
