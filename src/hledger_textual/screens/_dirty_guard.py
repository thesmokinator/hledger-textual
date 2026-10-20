"""Two-step Escape guard for forms with unsaved changes (issue #149)."""

from __future__ import annotations

from typing import Any

from textual.widgets import Input, Select, TextArea


class DirtyGuardMixin:
    """Warn before discarding data typed into a form.

    The form's state is snapshotted once it has finished mounting
    (:meth:`capture_initial_state`) and compared when Escape is pressed.  The
    first Escape warns and arms the discard; a second Escape within
    :attr:`DISCARD_WINDOW` seconds discards the form, otherwise the warning
    simply expires.  A form with no changes still closes on the first Escape.
    """

    DISCARD_WINDOW: float = 3.0

    _initial_state: tuple[Any, ...] | None = None
    _discard_armed: bool = False

    def capture_initial_state(self) -> None:
        """Remember the current field values as the "clean" state."""
        self._initial_state = self._form_state()
        self._discard_armed = False

    def _form_state(self) -> tuple[Any, ...]:
        """Return the values that make the form "dirty" when changed."""
        state: list[Any] = []
        for widget in self.query(Input):
            state.append(widget.value)
        for widget in self.query(Select):
            state.append(widget.value)
        for widget in self.query(TextArea):
            state.append(widget.text)
        return tuple(state)

    def has_unsaved_changes(self) -> bool:
        """Whether any field differs from the state captured at mount."""
        if self._initial_state is None:
            return False
        return self._form_state() != self._initial_state

    def action_cancel(self) -> None:
        """Close the form, asking for confirmation when changes would be lost."""
        if not self.has_unsaved_changes() or self._discard_armed:
            self.dismiss(None)  # type: ignore[attr-defined]
            return

        self._discard_armed = True
        self.notify(  # type: ignore[attr-defined]
            "Unsaved changes \u2014 press Esc again to discard",
            severity="warning",
            timeout=int(self.DISCARD_WINDOW),
        )
        self.set_timer(self.DISCARD_WINDOW, self._disarm_discard)  # type: ignore[attr-defined]

    def _disarm_discard(self) -> None:
        """Forget the pending discard once the warning times out."""
        self._discard_armed = False
