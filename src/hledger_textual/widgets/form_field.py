"""Reusable label-plus-input row widget for form screens."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label


class FormField(Horizontal):
    """A single form row: a right-aligned label next to one input widget.

    Replaces the repeated ``Horizontal(Label(...), <Input>, classes=
    "form-field")`` boilerplate in the form screens. The row carries the
    shared ``form-field`` CSS class; required fields get the
    ``form-field--required`` class and an asterisk appended to the label,
    optional fields may request ``form-field--optional`` instead.
    """

    def __init__(
        self,
        label: str,
        child: Widget,
        *,
        required: bool = False,
        optional: bool = False,
        id: str | None = None,
    ) -> None:
        """Initialize the form field row.

        Args:
            label: Label text, e.g. ``"Date:"``. An asterisk is appended
                when *required* is true and the label does not already
                end with one.
            child: The input widget displayed next to the label.
            required: Mark the field as required (asterisk and styling).
            optional: Mark the field with the optional styling class.
            id: Optional DOM id for the row, for screens that query or
                toggle the whole row.
        """
        classes = "form-field"
        if required:
            classes += " form-field--required"
        elif optional:
            classes += " form-field--optional"
        super().__init__(id=id, classes=classes)
        self._label_text = f"{label}*" if required and not label.endswith("*") else label
        self._child = child

    def compose(self) -> ComposeResult:
        """Create the label and input layout."""
        yield Label(self._label_text)
        yield self._child
