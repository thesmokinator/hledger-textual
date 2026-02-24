"""Date input widget with digits-only entry and auto-dash formatting."""

from __future__ import annotations

from textual.widgets import Input


class DateInput(Input):
    """An Input that only accepts digits and auto-inserts dashes for YYYY-MM-DD format.

    Digit keys are intercepted and formatted; non-digit characters (except
    navigation keys) are rejected.  The dashes at positions 4 and 7 are
    inserted automatically so the user only types the 8 digits.
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

    def __init__(self, **kwargs) -> None:
        """Initialize with sensible defaults for a date field."""
        kwargs.setdefault("max_length", 10)
        kwargs.setdefault("placeholder", "YYYY-MM-DD")
        super().__init__(**kwargs)

    @staticmethod
    def _format_date(raw_digits: str) -> str:
        """Format raw digits into YYYY-MM-DD, inserting dashes as needed.

        Args:
            raw_digits: A string of up to 8 digit characters.

        Returns:
            The formatted date string with dashes at positions 4 and 7.
        """
        digits = raw_digits[:8]
        if len(digits) <= 4:
            return digits
        if len(digits) <= 6:
            return f"{digits[:4]}-{digits[4:]}"
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"

    @staticmethod
    def _cursor_for_digit_pos(digit_pos: int) -> int:
        """Convert a digit-index (0-7) to the cursor position in the formatted string.

        Args:
            digit_pos: Index into the raw-digits string (0-based).

        Returns:
            The corresponding cursor position in the formatted string.
        """
        if digit_pos <= 4:
            return digit_pos
        if digit_pos <= 6:
            return digit_pos + 1  # account for dash after YYYY
        return digit_pos + 2  # account for both dashes

    async def _on_key(self, event) -> None:
        """Intercept keys: allow digits and navigation, reject everything else."""
        key = event.key

        # Let navigation keys pass through to the parent handler.
        if key in self._PASSTHROUGH_KEYS:
            await super()._on_key(event)
            return

        # Only accept single digit characters.
        if not (len(key) == 1 and key.isdigit()):
            event.prevent_default()
            event.stop()
            return

        # --- Digit handling with auto-formatting ---
        event.prevent_default()
        event.stop()

        current = self.value
        raw_digits = current.replace("-", "")

        # Don't exceed 8 digits (YYYYMMDD).
        if len(raw_digits) >= 8:
            return

        # Determine where to insert the new digit.
        cursor = self.cursor_position
        # Convert cursor position in formatted string to digit index.
        digit_pos = cursor
        if cursor > 4:
            digit_pos -= 1
        if cursor > 7:
            digit_pos -= 1
        digit_pos = min(digit_pos, len(raw_digits))

        raw_digits = raw_digits[:digit_pos] + key + raw_digits[digit_pos:]
        formatted = self._format_date(raw_digits)

        self.value = formatted
        self.cursor_position = self._cursor_for_digit_pos(digit_pos + 1)
