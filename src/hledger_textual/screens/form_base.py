"""Shared base class for modal form screens."""

from __future__ import annotations

from typing import Generic, TypeVar

from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Button

T = TypeVar("T")


class FormScreenBase(ModalScreen[T], Generic[T]):
    """Base class for modal forms with Save/Cancel buttons.

    Provides the Escape-to-cancel binding and routes button presses by id:
    ``SAVE_BUTTON_ID`` calls the subclass-implemented :meth:`_save`, and
    ``CANCEL_BUTTON_ID`` calls :meth:`action_cancel`. Subclasses with extra
    buttons override :meth:`_on_extra_button` instead of
    ``on_button_pressed``: Textual dispatches ``on_button_pressed`` once per
    class in the MRO that defines it, so an override calling ``super()``
    would run the Save/Cancel routing twice.

    The default :meth:`action_cancel` dismisses with ``None``. Forms that
    also inherit ``DirtyGuardMixin`` (placed before this class in the MRO)
    keep the mixin's two-step unsaved-changes guard instead.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    SAVE_BUTTON_ID = "btn-save"
    """Id of the button that triggers :meth:`_save`."""

    CANCEL_BUTTON_ID = "btn-form-cancel"
    """Id of the button that triggers :meth:`action_cancel`."""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route button presses to extra buttons, Save, or Cancel.

        Args:
            event: The button-pressed event to route.
        """
        if self._on_extra_button(event):
            return
        if event.button.id == self.SAVE_BUTTON_ID:
            self._save()
        elif event.button.id == self.CANCEL_BUTTON_ID:
            self.action_cancel()

    def _on_extra_button(self, event: Button.Pressed) -> bool:
        """Handle buttons other than Save/Cancel.

        Subclasses override this hook for their additional buttons.

        Args:
            event: The button-pressed event to inspect.

        Returns:
            True when the event was handled and must not be routed further.
        """
        return False

    def action_cancel(self) -> None:
        """Dismiss the form with no result."""
        self.dismiss(None)

    def _save(self) -> None:
        """Validate the form and dismiss with its result.

        Subclasses must override this method.
        """
        raise NotImplementedError
