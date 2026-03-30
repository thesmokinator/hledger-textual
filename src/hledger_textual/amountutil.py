"""Shared amount parsing utilities."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


def parse_amount_string(s: str) -> tuple[Decimal, str]:
    """Parse an amount string like '€800.00' or '150.00 EUR' into (quantity, commodity).

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

    # Try left-side commodity: €800.00, $500, $1,320.28
    match = re.match(r"^([^\d\s.,-]+)\s*(-?[\d,.]+)$", s)
    if match:
        commodity = match.group(1)
        try:
            quantity = Decimal(match.group(2).replace(",", ""))
        except InvalidOperation:
            raise ValueError(f"Invalid amount: {s}")
        return quantity, commodity

    # Try right-side commodity: 800.00 EUR, 1,320.28 EUR
    match = re.match(r"^(-?[\d,.]+)\s*([^\d\s.,-]+)$", s)
    if match:
        try:
            quantity = Decimal(match.group(1).replace(",", ""))
        except InvalidOperation:
            raise ValueError(f"Invalid amount: {s}")
        commodity = match.group(2)
        return quantity, commodity

    raise ValueError(f"Cannot parse amount: {s}")
