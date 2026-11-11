"""Unit tests for the pane_mixin shared worker helpers (no app needed)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from hledger_textual.widgets.pane_mixin import run_mutation, run_pane_load


def _widget() -> SimpleNamespace:
    """A minimal widget double with a mock app and notify."""
    app = MagicMock()
    calls: list[tuple] = []
    app.call_from_thread.side_effect = lambda fn, *a, **k: calls.append((fn, a, k))
    widget = SimpleNamespace(app=app, notify=MagicMock(), _calls=calls)
    return widget


class TestRunMutation:
    """run_mutation paths: guard, messages, refresh, error styles."""

    def test_guard_falsy_skips_everything(self):
        """A falsy guard returns without touching the app."""
        widget = _widget()
        mutate = MagicMock()
        run_mutation(widget, mutate, success_message="ok", error_cls=ValueError, guard=None)
        mutate.assert_not_called()
        widget.app.call_from_thread.assert_not_called()

    def test_plain_success_message(self):
        """A string success message is notified with timeout 3."""
        widget = _widget()
        run_mutation(widget, lambda: None, success_message="done", error_cls=ValueError)
        widget.app.call_from_thread.assert_called_once_with(
            widget.notify, "done", timeout=3
        )

    def test_callable_success_message_is_evaluated(self):
        """A callable message is evaluated after mutate."""
        widget = _widget()
        seen: list[str] = []
        run_mutation(
            widget,
            lambda: seen.append("mutated"),
            success_message=lambda: f"count {len(seen)}",
            error_cls=ValueError,
        )
        widget.app.call_from_thread.assert_called_once_with(
            widget.notify, "count 1", timeout=3
        )

    def test_after_runs_before_success_toast(self):
        """The refresh callback is dispatched before the success toast."""
        widget = _widget()
        after = MagicMock()
        run_mutation(
            widget, lambda: None, success_message="ok", error_cls=ValueError, after=after
        )
        assert widget._calls[0][0] is after
        assert widget._calls[1][0] is widget.notify

    def test_plain_error_uses_str(self):
        """Without humanize_errors the raw message is notified (timeout 8)."""
        widget = _widget()

        def _raise():
            raise ValueError("bad thing")

        run_mutation(widget, _raise, success_message="ok", error_cls=ValueError)
        widget.app.call_from_thread.assert_called_once_with(
            widget.notify, "bad thing", severity="error", timeout=8
        )

    def test_humanized_error_uses_title_and_body(self):
        """With humanize_errors the toast carries title + body (timeout 10)."""
        widget = _widget()
        from hledger_textual.journal import JournalError

        def _raise():
            raise JournalError("disk full")

        run_mutation(
            widget, _raise, success_message="ok", error_cls=JournalError, humanize_errors=True
        )
        _args, kwargs = widget.app.call_from_thread.call_args
        assert kwargs["title"] == "Could not update the journal"
        assert "disk full" in _args[1]
        assert kwargs["severity"] == "error"
        assert kwargs["timeout"] == 10

    def test_unexpected_error_type_propagates(self):
        """Exceptions outside error_cls are not swallowed."""
        import pytest

        widget = _widget()

        def _raise():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            run_mutation(widget, _raise, success_message="ok", error_cls=ValueError)


class TestRunPaneLoad:
    """run_pane_load paths: overlay, apply, fallback."""

    def test_success_applies_result(self):
        """load() payload reaches apply() on the app thread."""
        widget = _widget()
        applied: list[object] = []
        run_pane_load(widget, lambda: 42, applied.append)
        widget.app.call_from_thread.assert_called_once_with(applied.append, 42)

    def test_loading_message_shows_overlay(self):
        """A loading message posts the overlay before loading."""
        from hledger_textual.widgets.loading import show_loading_overlay

        widget = _widget()
        run_pane_load(widget, lambda: None, lambda _r: None, loading_message="Busy…")
        first = widget._calls[0]
        assert first[0] is show_loading_overlay
        assert first[1] == (widget, "Busy…")

    def test_failure_without_on_error_skips_apply(self):
        """On load failure without fallback, apply never runs."""
        widget = _widget()
        applied: list[object] = []

        def _raise():
            raise OSError("gone")

        run_pane_load(widget, _raise, applied.append)
        assert all(call[0] is not applied.append for call in widget._calls)
        _args, kwargs = widget.app.call_from_thread.call_args
        assert kwargs["severity"] == "error"

    def test_failure_with_on_error_applies_fallback(self):
        """on_error(exc) supplies the payload apply() receives."""
        widget = _widget()
        applied: list[object] = []
        seen: list[Exception] = []

        def _raise():
            raise OSError("gone")

        def _fallback(exc: Exception):
            seen.append(exc)
            return "fallback"

        run_pane_load(widget, _raise, applied.append, on_error=_fallback)
        assert widget._calls[-1] == (applied.append, ("fallback",), {})
        assert isinstance(seen[0], OSError)
