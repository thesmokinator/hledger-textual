"""A horizontally scrolling marquee widget for overflow text."""

from __future__ import annotations

from textual.timer import Timer
from textual.widgets import Static


class CurrencyMarquee(Static):
    """Scrolls a single line of text horizontally when it overflows."""

    DEFAULT_CSS = ""  # styling comes from app.tcss

    def __init__(
        self, content: str = "", *, tick_seconds: float = 0.05, gap: str = "   ", **kwargs
    ) -> None:
        """Initialize with the text to display and the ticker speed."""
        super().__init__(content, **kwargs)
        self._text = content
        self._offset = 0
        self._timer: Timer | None = None
        self._tick_seconds = tick_seconds
        self._gap = gap

    @property
    def _is_scrolling(self) -> bool:
        """True while the ticker is active."""
        return self._timer is not None

    @property
    def current_window(self) -> str:
        """The substring of the (possibly looped) text currently visible."""
        if len(self._text) <= self.size.width or self.size.width <= 0:
            return self._text
        belt = self._text + self._gap + self._text
        return belt[self._offset : self._offset + self.size.width]

    def set_content(self, text: str) -> None:
        """Replace the text, reset the scroll position, and restart the ticker if needed."""
        self._text = text
        self._offset = 0
        self._sync_scrolling()

    def on_mount(self) -> None:
        """Start the ticker if the content overflows the initial width."""
        self._sync_scrolling()

    def on_resize(self, event) -> None:
        """Re-evaluate whether to scroll when the widget width changes."""
        self._sync_scrolling()

    def _sync_scrolling(self) -> None:
        """Start or stop the ticker based on visibility and overflow, then refresh."""
        width = self.size.width
        overflowing = self.display and width > 0 and len(self._text) > width
        if overflowing and self._timer is None:
            self._timer = self.set_interval(self._tick_seconds, self._advance)
        elif not overflowing and self._timer is not None:
            self._timer.stop()
            self._timer = None
            self._offset = 0
        self.update(self.current_window)

    def _advance(self) -> None:
        """Advance the scroll offset by one column, wrapping around the belt."""
        wrap = len(self._text) + len(self._gap)
        self._offset = (self._offset + 1) % wrap
        self.update(self.current_window)

    def on_hide(self) -> None:
        """Stop the ticker when the widget is hidden."""
        self._sync_scrolling()

    def on_show(self) -> None:
        """Restart the ticker when the widget is shown again."""
        self._sync_scrolling()
