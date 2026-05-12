"""Cloud sync confirmation modal screen."""

from __future__ import annotations

from hledger_textual.screens.confirm_base import ConfirmAction, ConfirmModalBase


class CloudSyncConfirmModal(ConfirmModalBase[str]):
    """A modal dialog to choose a cloud sync action.

    Returns ``"upload"``, ``"download"``, or ``None`` (cancel).
    """

    def __init__(self) -> None:
        super().__init__(
            title="Cloud Sync",
            summary="Upload your journal to the cloud or download from it?",
            prefix="cloud-sync",
            actions=[
                ConfirmAction("Download", "download", "warning", "download"),
                ConfirmAction("Upload", "upload", "primary", "upload"),
            ],
        )
