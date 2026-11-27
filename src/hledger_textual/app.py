"""Main Textual application for hledger-textual."""

from __future__ import annotations

from collections.abc import Callable, Collection
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import ContentSwitcher, DataTable, Static, Tab, Tabs

from hledger_textual.cache import HledgerCache
from hledger_textual.config import (
    load_auto_generate_recurring,
    load_sync_config,
    load_tab_order,
    load_theme,
)
from hledger_textual.period import PeriodSelection, current_month_selection, month_selection
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


def _build_footer_commands(
    sync_enabled: bool, read_only: bool = False
) -> dict[str, str]:
    """Build the footer command strings.

    Args:
        sync_enabled: Whether the sync shortcut should be shown.
        read_only: Prepend a persistent READ-ONLY marker to every footer.

    Returns:
        A dict mapping section name to footer text.
    """
    sync_part = "\\[s] Sync  " if sync_enabled else ""
    global_part = f"\\[x] Export  {sync_part}\\[?] Help  \\[q] Quit"
    global_no_export = f"{sync_part}\\[?] Help  \\[q] Quit"
    ro_part = "\\[READ-ONLY]  " if read_only else ""
    return {
        "summary": f"{ro_part}\\[◄/►] Month  \\[r] Reload  \\[i]/\\[l] Fold  {global_no_export}",
        "transactions": f"{ro_part}\\[a] Add  \\[e] Edit  \\[d] Del  \\[c] Clone  \\[m] Move  \\[◄/►] Month  \\[g] Period  \\[/] Search  \\[f] Filters  \\[^s] Save filter  {global_part}",
        "accounts": f"{ro_part}\\[↵] Drill  \\[/] Search  \\[r] Reload  {global_part}",
        "budget": f"{ro_part}\\[a] Add  \\[e] Edit  \\[d] Del  \\[◄/►] Month  \\[/] Search  \\[o] Overview  {global_part}",
        "reports": f"{ro_part}\\[◄/►] Window  \\[n] New  \\[S] Sort  \\[c] Chart  \\[i] Inv  \\[r] Reload  {global_part}",
        "reports-custom": f"{ro_part}\\[esc] Back  \\[n] New  \\[e] Edit  \\[d] Del  \\[r] Reload  {global_part}",
        "recurring": f"{ro_part}\\[a] Add  \\[e] Edit  \\[d] Del  \\[g] Generate  \\[r] Reload  {global_part}",
    }


def _resolve_saved_theme(saved_theme: str | None, available: Collection[str]) -> str | None:
    """Resolve a theme saved in config against Textual's available themes.

    Textual 8 removed the ``textual-ansi`` theme in favour of ``ansi-dark``
    and ``ansi-light``.  ``ansi-dark`` was added in 8.2.5, so it is only used
    when the running Textual version provides it.

    Args:
        saved_theme: Theme name stored in the config file, or None.
        available: Names of the themes registered with the app.

    Returns:
        A valid theme name, or None to keep Textual's default theme.
    """
    if not saved_theme:
        return None
    if saved_theme == "textual-ansi":
        return "ansi-dark" if "ansi-dark" in available else None
    return saved_theme if saved_theme in available else None


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

    #: Shared period selection every pane derives its time scope from
    #: (issue #263).  Panes no longer keep private "today" anchors; they
    #: read this reactive and reload when it changes.
    period_selection: reactive[PeriodSelection | None] = reactive(None, init=False)

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
        Binding("p", "period_presets", "Period presets", show=True),
        Binding("P", "save_period_view", "Save period view", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        journal_file: Path,
        initial_period: PeriodSelection | None = None,
        read_only: bool = False,
    ) -> None:
        """Initialize the app.

        Args:
            journal_file: Path to the hledger journal file.
            initial_period: Period the app starts on (from ``-p``/``-b``/``-e``
                flags or the ``default_period`` config key); None means the
                current month, with the landing heuristic of #267 allowed to
                move to the latest activity when the current month is empty.
            read_only: Disable every write path (issue #271). Exports,
                search, period navigation and drill-down stay available.
        """
        super().__init__()
        self.journal_file = journal_file
        # An explicit period (CLI/config) must not be overridden by the
        # startup landing heuristic.
        self._period_explicit = initial_period is not None
        self.read_only = read_only
        self._cache = HledgerCache()
        self._stale_panes: set[str] = set()
        # Non-visible panes defer their initial hledger load until the Summary
        # has painted, so the first screen is not queued behind transactions
        # import/parse.  Switching to a pane early flushes its queued loads.
        self._deferred_loads: list[tuple[str, Callable[[], None]]] = []
        self._preload_started = False
        self._sync_backend: SyncBackend | None = None
        #: Journal statistics (with the date span), set once the Summary loads
        #: them; used by the startup landing heuristic (issue #267) and later
        #: by the period picker for validation.
        self.journal_stats = None
        self._landing_checked = False
        sync_config = load_sync_config()
        if sync_config:
            method = sync_config.get("method", "git")
            try:
                self._sync_backend = create_sync_backend(
                    method, journal_file, sync_config
                )
            except SyncError:
                pass
        self._footer_commands = _build_footer_commands(
            self._sync_backend is not None, read_only
        )
        self._tab_order = resolve_tab_order(load_tab_order())
        theme = _resolve_saved_theme(load_theme(), self.available_themes)
        if theme:
            self.theme = theme
        self.period_selection = initial_period or current_month_selection()

    # ------------------------------------------------------------------
    # Shared period state (issue #263)
    # ------------------------------------------------------------------

    def watch_period_selection(self, new: PeriodSelection | None) -> None:
        """Refresh the visible pane and mark the others stale on a period change.

        Panes are not rebuilt: the visible one reloads now, the period-aware
        ones reload when they are next activated (via ``_stale_panes``).
        """
        if new is None or not self.is_mounted:
            return
        try:
            switcher = self.query_one("#content-switcher", ContentSwitcher)
        except Exception:
            return
        visible = switcher.current or "summary"
        # Accounts and Recurring are period-independent; only the four
        # panes scoped by time need refreshing.
        period_sections = {"summary", "transactions", "budget", "reports"}
        self._stale_panes |= period_sections - {visible}
        self._refresh_pane(visible, period_only=True)

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
        # Safety net: if the Summary never reports loaded, still preload the
        # other panes rather than leaving them empty forever.
        self.set_timer(30.0, self._start_deferred_loads)
        if load_auto_generate_recurring() and not self.read_only:
            self._auto_generate_recurring()
        if self.read_only:
            self.notify(
                "Read-only mode: no changes will be written to the journal",
                severity="information",
                timeout=8,
            )

    # ------------------------------------------------------------------
    # Startup pane preloading
    # ------------------------------------------------------------------

    def request_initial_load(
        self, section: str, loader: Callable[[], None]
    ) -> None:
        """Run a pane's initial load, or queue it until the Summary is ready.

        Args:
            section: Tab section owning the loader (``"accounts"``, ...).
            loader: Zero-argument callable starting the pane's load.
        """
        if self._preload_started or section == "summary":
            loader()
        else:
            self._deferred_loads.append((section, loader))

    @on(SummaryPane.Loaded)
    def _on_summary_loaded(self, event: SummaryPane.Loaded) -> None:
        """Kick off the deferred pane loads once the Summary has painted."""
        self._start_deferred_loads()

    @on(SummaryPane.StatsLoaded)
    def _on_summary_stats_loaded(self, event: SummaryPane.StatsLoaded) -> None:
        """Store the journal span and land on the latest month when needed.

        The landing heuristic runs once at startup: if the newest transaction
        predates the current month, the current month is provably empty, so
        the app starts on the month of the latest activity (issue #267).
        Journals with no data or with future-dated transactions are left on
        the current month without any notice.
        """
        self.journal_stats = event.stats
        if self._landing_checked:
            return
        self._landing_checked = True
        stats = event.stats
        if stats.last_date is None:
            return
        from datetime import date

        today = date.today()
        latest = stats.last_date
        if (latest.year, latest.month) >= (today.year, today.month):
            return
        if self._period_explicit or self.period_selection != current_month_selection():
            return  # user, CLI flag or config already chose a period
        self.period_selection = month_selection(latest)
        self.notify(
            f"Showing {latest.strftime('%b %Y')} — latest activity in this journal",
            severity="information",
            timeout=10,
        )

    def _start_deferred_loads(self) -> None:
        """Start every queued initial pane load exactly once."""
        if self._preload_started:
            return
        self._preload_started = True
        queued = self._deferred_loads
        self._deferred_loads = []
        self._run_deferred_loaders(queued)

    def _run_deferred_loaders(
        self, queued: list[tuple[str, Callable[[], None]]]
    ) -> None:
        """Run deferred loaders, tolerating panes torn down during shutdown."""
        for _section, loader in queued:
            try:
                loader()
            except NoMatches:
                # The app is closing and the pane's children are gone.
                continue

    def _flush_deferred_section(self, section: str) -> None:
        """Start this section's queued loads now (early tab switch).

        Args:
            section: Tab section being activated.
        """
        remaining: list[tuple[str, Callable[[], None]]] = []
        flush: list[tuple[str, Callable[[], None]]] = []
        for queued_section, loader in self._deferred_loads:
            if queued_section == section:
                flush.append((queued_section, loader))
            else:
                remaining.append((queued_section, loader))
        self._deferred_loads = remaining
        self._run_deferred_loaders(flush)

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
            # Auto-generation is an explicit opt-in mutation (config key),
            # so creating the file and its include here is acceptable.
            recurring_path = ensure_recurring_file(self.journal_file, create=True)
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
        # Textual can deliver TabActivated before the ContentSwitcher is
        # mounted; ignore the early event and let the default section stand.
        if not self.query("#content-switcher"):
            return
        section = event.tab.id.removeprefix("tab-")
        self.query_one("#content-switcher", ContentSwitcher).current = section
        self.query_one("#footer-bar", Static).update(
            self._footer_commands.get(section, "")
        )
        self._flush_deferred_section(section)
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
            # On an empty month the breakdown section is hidden; focus the
            # pane itself so its period-navigation bindings stay reachable.
            if self.query_one("#summary-breakdown").display:
                self.query_one("#summary-breakdown-table", DataTable).focus()
            else:
                self.query_one(SummaryPane).focus()
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

    def _refresh_pane(self, section: str, period_only: bool = False) -> None:
        """Refresh a single pane by name.

        Args:
            section: Tab section to refresh.
            period_only: When True, only reload the period-dependent parts
                (the Summary keeps its all-time sections untouched).
        """
        if section == "summary":
            pane = self.query_one(SummaryPane)
            if period_only:
                pane.reload_month()
            else:
                pane._load_static_data()
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

    def action_period_presets(self) -> None:
        """Open the period presets menu and apply the chosen selection."""
        from hledger_textual.screens.period_presets import PeriodPresetsModal

        def on_result(selection) -> None:
            if selection is not None:
                self.period_selection = selection

        self.push_screen(PeriodPresetsModal(), callback=on_result)

    def action_save_period_view(self) -> None:
        """Save the current period selection as a named view."""
        from hledger_textual.screens.save_period_view import SavePeriodViewModal

        current = self.period_selection
        expr = current.period_expr if current is not None else ""
        self.push_screen(SavePeriodViewModal(current_expr=expr))

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Gate actions on app state.

        - ``sync`` is disabled when no backend is configured.
        - ``command_palette`` is disabled while the import wizard is open:
          the wizard binds Ctrl+P to "previous step", and the app-level
          palette binding (priority) would otherwise swallow the key
          before the modal screen ever sees it.
        """
        if action == "sync":
            if self.read_only:
                return None  # a download could rewrite the journal
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
        if backend is None or self.read_only:
            if self.read_only:
                self.notify(
                    "Read-only mode: sync is disabled", severity="warning", timeout=5
                )
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
