"""Amount input widget with validation and auto-formatting to 2 decimal places."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from textual.events import Blur
from textual.widgets import Input


class AmountInput(Input):
    """An Input that only accepts valid amount characters and formats on blur.

    Accepted characters are digits (0-9), a single decimal point, and
    a minus sign (only at the beginning).  When the field loses focus
    the value is reformatted to exactly 2 decimal places.
    """

    # Keys that should pass through to the default Input handler.
    _PASSTHROUGH_KEYS = frozenset(
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

    # Characters allowed in amount input besides digits.
    _ALLOWED_CHARS = frozenset({"-", "."})

    def __init__(self, **kwargs) -> None:
        """Initialize with sensible defaults for an amount field."""
        kwargs.setdefault("placeholder", "0.00")
        super().__init__(**kwargs)

    @staticmethod
    def _format_amount(value: str) -> str:
        """Format a raw amount string to 2 decimal places.

        Args:
            value: The raw user input (e.g. "49", "-3.5", ".5").

        Returns:
            The value formatted with 2 decimal places, or the original
            string unchanged if it cannot be parsed.
        """
        stripped = value.strip()
        if not stripped:
            return ""
        try:
            d = Decimal(stripped)
            return f"{d:.2f}"
        except InvalidOperation:
            return stripped

    async def _on_key(self, event) -> None:
        """Intercept keys: allow digits, minus, dot, and navigation only."""
        key = event.key

        # Let navigation keys pass through.
        if key in self._PASSTHROUGH_KEYS:
            await super()._on_key(event)
            return

        # Use event.character for printable-character checks because Textual
        # maps some keys to names (e.g. "full_stop" for ".", "minus" for "-").
        char = event.character

        # Accept digits or allowed chars.
        if char and (char.isdigit() or char in self._ALLOWED_CHARS):
            # Minus sign: only valid at position 0 and only once.
            if char == "-":
                if self.cursor_position != 0 or "-" in self.value:
                    event.prevent_default()
                    event.stop()
                    return

            # Decimal point: only one allowed.
            if char == ".":
                if "." in self.value:
                    event.prevent_default()
                    event.stop()
                    return

            # Valid character — let the default handler insert it.
            await super()._on_key(event)
            return

        # Reject everything else.
        event.prevent_default()
        event.stop()

    def _on_blur(self, event: Blur) -> None:
        """Auto-format to 2 decimal places when the field loses focus."""
        formatted = self._format_amount(self.value)
        if formatted != self.value:
            self.value = formatted
