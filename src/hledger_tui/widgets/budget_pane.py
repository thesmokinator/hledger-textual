"""Budget pane widget with CRUD, period navigation, and color-coded table."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import DataTable, Input, Static

from hledger_tui.budget import (
    BudgetError,
    add_budget_rule,
    delete_budget_rule,
    ensure_budget_file,
    parse_budget_rules,
    update_budget_rule,
)
from hledger_tui.hledger import HledgerError, load_budget_report
from hledger_tui.models import BudgetRow, BudgetRule
from hledger_tui.widgets import distribute_column_widths
from hledger_tui.widgets.pane_toolbar import PaneToolbar


class BudgetPane(Widget):
    """Widget showing budget rules with actual vs budget comparison."""

    BINDINGS = [
        Binding("a", "add", "Add", show=True, priority=True),
        Binding("e", "edit", "Edit", show=True, priority=True),
        Binding("enter", "edit", "Edit", show=False),
        Binding("d", "delete", "Delete", show=True, priority=True),
        Binding("slash", "filter", "Filter", show=True, priority=True),
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("escape", "dismiss_filter", "Dismiss filter", show=False),
        Binding("left,h", "prev_month", "Prev month", show=False, priority=True),
        Binding("right,l", "next_month", "Next month", show=False, priority=True),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    def __init__(self, journal_file: Path, **kwargs) -> None:
        """Initialize the pane.

        Args:
            journal_file: Path to the hledger journal file.
        """
        super().__init__(**kwargs)
        self.journal_file = journal_file
        self._budget_path: Path | None = None
        self._rules: list[BudgetRule] = []
        self._budget_rows: list[BudgetRow] = []
        self._current_month: date = date.today().replace(day=1)
        self.filter_text: str = ""

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

        yield DataTable(id="budget-table")

    _BUDGET_FIXED = {1: 14, 2: 14, 3: 14, 4: 10}

    def on_mount(self) -> None:
        """Set up the DataTable and load budget data."""
        table = self.query_one("#budget-table", DataTable)
        table.cursor_type = "row"
        table.add_column("Account", width=20)
        table.add_column("Budget", width=self._BUDGET_FIXED[1])
        table.add_column("Actual", width=self._BUDGET_FIXED[2])
        table.add_column("Remaining", width=self._BUDGET_FIXED[3])
        table.add_column("% Used", width=self._BUDGET_FIXED[4])
        self._load_budget_data()
        table.focus()

    def on_show(self) -> None:
        """Restore focus to the table when the pane becomes visible."""
        self.query_one("#budget-table", DataTable).focus()

    def on_resize(self) -> None:
        """Recalculate column widths when the pane is resized."""
        table = self.query_one("#budget-table", DataTable)
        distribute_column_widths(table, self._BUDGET_FIXED)

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
            self._rules = parse_budget_rules(self._budget_path)
        except BudgetError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )
            self._rules = []

        try:
            self._budget_rows = load_budget_report(
                self.journal_file, self._period_string()
            )
        except HledgerError:
            self._budget_rows = []

        self.app.call_from_thread(self._update_table)

    def _update_table(self) -> None:
        """Refresh the DataTable with current budget data."""
        table = self.query_one("#budget-table", DataTable)
        table.clear()

        self.query_one("#period-label", Static).update(self._period_label())

        if not self._rules:
            table.add_row(
                "No budget rules defined. Press [a] to add one.",
                "", "", "", "",
            )
            return

        # Build lookup from budget report
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

            # Format values
            budget_str = f"{commodity}{budget_amount:.2f}"
            actual_str = f"{commodity}{actual_amount:.2f}"

            # Color-coded remaining and usage
            if usage > 100:
                remaining_str = f"[red]-{commodity}{abs(remaining):.2f}[/red]"
                usage_str = f"[red]{usage:.0f}%[/red]"
            elif usage >= 75:
                remaining_str = f"[yellow]{commodity}{remaining:.2f}[/yellow]"
                usage_str = f"[yellow]{usage:.0f}%[/yellow]"
            else:
                remaining_str = f"[green]{commodity}{remaining:.2f}[/green]"
                usage_str = f"[green]{usage:.0f}%[/green]"

            table.add_row(
                rule.account,
                budget_str,
                actual_str,
                remaining_str,
                usage_str,
                key=rule.account,
            )

    def _get_selected_rule(self) -> BudgetRule | None:
        """Return the BudgetRule for the currently highlighted row."""
        table = self.query_one("#budget-table", DataTable)
        if table.row_count == 0:
            return None

        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        account = row_key.value if row_key else None
        if not account:
            return None

        for rule in self._rules:
            if rule.account == account:
                return rule
        return None

    # --- Actions ---

    def action_add(self) -> None:
        """Open the form to add a new budget rule."""
        from hledger_tui.screens.budget_form import BudgetFormScreen

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

        from hledger_tui.screens.budget_form import BudgetFormScreen

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

        from hledger_tui.screens.budget_delete_confirm import BudgetDeleteConfirmModal

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
        month = self._current_month.month - 1
        year = self._current_month.year
        if month < 1:
            month = 12
            year -= 1
        self._current_month = self._current_month.replace(year=year, month=month)
        self._load_budget_data()

    def action_next_month(self) -> None:
        """Navigate to the next month."""
        month = self._current_month.month + 1
        year = self._current_month.year
        if month > 12:
            month = 1
            year += 1
        self._current_month = self._current_month.replace(year=year, month=month)
        self._load_budget_data()

    def action_cursor_down(self) -> None:
        """Move cursor down in the table."""
        self.query_one("#budget-table", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up in the table."""
        self.query_one("#budget-table", DataTable).action_cursor_up()

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

    def _reload(self) -> None:
        """Reload budget data after a mutation."""
        self._load_budget_data()
