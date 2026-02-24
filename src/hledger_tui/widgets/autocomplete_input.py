"""Input widget with Tab-to-accept autocomplete."""

from __future__ import annotations

from textual.widgets import Input


class AutocompleteInput(Input):
    """An Input that accepts the current suggestion when Tab is pressed.

    If a suggestion is visible, Tab accepts it instead of moving focus.
    If no suggestion is shown, Tab moves focus normally.
    """

    async def _on_key(self, event) -> None:
        """Intercept Tab to accept suggestions."""
        if event.key == "tab" and self._suggestion and self._suggestion != self.value:
            event.prevent_default()
            event.stop()
            self.value = self._suggestion
            self.cursor_position = len(self.value)
            return
        await super()._on_key(event)
