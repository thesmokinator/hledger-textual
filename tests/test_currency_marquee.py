"""Tests for the CurrencyMarquee widget."""

from __future__ import annotations

from textual.app import App, ComposeResult

from hledger_textual.widgets.currency_marquee import CurrencyMarquee
from tests.conftest import wait_until


class _MarqueeApp(App):
    """Minimal app wrapping a single CurrencyMarquee for isolated testing."""

    def __init__(self, content: str = "", tick_seconds: float = 0.05, width: int = 40):
        """Initialize with optional content, tick rate, and window width."""
        super().__init__()
        self._content = content
        self._tick = tick_seconds
        self._w = width

    def compose(self) -> ComposeResult:
        """Compose a single CurrencyMarquee widget at the given width."""
        widget = CurrencyMarquee(self._content, tick_seconds=self._tick, id="marquee")
        widget.styles.width = self._w
        yield widget


class TestCurrencyMarquee:
    """Tests for the CurrencyMarquee widget."""

    async def test_marquee_plain_when_fits(self):
        """A short line renders statically with no ticker and zero offset."""
        app = _MarqueeApp(content="€10.00", width=40)
        async with app.run_test() as pilot:
            await pilot.pause()
            m = app.query_one(CurrencyMarquee)
            assert m._offset == 0
            assert not m._is_scrolling
            assert m.current_window == "€10.00"

    async def test_marquee_scrolls_when_overflowing(self):
        """A line wider than the widget starts the ticker."""
        app = _MarqueeApp(content="A" * 100, width=20)
        async with app.run_test() as pilot:
            await pilot.pause()
            m = app.query_one(CurrencyMarquee)
            assert m._is_scrolling is True

    async def test_marquee_offset_advances(self):
        """The offset advances over time and the window matches the width."""
        app = _MarqueeApp(content="ABCDEFGHIJKLMNOP", tick_seconds=0.02, width=10)
        async with app.run_test() as pilot:
            await pilot.pause()
            m = app.query_one(CurrencyMarquee)
            start = m._offset
            await wait_until(pilot, lambda: m._offset > start)
            assert m._offset > start
            assert len(m.current_window) == 10

    async def test_marquee_pause_and_resume_on_display(self):
        """Hiding the widget stops the ticker; showing it restarts it."""
        app = _MarqueeApp(content="A" * 100, width=20)
        async with app.run_test() as pilot:
            await pilot.pause()
            m = app.query_one(CurrencyMarquee)
            assert m._is_scrolling
            m.display = False
            await pilot.pause()
            assert not m._is_scrolling
            m.display = True
            await pilot.pause()
            assert m._is_scrolling

    async def test_marquee_window_wraps_seamlessly(self):
        """At the wrap offset the window shows the gap then the text restart."""
        app = _MarqueeApp(content="ABCDE", tick_seconds=0.02, width=4)
        async with app.run_test() as pilot:
            await pilot.pause()
            m = app.query_one(CurrencyMarquee)
            m._offset = len(m._text)  # window shows the gap then the text restart
            window = m.current_window
            assert window == "   A"

    async def test_marquee_set_content_resets(self):
        """set_content resets the offset and adjusts the ticker."""
        app = _MarqueeApp(content="A" * 100, width=20)
        async with app.run_test() as pilot:
            await pilot.pause()
            m = app.query_one(CurrencyMarquee)
            assert m._is_scrolling
            m.set_content("XY")
            await pilot.pause()
            assert m._offset == 0
            assert not m._is_scrolling
            assert m.current_window == "XY"
