"""Budget pane widget with CRUD, period navigation, and color-coded table."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from rich.text import Text
from textual.widgets import DataTable, Input, Static

from hledger_textual.dateutil import next_month as _next_month
from hledger_textual.dateutil import prev_month as _prev_month
from hledger_textual.budget import (
    BudgetError,
    add_budget_rule,
    delete_budget_rule,
    ensure_budget_file,
    parse_budget_rules,
    update_budget_rule,
)
from hledger_textual.cache import HledgerCache
from hledger_textual.config import load_budget_alert_threshold
from hledger_textual.hledger import HledgerError, load_budget_report
from hledger_textual.models import BudgetRow, BudgetRule
from hledger_textual.widgets.empty_state import EmptyState
from hledger_textual.widgets.formatting import fmt_amount
from hledger_textual.widgets.pane_mixin import DataTablePaneMixin
from hledger_textual.widgets.pane_toolbar import PaneToolbar


class BudgetPane(DataTablePaneMixin, Widget):
    """Widget showing budget rules with actual vs budget comparison."""

    _main_table_id = "budget-table"
    _fixed_column_widths = {1: 14, 2: 14, 3: 14, 4: 10}

    BINDINGS = [
        Binding("a", "add", "Add", show=True, priority=True),
        Binding("e", "edit", "Edit", show=True, priority=True),
        Binding("enter", "edit", "Edit", show=False),
        Binding("d", "delete", "Delete", show=True, priority=True),
        Binding("slash", "filter", "Filter", show=True, priority=True),
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("x", "export", "Export", show=False, priority=True),
        Binding("o", "overview", "Overview", show=True, priority=True),
        Binding("escape", "dismiss_filter", "Dismiss filter", show=False),
        Binding("left,h", "prev_month", "Prev month", show=False, priority=True),
        Binding("right,l", "next_month", "Next month", show=False, priority=True),
        Binding("t", "today_month", "Today", show=False, priority=True),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    def __init__(self, journal_file: Path, cache: HledgerCache | None = None, **kwargs) -> None:
        """Initialize the pane.

        Args:
            journal_file: Path to the hledger journal file.
            cache: Optional cache instance to avoid repeated subprocess calls.
        """
        super().__init__(**kwargs)
        self.journal_file = journal_file
        self._cache = cache
        self._budget_path: Path | None = None
        self._rules: list[BudgetRule] = []
        self._budget_rows: list[BudgetRow] = []
        self._current_month: date = date.today().replace(day=1)
        self.filter_text: str = ""
        self._alerted_accounts: set[str] = set()

    def compose(self) -> ComposeResult:
        """Create the pane layout."""
        with PaneToolbar():
            with Horizontal(id="period-nav", classes="period-nav"):
                yield Static("\u25c4 Prev", id="btn-prev-month", classes="period-btn")
                yield Static(self._period_label(), id="period-label")
                yield Static("Next \u25ba", id="btn-next-month", classes="period-btn")

            with Horizontal(classes="filter-bar"):
                yield Input(
                    placeholder="Filter by account name...",
                    id="budget-filter-input",
                    disabled=True,
                )

        yield EmptyState(
            "No budgets configured",
            "Press `a` to create one.",
            icon="📭",
            id="budget-empty-state",
        )
        yield DataTable(id="budget-table")

    def on_mount(self) -> None:
        """Set up the DataTable and load budget data."""
        table = self._get_main_table()
        table.cursor_type = "row"
        table.add_column("Account", width=20)
        table.add_column("Budget", width=self._fixed_column_widths[1])
        table.add_column("Actual", width=self._fixed_column_widths[2])
        table.add_column("Remaining", width=self._fixed_column_widths[3])
        table.add_column("% Used", width=self._fixed_column_widths[4])
        self._set_empty_state_visible(False)
        self._load_budget_data()
        table.focus()

    def _period_label(self) -> str:
        """Return the formatted period label for the current month."""
        return self._current_month.strftime("%B %Y")

    def _period_string(self) -> str:
        """Return the period string for hledger (YYYY-MM)."""
        return self._current_month.strftime("%Y-%m")

    @work(thread=True, exclusive=True)
    def _load_budget_data(self) -> None:
        """Load budget rules and actual spending data."""
        try:
            self._budget_path = ensure_budget_file(self.journal_file)
            self._rules = sorted(
                parse_budget_rules(self._budget_path),
                key=lambda r: r.account.lower(),
            )
        except BudgetError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )
            self._rules = []

        try:
            self._budget_rows = load_budget_report(
                self.journal_file, self._period_string(), cache=self._cache
            )
        except HledgerError:
            self._budget_rows = []

        self.app.call_from_thread(self._update_table)

    def _update_table(self) -> None:
        """Refresh the DataTable with current budget data, grouped by category."""
        table = self.query_one("#budget-table", DataTable)
        table.clear()

        self.query_one("#period-label", Static).update(self._period_label())

        if not self._rules:
            self._set_empty_state_visible(True)
            return
        self._set_empty_state_visible(False)

        # Build lookup from budget report
        actuals: dict[str, BudgetRow] = {
            row.account: row for row in self._budget_rows
        }

        # Apply filter and group rules by category
        visible = [
            r for r in self._rules
            if not self.filter_text or self.filter_text.lower() in r.account.lower()
        ]

        categorized: dict[str, list[BudgetRule]] = {}
        uncategorized: list[BudgetRule] = []
        for rule in visible:
            if rule.category:
                categorized.setdefault(rule.category, []).append(rule)
            else:
                uncategorized.append(rule)

        has_categories = bool(categorized)
        alert_threshold = load_budget_alert_threshold()

        def _render_rule(rule: BudgetRule) -> None:
            budget_amount = rule.amount.quantity
            commodity = rule.amount.commodity
            report_row = actuals.get(rule.account)

            actual_amount = report_row.actual if report_row else Decimal("0")
            remaining = budget_amount - actual_amount
            usage = float(actual_amount / budget_amount * 100) if budget_amount else 0.0

            budget_str = fmt_amount(budget_amount, commodity)
            actual_str = fmt_amount(actual_amount, commodity)

            if usage > 100:
                remaining_str = f"[red]{fmt_amount(remaining, commodity)}[/red]"
                usage_str = f"[red]{usage:.0f}%[/red]"
            elif usage >= 75:
                remaining_str = f"[yellow]{fmt_amount(remaining, commodity)}[/yellow]"
                usage_str = f"[yellow]{usage:.0f}%[/yellow]"
            else:
                remaining_str = f"[green]{fmt_amount(remaining, commodity)}[/green]"
                usage_str = f"[green]{usage:.0f}%[/green]"

            table.add_row(
                Text(rule.account),
                budget_str,
                actual_str,
                remaining_str,
                usage_str,
                key=rule.account,
            )

            # Budget alerts
            if (
                alert_threshold is not None
                and usage >= alert_threshold
                and rule.account not in self._alerted_accounts
            ):
                self._alerted_accounts.add(rule.account)
                self.notify(
                    f"{rule.account}: {usage:.0f}% of budget used",
                    severity="warning",
                    timeout=6,
                )

        # Render categorized groups first (sorted by category name)
        for cat in sorted(categorized):
            table.add_row(
                Text(f"\u2500\u2500 {cat} \u2500\u2500", style="dim bold"),
                "", "", "", "",
                key=f"__cat__{cat}",
            )
            for rule in categorized[cat]:
                _render_rule(rule)

        # Render uncategorized rules (no header when everything is uncategorized)
        if uncategorized and has_categories:
            table.add_row(
                Text("\u2500\u2500 Other \u2500\u2500", style="dim bold"),
                "", "", "", "",
                key="__cat__other__",
            )
        for rule in uncategorized:
            _render_rule(rule)

    def _set_empty_state_visible(self, visible: bool) -> None:
        """Toggle the no-budget message and DataTable visibility."""
        self.query_one("#budget-empty-state", EmptyState).display = visible
        self.query_one("#budget-table", DataTable).display = not visible

    def _get_selected_rule(self) -> BudgetRule | None:
        """Return the BudgetRule for the currently highlighted row.

        Returns ``None`` if the cursor is on a category header row.
        """
        table = self.query_one("#budget-table", DataTable)
        if table.row_count == 0:
            return None

        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        account = row_key.value if row_key else None
        if not account or account.startswith("__cat__"):
            return None

        for rule in self._rules:
            if rule.account == account:
                return rule
        return None

    # --- Actions ---

    def action_add(self) -> None:
        """Open the form to add a new budget rule."""
        from hledger_textual.screens.budget_form import BudgetFormScreen

        def on_save(result: BudgetRule | None) -> None:
            if result is not None:
                self._do_add(result)

        self.app.push_screen(
            BudgetFormScreen(journal_file=self.journal_file),
            callback=on_save,
        )

    def action_edit(self) -> None:
        """Open the form to edit the selected budget rule."""
        rule = self._get_selected_rule()
        if not rule:
            return

        from hledger_textual.screens.budget_form import BudgetFormScreen

        old_account = rule.account

        def on_save(result: BudgetRule | None) -> None:
            if result is not None:
                self._do_update(old_account, result)

        self.app.push_screen(
            BudgetFormScreen(journal_file=self.journal_file, rule=rule),
            callback=on_save,
        )

    def action_delete(self) -> None:
        """Delete the selected budget rule (with confirmation)."""
        rule = self._get_selected_rule()
        if not rule:
            return

        from hledger_textual.screens.budget_delete_confirm import BudgetDeleteConfirmModal

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._do_delete(rule.account)

        self.app.push_screen(
            BudgetDeleteConfirmModal(rule),
            callback=on_confirm,
        )

    def action_refresh(self) -> None:
        """Reload budget data."""
        self._load_budget_data()
        self.notify("Refreshed", timeout=2)

    def action_filter(self) -> None:
        """Show/focus the filter input and hide period nav."""
        self.query_one("#period-nav").add_class("hidden")
        filter_bar = self.query_one(".filter-bar")
        filter_bar.add_class("visible")
        filter_input = self.query_one("#budget-filter-input", Input)
        filter_input.disabled = False
        filter_input.focus()

    def action_dismiss_filter(self) -> None:
        """Hide the filter input, restore period nav, and clear the filter."""
        filter_bar = self.query_one(".filter-bar")
        if filter_bar.has_class("visible"):
            filter_bar.remove_class("visible")
            filter_input = self.query_one("#budget-filter-input", Input)
            filter_input.value = ""
            filter_input.disabled = True
            self.filter_text = ""
            self.query_one("#period-nav").remove_class("hidden")
            self._update_table()
            self.query_one("#budget-table", DataTable).focus()

    def action_prev_month(self) -> None:
        """Navigate to the previous month."""
        self._current_month = _prev_month(self._current_month)
        self._alerted_accounts.clear()
        self._load_budget_data()

    def action_next_month(self) -> None:
        """Navigate to the next month."""
        self._current_month = _next_month(self._current_month)
        self._alerted_accounts.clear()
        self._load_budget_data()

    def action_today_month(self) -> None:
        """Jump to the current month."""
        self._current_month = date.today().replace(day=1)
        self._alerted_accounts.clear()
        self._load_budget_data()

    def action_overview(self) -> None:
        """Open the multi-period budget overview screen."""
        from hledger_textual.screens.budget_overview import BudgetOverviewScreen

        self.app.push_screen(BudgetOverviewScreen(self.journal_file, self._rules))

    # --- Event handlers ---

    @on(Input.Changed, "#budget-filter-input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        """Filter budget rules as the user types."""
        self.filter_text = event.value
        self._update_table()

    # --- Mutation helpers ---

    @work(thread=True)
    def _do_add(self, rule: BudgetRule) -> None:
        """Add a budget rule and reload."""
        if not self._budget_path:
            return
        try:
            add_budget_rule(self._budget_path, rule, self.journal_file)
            self.app.call_from_thread(self._reload)
            self.app.call_from_thread(self.notify, "Budget rule added", timeout=3)
        except BudgetError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    @work(thread=True)
    def _do_update(self, old_account: str, new_rule: BudgetRule) -> None:
        """Update a budget rule and reload."""
        if not self._budget_path:
            return
        try:
            update_budget_rule(
                self._budget_path, old_account, new_rule, self.journal_file
            )
            self.app.call_from_thread(self._reload)
            self.app.call_from_thread(self.notify, "Budget rule updated", timeout=3)
        except BudgetError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    @work(thread=True)
    def _do_delete(self, account: str) -> None:
        """Delete a budget rule and reload."""
        if not self._budget_path:
            return
        try:
            delete_budget_rule(self._budget_path, account, self.journal_file)
            self.app.call_from_thread(self._reload)
            self.app.call_from_thread(self.notify, "Budget rule deleted", timeout=3)
        except BudgetError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    def get_export_data(self):
        """Return an ExportData with budget rows for export.

        Returns:
            An ExportData instance with Account, Budget, Actual, Remaining,
            and % Used columns.
        """
        from hledger_textual.export import ExportData

        headers = ["Account", "Budget", "Actual", "Remaining", "% Used"]
        rows: list[list[str]] = []

        actuals: dict[str, BudgetRow] = {
            row.account: row for row in self._budget_rows
        }

        for rule in self._rules:
            if self.filter_text and self.filter_text.lower() not in rule.account.lower():
                continue

            budget_amount = rule.amount.quantity
            commodity = rule.amount.commodity
            report_row = actuals.get(rule.account)

            actual_amount = report_row.actual if report_row else 0
            remaining = budget_amount - actual_amount
            usage = float(actual_amount / budget_amount * 100) if budget_amount else 0.0

            rows.append([
                rule.account,
                f"{commodity}{budget_amount:.2f}",
                f"{commodity}{actual_amount:.2f}",
                f"{commodity}{remaining:.2f}",
                f"{usage:.0f}%",
            ])

        return ExportData(
            title=f"Budget {self._period_label()}",
            headers=headers,
            rows=rows,
            pane_name="budget",
        )

    def _reload(self) -> None:
        """Reload budget data after a mutation."""
        self._load_budget_data()
