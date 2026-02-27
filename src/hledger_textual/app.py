"""Main Textual application for hledger-textual."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import ContentSwitcher, DataTable, Static, Tab, Tabs

from hledger_textual.config import load_theme, save_theme
from hledger_textual.widgets.accounts_pane import AccountsPane
from hledger_textual.widgets.budget_pane import BudgetPane
from hledger_textual.widgets.info_pane import InfoPane
from hledger_textual.widgets.reports_pane import ReportsPane
from hledger_textual.widgets.summary_pane import SummaryPane
from hledger_textual.widgets.transactions_pane import TransactionsPane
from hledger_textual.widgets.transactions_table import TransactionsTable

_FOOTER_COMMANDS: dict[str, str] = {
    "summary": "\\[r] Reload  \\[q] Quit",
    "transactions": "\\[a] Add  \\[e] Edit  \\[d] Delete  \\[◄/►] Month  \\[/] Search  \\[r] Reload  \\[q] Quit",
    "accounts": "\\[↵] Drill  \\[/] Search  \\[r] Reload  \\[q] Quit",
    "budget": "\\[a] Add  \\[e] Edit  \\[d] Delete  \\[◄/►] Month  \\[/] Search  \\[q] Quit",
    "reports": "\\[r] Reload  \\[q] Quit",
    "info": "\\[t] Theme  \\[q] Quit",
}


class _NavTab(Tab):
    """Tab that never receives keyboard focus."""

    ALLOW_FOCUS = False


class _NavTabs(Tabs):
    """Tab bar that never receives keyboard focus and ignores arrow keys."""

    ALLOW_FOCUS = False

    def action_previous_tab(self) -> None:
        """Disable arrow-key tab switching."""

    def action_next_tab(self) -> None:
        """Disable arrow-key tab switching."""


class HledgerTuiApp(App):
    """A TUI for managing hledger journal transactions."""

    TITLE = "hledger-textual"
    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("1", "switch_section('summary')", "Summary", show=False),
        Binding("2", "switch_section('transactions')", "Transactions", show=False),
        Binding("3", "switch_section('budget')", "Budget", show=False),
        Binding("4", "switch_section('reports')", "Reports", show=False),
        Binding("5", "switch_section('accounts')", "Accounts", show=False),
        Binding("6", "switch_section('info')", "Info", show=False),
        Binding("q", "quit", "Quit"),
        Binding("t", "pick_theme", "Theme", show=False),
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
        yield _NavTabs(
            _NavTab("1. Summary", id="tab-summary"),
            _NavTab("2. Transactions", id="tab-transactions"),
            _NavTab("3. Budget", id="tab-budget"),
            _NavTab("4. Reports", id="tab-reports"),
            _NavTab("5. Accounts", id="tab-accounts"),
            _NavTab("6. Info", id="tab-info"),
            id="nav-tabs",
        )

        with ContentSwitcher(initial="summary", id="content-switcher"):
            yield SummaryPane(self.journal_file, id="summary")
            yield TransactionsPane(self.journal_file, id="transactions")
            yield BudgetPane(self.journal_file, id="budget")
            yield ReportsPane(self.journal_file, id="reports")
            yield AccountsPane(self.journal_file, id="accounts")
            yield InfoPane(self.journal_file, id="info")

        yield Static(_FOOTER_COMMANDS["summary"], id="footer-bar")

    def on_mount(self) -> None:
        """Focus the default section after mount."""
        self._focus_section("summary")

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        """Handle tab activation (click) — switch content and focus."""
        if not event.tab or not event.tab.id:
            return
        section = event.tab.id.removeprefix("tab-")
        self.query_one("#content-switcher", ContentSwitcher).current = section
        self.query_one("#footer-bar", Static).update(
            _FOOTER_COMMANDS.get(section, "")
        )
        self._focus_section(section)

    def _activate_section(self, section: str) -> None:
        """Set the active tab — triggers on_tabs_tab_activated."""
        self.query_one("#nav-tabs", _NavTabs).active = f"tab-{section}"

    def _focus_section(self, section: str) -> None:
        """Move keyboard focus to the main widget in the given section."""
        if section == "summary":
            self.query_one("#summary-breakdown-table", DataTable).focus()
        elif section == "transactions":
            self.query_one(TransactionsTable).query_one(DataTable).focus()
        elif section == "accounts":
            self.query_one("#accounts-table", DataTable).focus()
        elif section == "budget":
            self.query_one("#budget-table", DataTable).focus()
        elif section == "reports":
            self.query_one("#reports-table", DataTable).focus()
        elif section == "info":
            self.query_one(InfoPane).focus()

    def action_switch_section(self, section: str) -> None:
        """Switch to the given section via keyboard shortcut (1-6)."""
        self._activate_section(section)

    def action_pick_theme(self) -> None:
        """Open the theme picker dialog."""
        from hledger_textual.screens.theme_picker import ThemePickerModal

        def on_theme_selected(theme: str | None) -> None:
            if theme is not None:
                self.theme = theme
                save_theme(theme)
                self.query_one(InfoPane).apply_theme(theme)

        self.push_screen(ThemePickerModal(), callback=on_theme_selected)
