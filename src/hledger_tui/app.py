"""Main Textual application for hledger-tui."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import ContentSwitcher, Static, Tab, Tabs

from hledger_tui.config import load_theme
from hledger_tui.widgets.accounts_pane import AccountsPane
from hledger_tui.widgets.transactions_pane import TransactionsPane

_FOOTER_TEXTS: dict[str, str] = {
    "transactions": "\\[a] Add  \\[e] Edit  \\[d] Delete  \\[/] Filter  \\[r] Refresh  \\[q] Quit",
    "accounts": "\\[Enter] View  \\[/] Filter  \\[r] Refresh  \\[q] Quit",
}


class HledgerTuiApp(App):
    """A TUI for managing hledger journal transactions."""

    TITLE = "hledger-tui"
    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("1", "switch_section('transactions')", "Transactions", show=False),
        Binding("2", "switch_section('accounts')", "Accounts", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, journal_file: Path) -> None:
        """Initialize the app.

        Args:
            journal_file: Path to the hledger journal file.
        """
        super().__init__()
        self.journal_file = journal_file
        saved_theme = load_theme()
        if saved_theme:
            self.theme = saved_theme

    def compose(self) -> ComposeResult:
        """Create the app layout."""
        yield Tabs(
            Tab("Transactions", id="tab-transactions"),
            Tab("Accounts", id="tab-accounts"),
            id="nav-tabs",
        )

        yield Static(str(self.journal_file), id="journal-bar")

        with ContentSwitcher(initial="transactions", id="content-switcher"):
            yield TransactionsPane(self.journal_file, id="transactions")
            yield AccountsPane(self.journal_file, id="accounts")

        yield Static(_FOOTER_TEXTS["transactions"], id="footer-bar")

    def on_key(self, event) -> None:
        """Enter the highlighted section when Enter or Down is pressed on the tab bar."""
        if isinstance(self.focused, Tabs) and event.key in ("enter", "down"):
            active = self.query_one("#nav-tabs", Tabs).active
            if active:
                self._activate_section(active.removeprefix("tab-"))
                event.stop()

    def _activate_section(self, section: str) -> None:
        """Switch the content pane and update the footer for the given section."""
        self.query_one("#content-switcher", ContentSwitcher).current = section
        self.query_one("#footer-bar", Static).update(_FOOTER_TEXTS.get(section, ""))

    def action_switch_section(self, section: str) -> None:
        """Switch to the given section via keyboard shortcut (1/2)."""
        self.query_one("#nav-tabs", Tabs).active = f"tab-{section}"
        self._activate_section(section)
