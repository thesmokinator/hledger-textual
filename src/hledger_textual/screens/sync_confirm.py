"""Sync confirmation modal screen."""

from __future__ import annotations

from hledger_textual.screens.confirm_base import ConfirmAction, ConfirmModalBase
from hledger_textual.sync import SyncBackend


class SyncConfirmModal(ConfirmModalBase[str]):
    """A modal dialog to confirm and choose a sync action.

    Adapts its buttons to the backend's available actions.
    Returns the chosen action string, or ``None`` on cancel.
    """

    def __init__(self, backend: SyncBackend) -> None:
        actions = backend.actions
        if len(actions) == 1:
            confirm_actions = [ConfirmAction(actions[0].capitalize(), actions[0], "primary", actions[0])]
        else:
            confirm_actions = [
                ConfirmAction(
                    action.capitalize(),
                    action,
                    "primary" if action == actions[-1] else "warning",
                    action,
                )
                for action in actions
            ]
        super().__init__(
            title=f"Sync ({backend.name})",
            summary=backend.confirm_message(),
            prefix="sync",
            actions=confirm_actions,
        )
