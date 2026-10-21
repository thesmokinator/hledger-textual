"""Shared constants used across widgets, panes, and screens."""

from __future__ import annotations

from hledger_textual.models import TransactionStatus
from hledger_textual.recurring import SUPPORTED_PERIODS

PASSTHROUGH_KEYS: frozenset[str] = frozenset(
    {
        "backspace",
        "delete",
        "left",
        "right",
        "home",
        "end",
        "tab",
        "shift+tab",
        "escape",
        "enter",
        "up",
        "down",
    }
)
"""Keys that should pass through to the default Input handler."""

TREE_INDENT = "  "
"""Visual indentation used per hierarchy level when rendering account trees."""

# ---------------------------------------------------------------------------
# Transaction form
# ---------------------------------------------------------------------------

TRANSACTION_STATUS_OPTIONS: list[tuple[str, TransactionStatus]] = [
    ("Unmarked", TransactionStatus.UNMARKED),
    ("Pending (!)", TransactionStatus.PENDING),
    ("Cleared (*)", TransactionStatus.CLEARED),
]
"""Selectable transaction statuses in the transaction form."""

# ---------------------------------------------------------------------------
# Recurring form
# ---------------------------------------------------------------------------

RECURRING_PERIOD_OPTIONS: list[tuple[str, str]] = [
    (period.capitalize(), period) for period in SUPPORTED_PERIODS
] + [("Custom", "custom")]
"""Selectable period expressions in the recurring rule form."""

# ---------------------------------------------------------------------------
# Reports pane / budget overview
# ---------------------------------------------------------------------------

REPORT_TYPES: list[tuple[str, str]] = [
    ("Income Statement", "is"),
    ("Balance Sheet", "bs"),
    ("Cash Flow", "cf"),
]
"""Built-in report types offered by the reports pane."""

REPORT_LABELS: dict[str, str] = {value: label for label, value in REPORT_TYPES}
"""Human-readable label for each built-in report type code."""

REPORT_PERIOD_RANGES: list[tuple[str, int]] = [
    ("3 months", 3),
    ("6 months", 6),
    ("12 months", 12),
    ("Year to date", 0),
]
"""Selectable period ranges (label, months) for reports and budget overview."""

REPORT_PERIOD_LABELS: dict[int, str] = {months: label for label, months in REPORT_PERIOD_RANGES}
"""Human-readable label for each report period length in months."""

BUDGET_OVERVIEW_PERIOD_OPTIONS: list[tuple[str, int]] = REPORT_PERIOD_RANGES[:3]
"""Selectable period ranges in the budget overview (no year-to-date option)."""

# ---------------------------------------------------------------------------
# CSV import wizard
# ---------------------------------------------------------------------------

SEPARATOR_OPTIONS: list[tuple[str, str]] = [
    ("Comma (,)", ","),
    ("Semicolon (;)", ";"),
    ("Tab", "\t"),
    ("Pipe (|)", "|"),
]
"""Selectable CSV separator options in the import wizard."""

HEADER_OPTIONS: list[tuple[str, str]] = [
    ("Yes", "yes"),
    ("No", "no"),
]
"""Selectable header-row options in the import wizard."""

FIELD_OPTIONS: list[tuple[str, str]] = [
    ("(skip)", ""),
    ("date", "date"),
    ("date2", "date2"),
    ("status", "status"),
    ("code", "code"),
    ("description", "description"),
    ("comment", "comment"),
    ("amount", "amount"),
    ("amount-in", "amount-in"),
    ("amount-out", "amount-out"),
    ("currency", "currency"),
    ("account1", "account1"),
    ("account2", "account2"),
]
"""Selectable CSV column field mappings in the import wizard."""

# ---------------------------------------------------------------------------
# Custom report form
# ---------------------------------------------------------------------------

CUSTOM_REPORT_EXAMPLES: list[tuple[str, str]] = [
    ("balance --tree", "Full balance tree"),
    ("balance expenses --tree", "Expenses tree"),
    ("balance expenses --tree -M", "Monthly expenses tree"),
    ("balance income --tree", "Income tree"),
    ("balance assets --tree", "Assets tree"),
    ("register expenses -M", "Monthly expense register"),
    ("register income -M", "Monthly income register"),
    ("incomestatement -M", "Monthly income statement"),
    ("balancesheet", "Balance sheet"),
]
"""Example hledger commands offered by the custom report form."""

# ---------------------------------------------------------------------------
# Help screen
# ---------------------------------------------------------------------------

KEY_LABELS: dict[str, str] = {
    "slash": "/",
    "question_mark": "?",
    "exclamation_mark": "!",
    "enter": "Enter",
    "escape": "Esc",
    "space": "Space",
    "left": "Left",
    "right": "Right",
    "up": "Up",
    "down": "Down",
    "home": "Home",
    "end": "End",
    "tab": "Tab",
    "backspace": "Backspace",
}
"""Human-readable labels for Textual binding key names."""
