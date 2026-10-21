"""Amount and cost parsing helpers shared by forms and import code.

Extracted from the transaction form so amount strings (including ``@`` /
``@@`` cost annotations and commodity-directive styles) can be parsed and
unit-tested without mounting any UI.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from hledger_textual.amountutil import (
    decimal_places_for_number_string,
    normalize_number_string_for_style,
)
from hledger_textual.models import Amount, AmountStyle

# ---------------------------------------------------------------------------
# Hledger amount string parser
# ---------------------------------------------------------------------------
_SYM = r"[€$£¥₿₹]"
_NAME = r"[A-Za-z][A-Za-z0-9.]*"
_COMMODITY = rf"(?:{_SYM}|{_NAME})"
_UNSIGNED_QTY = r"\d+(?:[.,]\d+)*(?:[.,]\d+)?"
_SIGNED_QTY = r"-?\d+(?:[.,]\d+)*(?:[.,]\d+)?"

# -5.00 XEON @@ €742.59  OR  -5.00 XEON @ €148.518
_AMOUNT_COST_RE = re.compile(rf"^({_SIGNED_QTY})\s+({_COMMODITY})\s+(@@?)\s+(.+)$")
# -5.00 XEON  OR  5 USD
_AMOUNT_QTY_COMM_RE = re.compile(rf"^({_SIGNED_QTY})\s+({_COMMODITY})\s*$")
# €742.59, EUR 742.59, -€742.59, OR -EUR 742.59
_AMOUNT_COMM_QTY_RE = re.compile(rf"^(-?)({_COMMODITY})\s*({_UNSIGNED_QTY})\s*$")
_COMMODITY_DIRECTIVE_RE = re.compile(r"^\s*commodity\s+(.+?)\s*$")


def _decimal_places(qty_str: str, style: AmountStyle | None = None) -> int:
    """Return the number of decimal places in a numeric string."""
    return decimal_places_for_number_string(qty_str, style)


def _amount_style_from_parts(
    *,
    commodity_side: str,
    commodity_spaced: bool,
    precision: int,
    base_style: AmountStyle | None = None,
) -> AmountStyle:
    """Build an amount style, preserving locale separators from a base style."""
    return AmountStyle(
        commodity_side=commodity_side,
        commodity_spaced=commodity_spaced,
        decimal_mark=base_style.decimal_mark if base_style else ".",
        digit_group_separator=base_style.digit_group_separator if base_style else None,
        digit_group_sizes=list(base_style.digit_group_sizes) if base_style else [],
        precision=max(precision, base_style.precision) if base_style else precision,
    )


def _parse_decimal(qty_str: str, style: AmountStyle | None = None) -> Decimal:
    """Parse a quantity string according to a commodity style."""
    return Decimal(normalize_number_string_for_style(qty_str, style))


def _parse_commodity_directive_amount(amount_str: str) -> tuple[str, AmountStyle] | None:
    """Parse a ``commodity`` directive sample amount into commodity and style."""
    amount_str = amount_str.strip()

    match = _AMOUNT_COMM_QTY_RE.match(amount_str)
    if match:
        _sign, commodity, qty_str = match.groups()
        decimal_mark = "," if "," in qty_str and qty_str.rfind(",") > qty_str.rfind(".") else "."
        other_separator = "." if decimal_mark == "," else ","
        return (
            commodity,
            AmountStyle(
                commodity_side="L",
                commodity_spaced=True,
                decimal_mark=decimal_mark,
                digit_group_separator=other_separator if other_separator in qty_str else None,
                digit_group_sizes=[3] if other_separator in qty_str else [],
                precision=_decimal_places(qty_str),
            ),
        )

    match = _AMOUNT_QTY_COMM_RE.match(amount_str)
    if match:
        qty_str, commodity = match.groups()
        decimal_mark = "," if "," in qty_str and qty_str.rfind(",") > qty_str.rfind(".") else "."
        other_separator = "." if decimal_mark == "," else ","
        return (
            commodity,
            AmountStyle(
                commodity_side="R",
                commodity_spaced=True,
                decimal_mark=decimal_mark,
                digit_group_separator=other_separator if other_separator in qty_str else None,
                digit_group_sizes=[3] if other_separator in qty_str else [],
                precision=_decimal_places(qty_str),
            ),
        )

    return None


def load_journal_commodity_styles(file: Path) -> dict[str, AmountStyle]:
    """Load commodity styles declared directly in a journal file.

    Args:
        file: Path to the journal file.

    Returns:
        Mapping of commodity name to declared amount style.
    """
    try:
        lines = file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    styles: dict[str, AmountStyle] = {}
    for line in lines:
        match = _COMMODITY_DIRECTIVE_RE.match(line)
        if not match:
            continue
        parsed = _parse_commodity_directive_amount(match.group(1).split(";", 1)[0])
        if parsed is None:
            continue
        commodity, style = parsed
        styles[commodity] = style
    return styles


def extract_commodity_and_qty(
    s: str,
    commodity_styles: dict[str, AmountStyle] | None = None,
) -> tuple[Decimal, str, Decimal | None] | None:
    """Extract signed quantity, commodity name, and optional total proceeds.

    Handles amounts with named commodities such as ``-5 XEON`` or
    ``-5 XEON @@ €742.55``.  Returns ``None`` for currency-symbol-prefixed
    amounts (``€50``) and plain numbers.

    Args:
        s: Raw amount string entered by the user.

    Returns:
        ``(signed_qty, commodity, proceeds)`` when a named commodity is found,
        else ``None``.  ``signed_qty`` preserves the original sign so callers
        can distinguish sells (negative) from buys (positive).  ``proceeds``
        is the total transaction value when a cost annotation (``@`` or ``@@``)
        is present and parseable, otherwise ``None``.
    """
    s = s.strip()
    m = _AMOUNT_COST_RE.match(s)
    if m:
        qty_str, commodity, at_sign, cost_str = (
            m.group(1), m.group(2), m.group(3), m.group(4)
        )
        qty = _parse_decimal(qty_str, (commodity_styles or {}).get(commodity))
        proceeds: Decimal | None = None
        cost_amount = parse_simple_amount_str(cost_str.strip(), "", commodity_styles)
        if cost_amount is not None:
            if at_sign == "@":
                proceeds = abs(cost_amount.quantity) * abs(qty)
            else:  # @@
                proceeds = abs(cost_amount.quantity)
        return qty, commodity, proceeds
    m = _AMOUNT_QTY_COMM_RE.match(s)
    if m:
        qty_str, commodity = m.groups()
        return _parse_decimal(qty_str, (commodity_styles or {}).get(commodity)), commodity, None
    return None


def parse_simple_amount_str(
    s: str,
    default_commodity: str,
    commodity_styles: dict[str, AmountStyle] | None = None,
) -> Amount | None:
    """Parse a simple hledger amount string (no cost annotation).

    Handles: ``€742.59``, ``-€742.59``, ``-5.00 XEON``, ``742.59``.
    Returns None if the string cannot be parsed.
    """
    s = s.strip()

    commodity_styles = commodity_styles or {}

    m = _AMOUNT_COMM_QTY_RE.match(s)
    if m:
        sign, commodity, qty_str = m.groups()
        base_style = commodity_styles.get(commodity)
        qty = _parse_decimal(f"{sign}{qty_str}", base_style)
        style = _amount_style_from_parts(
            commodity_side="L",
            commodity_spaced=bool(base_style and base_style.commodity_spaced) or len(commodity) > 1,
            precision=max(_decimal_places(qty_str, base_style), 2 if len(commodity) == 1 else 0),
            base_style=base_style,
        )
        return Amount(commodity=commodity, quantity=qty, style=style)

    m = _AMOUNT_QTY_COMM_RE.match(s)
    if m:
        qty_str, commodity = m.groups()
        base_style = commodity_styles.get(commodity)
        qty = _parse_decimal(qty_str, base_style)
        style = _amount_style_from_parts(
            commodity_side=base_style.commodity_side if base_style else "R",
            commodity_spaced=base_style.commodity_spaced if base_style else True,
            precision=_decimal_places(qty_str, base_style),
            base_style=base_style,
        )
        return Amount(commodity=commodity, quantity=qty, style=style)

    try:
        base_style = commodity_styles.get(default_commodity)
        qty = _parse_decimal(s, base_style)
        style = _amount_style_from_parts(
            commodity_side=base_style.commodity_side
            if base_style
            else "L"
            if not default_commodity[:1].isdigit()
            else "R",
            commodity_spaced=base_style.commodity_spaced if base_style else len(default_commodity) > 1,
            precision=max(_decimal_places(s, base_style), 2),
            base_style=base_style,
        )
        return Amount(commodity=default_commodity, quantity=qty, style=style)
    except InvalidOperation:
        return None


def parse_amount_str(
    s: str,
    default_commodity: str,
    commodity_styles: dict[str, AmountStyle] | None = None,
) -> Amount | None:
    """Parse a hledger amount string including an optional cost annotation.

    Supports:

    - Simple number: ``742.59``, ``-742.59``
    - Currency prefix: ``€742.59``, ``-€742.59``
    - Quantity + commodity: ``-5.00 XEON``, ``5 USD``
    - With total cost: ``-5.00 XEON @@ €742.59``
    - With unit cost: ``-5.00 XEON @ €148.518`` (converted to total cost)

    Returns None if the string cannot be parsed.
    """
    s = s.strip()
    if not s:
        return None
    commodity_styles = commodity_styles or {}

    m = _AMOUNT_COST_RE.match(s)
    if m:
        qty_str, commodity, at_sign, cost_str = m.groups()
        base_style = commodity_styles.get(commodity)
        qty = _parse_decimal(qty_str, base_style)
        style = _amount_style_from_parts(
            commodity_side=base_style.commodity_side if base_style else "R",
            commodity_spaced=base_style.commodity_spaced if base_style else True,
            precision=_decimal_places(qty_str, base_style),
            base_style=base_style,
        )
        cost_amount = parse_simple_amount_str(cost_str.strip(), default_commodity, commodity_styles)
        if cost_amount is None:
            return None
        if at_sign == "@":
            cost_amount = Amount(
                commodity=cost_amount.commodity,
                quantity=abs(cost_amount.quantity * qty),
                style=cost_amount.style,
            )
        else:
            # Normalise @@ cost to always positive (hledger requires it).
            cost_amount = Amount(
                commodity=cost_amount.commodity,
                quantity=abs(cost_amount.quantity),
                style=cost_amount.style,
            )
        return Amount(commodity=commodity, quantity=qty, style=style, cost=cost_amount)

    return parse_simple_amount_str(s, default_commodity, commodity_styles)
