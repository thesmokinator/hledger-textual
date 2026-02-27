"""Format Transaction objects into hledger journal text."""

from __future__ import annotations

from hledger_textual.models import Posting, Transaction, TransactionStatus

# Mapping from ISO 4217 currency codes to their common symbols.
_CURRENCY_SYMBOLS: dict[str, str] = {
    "EUR": "€",
    "USD": "$",
    "GBP": "£",
}


def normalize_commodity(commodity: str) -> str:
    """Convert well-known currency codes to their symbol.

    Converts ISO 4217 codes like ``EUR``, ``USD``, ``GBP`` to the
    corresponding symbol (``€``, ``$``, ``£``).  Unknown codes are
    returned unchanged.

    Args:
        commodity: A commodity string, e.g. ``'EUR'`` or ``'XDWD'``.

    Returns:
        The symbol if known, otherwise the original string.
    """
    return _CURRENCY_SYMBOLS.get(commodity, commodity)


def format_posting(
    posting: Posting,
    account_width: int = 40,
    amount_width: int = 12,
) -> str:
    """Format a single posting line.

    Args:
        posting: The posting to format.
        account_width: Minimum width for the account column.
        amount_width: Minimum width for the right-aligned amount column.

    Returns:
        Formatted posting line (e.g. '    expenses:food       €40.80').
    """
    if not posting.amounts:
        line = f"    {posting.account}"
    else:
        amounts_str = ", ".join(a.format() for a in posting.amounts)
        padded_account = posting.account.ljust(account_width)
        padded_amount = amounts_str.rjust(amount_width)
        line = f"    {padded_account}  {padded_amount}"

    if posting.comment:
        line += f"  ; {posting.comment}"

    return line


def format_transaction(transaction: Transaction) -> str:
    """Format a complete transaction as journal text.

    Args:
        transaction: The transaction to format.

    Returns:
        Multi-line string ready to be written to a journal file.
    """
    # Header line: date [status] [(code)] description
    header_parts = [transaction.date]

    if transaction.status != TransactionStatus.UNMARKED:
        header_parts.append(transaction.status.symbol)

    if transaction.code:
        header_parts.append(f"({transaction.code})")

    header_parts.append(transaction.description)

    header = " ".join(header_parts)

    if transaction.comment:
        header += f"  ; {transaction.comment}"

    # Calculate alignment widths
    account_width = max(
        (len(p.account) for p in transaction.postings),
        default=40,
    )
    account_width = max(account_width, 40)

    amount_width = max(
        (
            len(", ".join(a.format() for a in p.amounts))
            for p in transaction.postings
            if p.amounts
        ),
        default=12,
    )
    amount_width = max(amount_width, 12)

    # Format postings
    posting_lines = [
        format_posting(p, account_width, amount_width)
        for p in transaction.postings
    ]

    return header + "\n" + "\n".join(posting_lines)
