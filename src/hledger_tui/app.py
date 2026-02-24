"""Main Textual application for hledger-tui."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from hledger_tui.screens.transactions import TransactionsScreen


class HledgerTuiApp(App):
    """A TUI for managing hledger journal transactions."""

    TITLE = "hledger-tui"
    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(self, journal_file: Path) -> None:
        """Initialize the app.

        Args:
            journal_file: Path to the hledger journal file.
        """
        super().__init__()
        self.journal_file = journal_file

    def on_mount(self) -> None:
        """Push the main transactions screen on mount."""
        self.push_screen(TransactionsScreen(self.journal_file))
