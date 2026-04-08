"""Shared amount parsing utilities."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


def _normalize_number_string(s: str) -> str:
    """Normalize a raw number string to standard decimal notation.

    Supports both US format (1,000.00 — dot as decimal separator) and European
    format (1.000,00 — comma as decimal separator).  The decimal separator is
    detected by the position of the *last* separator character in the string:
    whichever of ``,`` or ``.`` appears furthest to the right is treated as the
    decimal separator.  When only a comma is present a two-digit heuristic is
    applied: if exactly one or two digits follow the last comma the comma is
    treated as a decimal separator (e.g. ``100,00`` → ``100.00``); otherwise it
    is treated as a thousands separator (e.g. ``1,000`` → ``1000``).

    Args:
        s: A raw number string, optionally prefixed with a minus sign.

    Returns:
        The number string in standard ``Decimal``-parseable notation.
    """
    negative = s.startswith("-")
    core = s[1:] if negative else s

    has_dot = "." in core
    has_comma = "," in core

    if has_dot and has_comma:
        if core.rfind(",") > core.rfind("."):
            # European: 1.000,00 — comma is the decimal separator
            normalized = core.replace(".", "").replace(",", ".")
        else:
            # US: 1,000.00 — dot is the decimal separator
            normalized = core.replace(",", "")
    elif has_comma:
        after_last_comma = core[core.rfind(",") + 1:]
        if len(after_last_comma) <= 2 and after_last_comma.isdigit():
            # Decimal comma: 100,00 → 100.00
            normalized = core.replace(",", ".")
        else:
            # Thousands comma: 1,000 → 1000
            normalized = core.replace(",", "")
    else:
        normalized = core

    return f"-{normalized}" if negative else normalized


def parse_amount_string(s: str) -> tuple[Decimal, str]:
    """Parse an amount string like '€800.00' or '150.00 EUR' into (quantity, commodity).

    Handles both US (1,000.00) and European (1.000,00) number formats.

    Args:
        s: The amount string to parse.

    Returns:
        A tuple of (quantity, commodity).

    Raises:
        ValueError: If the amount cannot be parsed.
    """
    s = s.strip()
    if not s:
        raise ValueError("Empty amount string")

    # Try left-side commodity: €800.00, $500, $1,320.28, €1.000,00
    match = re.match(r"^([^\d\s.,-]+)\s*(-?[\d,.]+)$", s)
    if match:
        commodity = match.group(1)
        try:
            quantity = Decimal(_normalize_number_string(match.group(2)))
        except InvalidOperation:
            raise ValueError(f"Invalid amount: {s}")
        return quantity, commodity

    # Try right-side commodity: 800.00 EUR, 1,320.28 EUR, 1.000,00 EUR
    match = re.match(r"^(-?[\d,.]+)\s*([^\d\s.,-]+)$", s)
    if match:
        try:
            quantity = Decimal(_normalize_number_string(match.group(1)))
        except InvalidOperation:
            raise ValueError(f"Invalid amount: {s}")
        commodity = match.group(2)
        return quantity, commodity

    raise ValueError(f"Cannot parse amount: {s}")
