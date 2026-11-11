"""Main Textual application for hledger-textual."""

from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import ContentSwitcher, DataTable, Static, Tab, Tabs

from hledger_textual.cache import HledgerCache
from hledger_textual.config import (
    load_auto_generate_recurring,
    load_sync_config,
    load_tab_order,
    load_theme,
)
from hledger_textual.sync import SyncBackend, SyncError, create_sync_backend
from hledger_textual.widgets.accounts_pane import AccountsPane
from hledger_textual.widgets.budget_pane import BudgetPane
from hledger_textual.widgets.recurring_pane import RecurringPane
from hledger_textual.widgets.reports_pane import ReportsPane
from hledger_textual.widgets.summary_pane import SummaryPane
from hledger_textual.widgets.transactions_pane import TransactionsPane
from hledger_textual.widgets.transactions_table import TransactionsTable


#: Default tab order (issue #165): account-first workflow.
DEFAULT_TAB_ORDER = (
    "summary",
    "accounts",
    "transactions",
    "budget",
    "recurring",
    "reports",
)

#: Human-readable tab labels.  "Recurring" was renamed because it was
#: ambiguous with recurring reports; "Recurring Txns" names the content.
TAB_LABELS = {
    "summary": "Summary",
    "accounts": "Accounts",
    "transactions": "Transactions",
    "budget": "Budget",
    "recurring": "Recurring Txns",
    "reports": "Reports",
}


def resolve_tab_order(configured: list[str] | None) -> list[str]:
    """Resolve the effective tab order from config.

    Unknown names are dropped; sections missing from the configuration
    keep their relative default order at the end.

    Args:
        configured: The ``tab_order`` value from config, or ``None``.

    Returns:
        The ordered section names covering every known section exactly once.
    """
    if not configured:
        return list(DEFAULT_TAB_ORDER)
    known = [name for name in configured if name in TAB_LABELS]
    missing = [name for name in DEFAULT_TAB_ORDER if name not in known]
    return known + missing or list(DEFAULT_TAB_ORDER)


def _build_footer_commands(sync_enabled: bool) -> dict[str, str]:
    """Build the footer command strings.

    Args:
        sync_enabled: Whether the sync shortcut should be shown.

    Returns:
        A dict mapping section name to footer text.
    """
    sync_part = "\\[s] Sync  " if sync_enabled else ""
    global_part = f"\\[x] Export  {sync_part}\\[?] Help  \\[q] Quit"
    global_no_export = f"{sync_part}\\[?] Help  \\[q] Quit"
    return {
        "summary": f"\\[r] Reload  \\[i]/\\[l] Fold  {global_no_export}",
        "transactions": f"\\[a] Add  \\[e] Edit  \\[d] Del  \\[c] Clone  \\[m] Move  \\[◄/►] Month  \\[/] Search  \\[f] Filters  \\[^s] Save filter  {global_part}",
        "accounts": f"\\[↵] Drill  \\[/] Search  \\[r] Reload  {global_part}",
        "budget": f"\\[a] Add  \\[e] Edit  \\[d] Del  \\[◄/►] Month  \\[/] Search  \\[o] Overview  {global_part}",
        "reports": f"\\[n] New  \\[S] Sort  \\[c] Chart  \\[i] Inv  \\[r] Reload  {global_part}",
        "reports-custom": f"\\[esc] Back  \\[n] New  \\[e] Edit  \\[d] Del  \\[r] Reload  {global_part}",
        "recurring": f"\\[a] Add  \\[e] Edit  \\[d] Del  \\[g] Generate  \\[r] Reload  {global_part}",
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
        # Number keys follow the visual tab order (see tab_order in config),
        # so their help descriptions name the default sections at each slot.
        Binding("1", "switch_nth(0)", "Summary", show=False),
        Binding("2", "switch_nth(1)", "Accounts", show=False),
        Binding("3", "switch_nth(2)", "Transactions", show=False),
        Binding("4", "switch_nth(3)", "Budget", show=False),
        Binding("5", "switch_nth(4)", "Recurring Txns", show=False),
        Binding("6", "switch_nth(5)", "Reports", show=False),
        Binding("s", "sync", "Sync", show=False),
        Binding("question_mark", "show_help", "Help", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, journal_file: Path) -> None:
        """Initialize the app.

        Args:
            journal_file: Path to the hledger journal file.
        """
        super().__init__()
        self.journal_file = journal_file
        self._cache = HledgerCache()
        self._stale_panes: set[str] = set()
        self._sync_backend: SyncBackend | None = None
        sync_config = load_sync_config()
        if sync_config:
            method = sync_config.get("method", "git")
            try:
                self._sync_backend = create_sync_backend(
                    method, journal_file, sync_config
                )
            except SyncError:
                pass
        self._footer_commands = _build_footer_commands(self._sync_backend is not None)
        self._tab_order = resolve_tab_order(load_tab_order())
        saved_theme = load_theme()
        if saved_theme:
            self.theme = saved_theme

    def _pane_for_section(self, section: str):
        """Build the pane widget for a tab section."""
        if section == "summary":
            return SummaryPane(self.journal_file, cache=self._cache, id="summary")
        if section == "transactions":
            return TransactionsPane(
                self.journal_file, cache=self._cache, id="transactions"
            )
        if section == "budget":
            return BudgetPane(self.journal_file, cache=self._cache, id="budget")
        if section == "reports":
            return ReportsPane(self.journal_file, cache=self._cache, id="reports")
        if section == "accounts":
            return AccountsPane(self.journal_file, cache=self._cache, id="accounts")
        return RecurringPane(self.journal_file, id="recurring")

    def compose(self) -> ComposeResult:
        """Create the app layout, with tabs in the configured order."""
        yield _NavTabs(
            *[
                _NavTab(f"{i + 1}. {TAB_LABELS[section]}", id=f"tab-{section}")
                for i, section in enumerate(self._tab_order)
            ],
            id="nav-tabs",
        )

        with ContentSwitcher(initial="summary", id="content-switcher"):
            for section in self._tab_order:
                yield self._pane_for_section(section)

        yield Static(self._footer_commands["summary"], id="footer-bar")

    def on_mount(self) -> None:
        """Focus the default section after mount."""
        self._focus_section("summary")
        self._check_for_updates()
        if load_auto_generate_recurring():
            self._auto_generate_recurring()

    @work(thread=True, exclusive=True, group="startup-update-check")
    def _check_for_updates(self) -> None:
        """Check PyPI for a newer version and notify once if found."""
        import importlib.metadata

        from hledger_textual.updates import get_latest_version, is_newer

        try:
            meta = importlib.metadata.metadata("hledger-textual")
            current = meta.get("Version", "0")
        except importlib.metadata.PackageNotFoundError:
            return

        latest = get_latest_version()
        if latest and is_newer(latest, current):
            self.app.call_from_thread(
                self.notify,
                f"hledger-textual {latest} is available (current: {current})",
                severity="information",
                timeout=8,
            )

    @work(thread=True, exclusive=True, group="startup-auto-generate")
    def _auto_generate_recurring(self) -> None:
        """Auto-generate pending recurring transactions for the current month on startup."""
        from datetime import date

        from hledger_textual.recurring import (
            RecurringError,
            compute_pending,
            ensure_recurring_file,
            generate_transactions,
            parse_recurring_rules,
        )

        try:
            recurring_path = ensure_recurring_file(self.journal_file)
            rules = parse_recurring_rules(recurring_path)
        except Exception:
            return

        today = date.today()
        pending: list[tuple] = []
        for rule in rules:
            try:
                dates = compute_pending(rule, self.journal_file, today)
            except Exception:
                continue
            if dates:
                pending.append((rule, dates))

        if not pending:
            return

        for rule, dates in pending:
            try:
                generate_transactions(rule, dates, self.journal_file)
            except RecurringError:
                return

        total = sum(len(d) for _, d in pending)
        self.app.call_from_thread(
            self.notify,
            f"Auto-generated {total} recurring transaction(s)",
            severity="information",
            timeout=5,
        )
        self.app.call_from_thread(self._refresh_all_panes)

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        """Handle tab activation (click) — switch content and focus."""
        if not event.tab or not event.tab.id:
            return
        section = event.tab.id.removeprefix("tab-")
        self.query_one("#content-switcher", ContentSwitcher).current = section
        self.query_one("#footer-bar", Static).update(
            self._footer_commands.get(section, "")
        )
        if section in self._stale_panes:
            self._stale_panes.discard(section)
            self._refresh_pane(section)
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
        elif section == "recurring":
            self.query_one("#recurring-table", DataTable).focus()

    def _refresh_all_panes(self) -> None:
        """Invalidate cache, refresh visible pane, mark others stale."""
        self._cache.invalidate_all()
        switcher = self.query_one("#content-switcher", ContentSwitcher)
        visible = switcher.current or "summary"
        all_sections = {"summary", "transactions", "accounts", "budget", "reports", "recurring"}
        self._stale_panes = all_sections - {visible}
        self._refresh_pane(visible)

    def _refresh_pane(self, section: str) -> None:
        """Refresh a single pane by name."""
        if section == "summary":
            pane = self.query_one(SummaryPane)
            pane._load_static_data()
            pane._load_breakdown_data()
        elif section == "transactions":
            self.query_one(TransactionsPane).reload()
        elif section == "accounts":
            self.query_one(AccountsPane)._load_data()
        elif section == "budget":
            self.query_one(BudgetPane)._load_budget_data()
        elif section == "reports":
            self.query_one(ReportsPane)._load_report_data()
        elif section == "recurring":
            self.query_one(RecurringPane)._load_data()

    def on_transactions_table_journal_changed(
        self, event: TransactionsTable.JournalChanged
    ) -> None:
        """Silently refresh all data panes after a journal mutation."""
        self._refresh_all_panes()

    def on_recurring_pane_journal_changed(
        self, event: RecurringPane.JournalChanged
    ) -> None:
        """Silently refresh all data panes after recurring transactions are generated."""
        self._refresh_all_panes()

    def on_reports_pane_custom_report_state_changed(
        self, event: ReportsPane.CustomReportStateChanged
    ) -> None:
        """Update the Reports footer when switching between built-in and custom modes."""
        key = "reports-custom" if event.active else "reports"
        self.query_one("#footer-bar", Static).update(
            self._footer_commands.get(key, "")
        )

    def action_switch_section(self, section: str) -> None:
        """Switch to the given section."""
        self._activate_section(section)

    def action_switch_nth(self, index: int) -> None:
        """Switch to the tab at the given position (number keys 1-6)."""
        if 0 <= index < len(self._tab_order):
            self._activate_section(self._tab_order[index])

    def action_show_help(self) -> None:
        """Open the combined help and about panel."""
        from hledger_textual.screens.help import HelpScreen

        self.push_screen(HelpScreen(self.journal_file))

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Gate actions on app state.

        - ``sync`` is disabled when no backend is configured.
        - ``command_palette`` is disabled while the import wizard is open:
          the wizard binds Ctrl+P to "previous step", and the app-level
          palette binding (priority) would otherwise swallow the key
          before the modal screen ever sees it.
        """
        if action == "sync":
            return self._sync_backend is not None
        if action == "command_palette":
            from hledger_textual.screens.import_wizard import ImportWizardScreen

            if isinstance(self.screen, ImportWizardScreen):
                return False
        return True

    def action_sync(self) -> None:
        """Show sync confirmation dialog, then run the configured backend."""
        from hledger_textual.screens.sync_confirm import SyncConfirmModal

        backend = self._sync_backend
        if backend is None:
            return

        if not backend.is_available():
            self.notify(
                f"{backend.name} is not available",
                severity="error",
                timeout=8,
            )
            return

        def on_result(action: str | None) -> None:
            if action is not None:
                self._run_sync(action)

        self.push_screen(SyncConfirmModal(backend), callback=on_result)

    @work(thread=True, exclusive=True, group="sync")
    def _run_sync(self, action: str) -> None:
        """Execute the sync action in a background thread.

        Args:
            action: The action name from the backend.
        """
        backend = self._sync_backend
        if backend is None:
            return

        self.app.call_from_thread(
            self.notify, f"Syncing ({backend.name})...", severity="information"
        )
        try:
            result = backend.run(action, self.journal_file)
            self.app.call_from_thread(
                self.notify, result, severity="information"
            )
            if action == "download":
                self.app.call_from_thread(self._refresh_all_panes)
        except SyncError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )
