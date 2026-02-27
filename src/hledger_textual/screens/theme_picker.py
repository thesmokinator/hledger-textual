"""Theme picker modal screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

THEMES: list[str] = [
    "textual-dark",
    "textual-light",
    "nord",
    "dracula",
    "gruvbox",
    "catppuccin-mocha",
    "catppuccin-latte",
    "tokyo-night",
    "monokai",
    "flexoki",
    "solarized-light",
    "textual-ansi",
]


class ThemePickerModal(ModalScreen[str | None]):
    """A modal dialog to select a theme."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        """Create the modal layout."""
        with Vertical(id="theme-dialog"):
            yield Label("Select Theme", id="theme-title")
            yield OptionList(
                *[Option(name, id=name) for name in THEMES],
                id="theme-list",
            )

    def on_mount(self) -> None:
        """Highlight the currently active theme."""
        option_list = self.query_one("#theme-list", OptionList)
        current = self.app.theme
        for idx, name in enumerate(THEMES):
            if name == current:
                option_list.highlighted = idx
                break

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Dismiss with the selected theme name."""
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        """Cancel without changing theme."""
        self.dismiss(None)
