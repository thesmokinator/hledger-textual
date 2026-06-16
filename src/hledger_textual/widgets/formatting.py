"""Shared formatting helpers for financial amounts."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from babel.numbers import format_decimal

# Matches left-side currency symbol amounts with 2+ decimal places.
# Handles both €-2442.14 (symbol before minus) and -€1.73 (minus before symbol).
_FMT_STR_RE = re.compile(r"^(-?)([€$£¥₿₹])(-?)([\d,]+\.\d{2,})$")


@lru_cache(maxsize=1)
def _number_locale() -> str:
    """Return the cached number locale from config."""
    from hledger_textual.config import load_number_locale
    return load_number_locale()


# Separator used by hledger CSV output between multiple commodities in one cell.
# hledger CSV never uses thousands separators, so ", " is unambiguous.
_MULTI_COMMODITY_SEP = ", "


def fmt_amount_str(s: str) -> str:
    """Format a hledger amount string for display, supporting multi-commodity cells.

    hledger CSV output combines per-account amounts for different commodities
    into a single cell, separated by ``", "`` (e.g.
    ``"$5750.00, 0.175 BTC, £-8.99, €3741.81"``).  This function detects
    such multi-commodity cells, formats each sub-amount individually, and
    joins them with ``\\n`` for vertically stacked display in a DataTable.

    Single-commodity amounts with a left-side currency symbol (€, $, etc.)
    and 2+ decimal places get locale formatting via :func:`fmt_amount`.
    Named-commodity amounts (``164 XEON``, ``2.00 XDWD``) are returned
    unchanged.

    Handles both ``€-2442.140`` (symbol before minus) and ``-€1.730``
    (minus before symbol) formats.

    Args:
        s: Raw amount string, e.g. from hledger CSV output or ``Amount.format()``.

    Returns:
        Locale-formatted amount string, with multi-commodity sub-amounts
        joined by ``\\n`` for vertical stacking.
    """
    s = s.strip()
    if not s:
        return s

    if _MULTI_COMMODITY_SEP in s:
        sub_amounts = s.split(_MULTI_COMMODITY_SEP)
        formatted_parts: list[str] = []
        for part in sub_amounts:
            part = part.strip()
            if not part:
                continue
            formatted_parts.append(fmt_single_amount_str(part))
        return "\n".join(formatted_parts)

    return fmt_single_amount_str(s)


def split_multi_commodity_amounts(s: str) -> list[str]:
    """Split an amount string into individual per-commodity formatted amounts.

    For single-commodity strings, returns a single-element list with the
    formatted result.  For multi-commodity strings (separated by ``", "``),
    returns one formatted string per commodity, preserving order.

    This is used by the ReportsPane to create per-commodity child rows
    in stacked-currency mode.

    Args:
        s: Raw amount string from hledger CSV (e.g. ``"£-8.99, €3741.81"``).

    Returns:
        A list of formatted per-commodity amount strings, never empty.
    """
    s = s.strip()
    if not s:
        return [s]

    if _MULTI_COMMODITY_SEP in s:
        sub_amounts = s.split(_MULTI_COMMODITY_SEP)
        return [fmt_single_amount_str(part.strip()) for part in sub_amounts if part.strip()]

    return [fmt_single_amount_str(s)]


def get_commodity_name(raw_amount: str) -> str:
    """Extract the commodity display name from a raw hledger amount string.

    For single-char symbols, returns the symbol itself (``€``, ``$``, etc.).
    For named commodities, returns the commodity code (``BTC``, ``XDWD``, etc.).
    Returns empty string for unparseable amounts.

    Args:
        raw_amount: A single-commodity raw amount string (no ``", "`` separator).

    Returns:
        The commodity name, or ``""`` if it cannot be determined.
    """
    from hledger_textual.amountutil import parse_amount_string

    try:
        _, commodity = parse_amount_string(raw_amount.strip())
        return commodity
    except ValueError:
        return ""


def split_raw_commodities(s: str) -> list[str]:
    """Split a raw hledger amount string into individual commodity sub-strings.

    Does NOT apply locale formatting — use :func:`fmt_amount_str` or
    :func:`split_multi_commodity_amounts` for display-formatted output.

    Args:
        s: Raw amount string from hledger CSV (e.g. ``"£-8.99, €3741.81"``).

    Returns:
        List of raw per-commodity amount strings, never empty.
    """
    s = s.strip()
    if not s:
        return [s]

    if _MULTI_COMMODITY_SEP in s:
        return [part.strip() for part in s.split(_MULTI_COMMODITY_SEP) if part.strip()]

    return [s]


def fmt_single_amount_str(s: str) -> str:
    """Format a single-commodity hledger amount string.

    Applies locale formatting to amounts with a left-side currency symbol
    (€, $, etc.) that have 2+ decimal places.  Named-commodity amounts
    and plain integers are returned unchanged.

    Args:
        s: A single-commodity amount string (no ``", "`` separator).

    Returns:
        Locale-formatted amount string, or the original if not matched.
    """
    m = _FMT_STR_RE.match(s)
    if not m:
        return s
    minus1, sym, minus2, numpart = m.groups()
    try:
        qty = Decimal(numpart.replace(",", "")).quantize(Decimal("0.01"))
        sign = Decimal(-1) if (minus1 or minus2) else Decimal(1)
        return fmt_amount(qty * sign, sym)
    except InvalidOperation:
        return s


def fmt_amount(qty: Decimal, commodity: str) -> str:
    """Format a decimal amount with its commodity symbol using the configured locale.

    Args:
        qty: The numeric quantity.
        commodity: The commodity symbol (e.g. ``'€'``, ``'EUR'``).

    Returns:
        A locale-formatted string like ``'€1.234,56'`` (it_IT) or
        ``'€1,234.56'`` (en_US), or just the formatted number if no commodity.
    """
    locale = _number_locale()
    formatted = format_decimal(qty, format="#,##0.00", locale=locale)
    if not commodity:
        return formatted
    if len(commodity) == 1:
        return f"{commodity}{formatted}"
    return f"{formatted} {commodity}"



def compute_saving_rate(income: Decimal, expenses: Decimal) -> float | None:
    """Compute the saving rate as a percentage of income.

    Saving rate = (income - expenses) / income * 100.
    Investments count as savings (they are not included in expenses).

    Args:
        income: Total income for the period.
        expenses: Total expenses for the period (excluding investments).

    Returns:
        The saving rate percentage, or None if income is zero.
    """
    if income <= 0:
        return None
    return float((income - expenses) / income * 100)
