"""Shared constants used across widgets."""

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
