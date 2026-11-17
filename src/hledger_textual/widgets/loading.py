"""Reusable loading feedback for long-running background operations."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import LoadingIndicator, Static


class LoadingOverlay(Horizontal):
    """A slim loading bar with an animated indicator and a message."""

    def __init__(self, message: str) -> None:
        """Initialize the loading bar.

        Args:
            message: Text displayed next to the animated indicator.
        """
        super().__init__(classes="loading-overlay")
        self._message = message
        self._started = time.monotonic()

    def compose(self) -> ComposeResult:
        """Create the indicator and message layout."""
        yield LoadingIndicator()
        yield Static(self._message, classes="loading-message")

    def on_mount(self) -> None:
        """Start ticking the elapsed-time suffix."""
        self.set_interval(1.0, self._update_elapsed)

    def _update_elapsed(self) -> None:
        """Append the number of elapsed seconds to the message."""
        elapsed = int(time.monotonic() - self._started)
        if elapsed < 1 or not self.is_attached:
            return
        try:
            self.query_one(".loading-message", Static).update(
                f"{self._message} {elapsed}s"
            )
        except NoMatches:
            return


def show_loading_overlay(host: Widget, message: str) -> None:
    """Show a loading bar on *host*, reference-counted per host.

    Concurrent operations on the same host share one bar; the bar is
    removed when the matching number of :func:`hide_loading_overlay`
    calls has been made. Safe to call from the UI thread, including via
    ``app.call_from_thread`` from a worker.

    Args:
        host: The widget the loading bar is mounted on.
        message: Text displayed while loading.
    """
    count = getattr(host, "_loading_count", 0)
    host._loading_count = count + 1  # type: ignore[attr-defined]
    if count == 0:
        host.mount(LoadingOverlay(message))


def hide_loading_overlay(host: Widget) -> None:
    """Hide the loading bar shown by :func:`show_loading_overlay`.

    Idempotent: calling it without a matching show is a no-op.

    Args:
        host: The widget the loading bar was mounted on.
    """
    count = getattr(host, "_loading_count", 0)
    if count <= 0:
        return
    host._loading_count = count - 1  # type: ignore[attr-defined]
    if count - 1 == 0:
        for overlay in host.query(LoadingOverlay):
            overlay.remove()


@asynccontextmanager
async def show_loading(host: Widget, message: str) -> AsyncIterator[None]:
    """Show a loading bar on *host* for the duration of an async block.

    Usage::

        async with show_loading(self, "Exporting…"):
            ...

    The bar is removed when the block exits, including on error.

    Args:
        host: The widget the loading bar is mounted on.
        message: Text displayed while loading.

    Yields:
        None once the loading bar is visible.
    """
    show_loading_overlay(host, message)
    try:
        yield
    finally:
        hide_loading_overlay(host)
