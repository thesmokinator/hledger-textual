"""Unit tests for the sync confirmation modal variants (85% push)."""

from __future__ import annotations

from unittest.mock import MagicMock

from hledger_textual.screens.sync_confirm import SyncConfirmModal


def _backend(actions: list[str]):
    backend = MagicMock()
    backend.actions = actions
    backend.name = "Test"
    backend.confirm_message.return_value = "Confirm?"
    return backend


class TestSyncConfirmVariants:
    """Single- vs multi-action button construction."""

    def test_single_action_uses_primary(self):
        """One action becomes a single primary button."""
        modal = SyncConfirmModal(_backend(["sync"]))
        assert len(modal._actions) == 1
        assert modal._actions[0].id_suffix == "sync"
        assert modal._actions[0].variant == "primary"

    def test_last_action_is_primary_others_warning(self):
        """With several actions only the last is primary."""
        modal = SyncConfirmModal(_backend(["download", "upload"]))
        variants = {a.id_suffix: a.variant for a in modal._actions}
        assert variants == {"download": "warning", "upload": "primary"}
