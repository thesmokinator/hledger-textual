"""Unit tests for the confirm-modal base dispatch (85% push)."""

from __future__ import annotations

from types import SimpleNamespace

from hledger_textual.screens.confirm_base import ConfirmAction, ConfirmModalBase


def _modal() -> ConfirmModalBase:
    modal = ConfirmModalBase(
        title="T",
        summary="S",
        prefix="x",
        actions=[ConfirmAction("Go", "go", "primary", "go-result")],
    )
    modal.dismiss = lambda result: setattr(modal, "_dismissed", result)  # type: ignore[method-assign]
    return modal


class TestConfirmBaseDispatch:
    """Button presses route to results; unknown ids dismiss with None."""

    def test_known_button_dismisses_with_result(self):
        """A mapped button id dismisses with its action result."""
        modal = _modal()
        event = SimpleNamespace(button=SimpleNamespace(id="btn-x-go"))
        modal.on_button_pressed(event)
        assert modal._dismissed == "go-result"

    def test_unknown_button_dismisses_none(self):
        """An unmapped id (e.g. Cancel) dismisses with None."""
        modal = _modal()
        event = SimpleNamespace(button=SimpleNamespace(id="btn-x-cancel"))
        modal.on_button_pressed(event)
        assert modal._dismissed is None

    def test_missing_button_id_dismisses_none(self):
        """A button without an id dismisses with None."""
        modal = _modal()
        event = SimpleNamespace(button=SimpleNamespace(id=None))
        modal.on_button_pressed(event)
        assert modal._dismissed is None
