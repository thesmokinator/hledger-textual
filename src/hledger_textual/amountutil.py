"""Shared amount parsing utilities."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from hledger_textual.models import AmountStyle


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


def normalize_number_string_for_style(s: str, style: AmountStyle | None = None) -> str:
    """Normalize a number string using a known commodity style when available.

    Args:
        s: A raw number string, optionally prefixed with a minus sign.
        style: The style declared for the active commodity.

    Returns:
        The number string in standard ``Decimal``-parseable notation.
    """
    if style is None:
        return _normalize_number_string(s)

    negative = s.startswith("-")
    core = s[1:] if negative else s
    decimal_mark = style.decimal_mark or "."
    group_separator = style.digit_group_separator

    if decimal_mark != "." and decimal_mark in core:
        if group_separator:
            core = core.replace(group_separator, "")
        normalized = core.replace(decimal_mark, ".")
    elif "." in core and "," not in core:
        # Users often type dot decimals even in comma-decimal journals.  Treat
        # a lone dot followed by one or two digits as a decimal mark rather
        # than the commodity's group mark.
        after_last_dot = core[core.rfind(".") + 1:]
        if group_separator == "." and len(after_last_dot) == 3:
            normalized = core.replace(".", "")
        else:
            normalized = core
    elif group_separator:
        normalized = core.replace(group_separator, "")
    else:
        normalized = _normalize_number_string(core)

    return f"-{normalized}" if negative else normalized


def decimal_places_for_number_string(s: str, style: AmountStyle | None = None) -> int:
    """Return decimal places from a raw number string.

    Args:
        s: A raw number string, optionally prefixed with a minus sign.
        style: The style declared for the active commodity.

    Returns:
        Number of explicit fractional digits in the input.
    """
    core = s[1:] if s.startswith("-") else s
    if style is not None and style.decimal_mark in core:
        return len(core.rsplit(style.decimal_mark, 1)[1])
    if "." in core and "," not in core:
        if style is not None and style.digit_group_separator == ".":
            after_last_dot = core[core.rfind(".") + 1:]
            if len(after_last_dot) == 3:
                return 0
        return len(core.rsplit(".", 1)[1])
    if "," in core and "." not in core:
        after_last_comma = core[core.rfind(",") + 1:]
        if len(after_last_comma) <= 2 and after_last_comma.isdigit():
            return len(after_last_comma)
    if "." in core and "," in core:
        separator = "," if core.rfind(",") > core.rfind(".") else "."
        return len(core.rsplit(separator, 1)[1])
    return 0


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


def describe_amount_error(value: str) -> str:
    """Explain why an amount string cannot be parsed.

    Called only after parsing failed, so the goal is a short, plain-language
    reason rather than a full grammar.  Distinct categories help users fix the
    input without re-reading the whole format hint.

    Args:
        value: The raw amount string entered by the user.

    Returns:
        A one-line, user-facing description of the problem.
    """
    s = value.strip()
    if not s:
        return "an amount is required"

    if "@" in s:
        base, _, cost = s.partition("@")
        if cost.startswith("@"):
            cost = cost[1:]
        if not base.strip():
            return "the quantity before @ is missing"
        if not cost.strip():
            return "the cost after @ is missing"

    if not re.search(r"\d", s):
        return "the amount must include a number"

    for index, char in enumerate(s):
        if char == "-" and (index + 1 == len(s) or not s[index + 1].isdigit()):
            return "a negative amount needs the minus sign right before the number (e.g. -50.00)"

    # A number uses one decimal separator at most; repeated separators of the
    # same kind ("1.2.3", "1,2,3") are the usual typo.  Three-digit groups
    # ("1.000.000") are thousands separators and parse fine.
    dots = s.count(".")
    commas = s.count(",")
    if dots > 1 and not commas:
        if not all(len(group) == 3 for group in s.split(".")[1:]):
            return "the amount has too many decimal points"
    if commas > 1 and not dots:
        if not all(len(group) == 3 for group in s.split(",")[1:]):
            return "the amount has too many decimal points"

    currency_symbols = re.findall(r"[€$£¥₿₹]", s)
    if len(currency_symbols) > 1:
        return "only one currency or commodity is allowed"

    symbols = re.findall(r"[^\d\s.,@+\-]+", s)
    if len(symbols) > 1:
        return "only one currency or commodity is allowed"

    return (
        "the amount is not a recognised number with an optional currency "
        "(e.g. 50.00, €50.00, -5 XEON @ €40.00)"
    )
