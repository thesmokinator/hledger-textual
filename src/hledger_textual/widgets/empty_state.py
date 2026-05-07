"""Reusable empty-state message for panes with no data."""

from __future__ import annotations

from textual.widgets import Static


class EmptyState(Static):
    """Centered pane message shown when a table or section has no rows.

    Args:
        title: Short headline for the empty state.
        message: Helpful explanation or next action.
        icon: Optional icon displayed before the title.
        action_hint: Optional extra hint rendered below the message.
    """

    DEFAULT_CSS = """
    EmptyState {
        width: 1fr;
        height: 1fr;
        content-align: center middle;
        padding: 2 4;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        title: str,
        message: str,
        icon: str = "",
        action_hint: str | None = None,
        **kwargs,
    ) -> None:
        """Initialize the empty-state text."""
        text_lines = [f"{icon}  {title}".strip(), "", message]
        if action_hint:
            text_lines.append("")
            text_lines.append(action_hint)
        super().__init__("\n".join(text_lines), **kwargs)
