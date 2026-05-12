"""Reusable base class for multi-action confirm modals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label

T = TypeVar("T")


@dataclass(frozen=True)
class ConfirmAction(Generic[T]):
    """One non-cancel button on a confirm modal.

    The button id is composed as ``f"btn-{prefix}-{id_suffix}"`` so the
    base class can route presses back to ``result`` without per-subclass
    handler code.
    """

    label: str
    id_suffix: str
    variant: str
    result: T


class ConfirmModalBase(ModalScreen[T | None], Generic[T]):
    """Generic confirm modal with one or more action buttons plus Cancel.

    Subclasses pass title, summary, an id ``prefix`` used for every
    composed widget (``{prefix}-dialog``, ``{prefix}-title``,
    ``{prefix}-summary``, ``{prefix}-buttons``, ``btn-{prefix}-cancel``,
    ``btn-{prefix}-{id_suffix}``), and a list of :class:`ConfirmAction`
    entries. Escape and the Cancel button both dismiss with ``None``;
    every other button dismisses with the matching ``result``.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        *,
        title: str,
        summary: str,
        prefix: str,
        actions: list[ConfirmAction[T]],
        cancel_label: str = "Cancel",
    ) -> None:
        super().__init__()
        self._title = title
        self._summary = summary
        self._prefix = prefix
        self._actions = actions
        self._cancel_label = cancel_label
        self._result_by_id: dict[str, T] = {
            f"btn-{prefix}-{action.id_suffix}": action.result for action in actions
        }

    def compose(self) -> ComposeResult:
        p = self._prefix
        with Vertical(id=f"{p}-dialog"):
            yield Label(self._title, id=f"{p}-title")
            yield Label(self._summary, id=f"{p}-summary")
            with Horizontal(id=f"{p}-buttons"):
                yield Button(self._cancel_label, variant="default", id=f"btn-{p}-cancel")
                for action in self._actions:
                    yield Button(action.label, variant=action.variant, id=f"btn-{p}-{action.id_suffix}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id in self._result_by_id:
            self.dismiss(self._result_by_id[btn_id])
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
