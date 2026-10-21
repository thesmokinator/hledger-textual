"""Tests for the shared loading feedback helpers."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import LoadingIndicator, Static

from hledger_textual.widgets.loading import (
    LoadingOverlay,
    hide_loading_overlay,
    show_loading,
    show_loading_overlay,
)


class _HostApp(App[None]):
    """App with a single host container for loading bars."""

    def compose(self) -> ComposeResult:
        with Vertical(id="host"):
            yield Static("content")


async def test_show_and_hide_loading_overlay():
    """Showing mounts an animated indicator with the message; hiding removes it."""
    app = _HostApp()
    async with app.run_test() as pilot:
        host = app.query_one("#host")
        show_loading_overlay(host, "Loading report…")
        await pilot.pause()
        overlays = list(app.query(LoadingOverlay))
        assert len(overlays) == 1
        assert overlays[0].query_one(LoadingIndicator) is not None
        assert str(overlays[0].query_one(".loading-message", Static).renderable) == "Loading report…"

        hide_loading_overlay(host)
        await pilot.pause()
        assert list(app.query(LoadingOverlay)) == []


async def test_hide_without_show_is_noop():
    """Hiding without a matching show does nothing."""
    app = _HostApp()
    async with app.run_test() as pilot:
        host = app.query_one("#host")
        hide_loading_overlay(host)
        await pilot.pause()
        assert list(app.query(LoadingOverlay)) == []


async def test_loading_overlay_is_reference_counted():
    """Concurrent operations share one bar until all of them finish."""
    app = _HostApp()
    async with app.run_test() as pilot:
        host = app.query_one("#host")
        show_loading_overlay(host, "Loading…")
        show_loading_overlay(host, "Loading…")
        await pilot.pause()
        assert len(list(app.query(LoadingOverlay))) == 1

        hide_loading_overlay(host)
        await pilot.pause()
        assert len(list(app.query(LoadingOverlay))) == 1

        hide_loading_overlay(host)
        await pilot.pause()
        assert list(app.query(LoadingOverlay)) == []


async def test_show_loading_context_manager():
    """The async context manager shows the bar only inside the block."""
    app = _HostApp()
    async with app.run_test() as pilot:
        host = app.query_one("#host")
        async with show_loading(host, "Exporting…"):
            await pilot.pause()
            assert len(list(app.query(LoadingOverlay))) == 1
        await pilot.pause()
        assert list(app.query(LoadingOverlay)) == []


async def test_show_loading_removes_bar_on_error():
    """The bar is removed even when the wrapped block raises."""
    app = _HostApp()
    async with app.run_test() as pilot:
        host = app.query_one("#host")
        with pytest.raises(RuntimeError):
            async with show_loading(host, "Exporting…"):
                raise RuntimeError("boom")
        await pilot.pause()
        assert list(app.query(LoadingOverlay)) == []
