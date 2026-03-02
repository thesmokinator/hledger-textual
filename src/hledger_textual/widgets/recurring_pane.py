"""Recurring transactions pane widget with CRUD, generation, and filtering."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import DataTable, Input, Static

from hledger_textual.journal import JournalError, append_transaction
from hledger_textual.recurring import (
    RecurringError,
    add_recurring_rule,
    delete_recurring_rule,
    ensure_recurring_file,
    parse_recurring_rules,
    update_last_generated,
    update_recurring_rule,
)
from hledger_textual.recurring_engine import (
    build_transaction_from_rule,
    compute_next_due_date,
    find_pending_generations,
)
from hledger_textual.models import RecurringRule
from hledger_textual.widgets import distribute_column_widths
from hledger_textual.widgets.pane_toolbar import PaneToolbar


class RecurringPane(Widget):
    """Widget showing recurring transaction rules with generation support."""

    BINDINGS = [
        Binding("a", "add", "Add", show=True, priority=True),
        Binding("e", "edit", "Edit", show=True, priority=True),
        Binding("enter", "edit", "Edit", show=False),
        Binding("d", "delete", "Delete", show=True, priority=True),
        Binding("g", "generate", "Generate", show=True, priority=True),
        Binding("slash", "filter", "Filter", show=True, priority=True),
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("escape", "dismiss_filter", "Dismiss filter", show=False),
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
        self._recurring_path: Path | None = None
        self._rules: list[RecurringRule] = []
        self.filter_text: str = ""

    def compose(self) -> ComposeResult:
        """Create the pane layout."""
        with PaneToolbar():
            with Horizontal(id="recurring-toolbar-content"):
                yield Static("Recurring Transactions", id="recurring-title")

            with Horizontal(classes="filter-bar"):
                yield Input(
                    placeholder="Filter by description...",
                    id="recurring-filter-input",
                    disabled=True,
                )

        yield DataTable(id="recurring-table")

    _RECURRING_FIXED = {1: 16, 2: 14, 3: 14, 4: 12}

    def on_mount(self) -> None:
        """Set up the DataTable and load data."""
        table = self.query_one("#recurring-table", DataTable)
        table.cursor_type = "row"
        table.add_column("Description", width=20)
        table.add_column("Period", width=self._RECURRING_FIXED[1])
        table.add_column("Next Due", width=self._RECURRING_FIXED[2])
        table.add_column("Last Gen", width=self._RECURRING_FIXED[3])
        table.add_column("Status", width=self._RECURRING_FIXED[4])
        self._load_recurring_data()
        table.focus()

    def on_show(self) -> None:
        """Restore focus to the table when the pane becomes visible."""
        self.query_one("#recurring-table", DataTable).focus()

    def on_resize(self) -> None:
        """Recalculate column widths when the pane is resized."""
        table = self.query_one("#recurring-table", DataTable)
        distribute_column_widths(table, self._RECURRING_FIXED)

    @work(thread=True, exclusive=True)
    def _load_recurring_data(self) -> None:
        """Load recurring rules from file."""
        try:
            self._recurring_path = ensure_recurring_file(self.journal_file)
            self._rules = parse_recurring_rules(self._recurring_path)
        except RecurringError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )
            self._rules = []

        self.app.call_from_thread(self._update_table)

    def _update_table(self) -> None:
        """Refresh the DataTable with current recurring rules."""
        table = self.query_one("#recurring-table", DataTable)
        table.clear()

        if not self._rules:
            table.add_row(
                "No recurring rules defined. Press [a] to add one.",
                "", "", "", "",
            )
            return

        today = date.today()

        for rule in self._rules:
            if self.filter_text and self.filter_text.lower() not in rule.description.lower():
                continue

            # Compute next due date
            next_due = compute_next_due_date(
                rule.period_expr, rule.last_generated, reference_date=today
            )

            next_due_str = next_due.isoformat() if next_due else "-"
            last_gen_str = rule.last_generated or "Never"

            if next_due:
                status_str = "[green]Pending[/green]"
            else:
                status_str = "[dim]Up to date[/dim]"

            table.add_row(
                rule.description,
                rule.period_expr,
                next_due_str,
                last_gen_str,
                status_str,
                key=rule.rule_id,
            )

    def _get_selected_rule(self) -> RecurringRule | None:
        """Return the RecurringRule for the currently highlighted row."""
        table = self.query_one("#recurring-table", DataTable)
        if table.row_count == 0:
            return None

        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        rule_id = row_key.value if row_key else None
        if not rule_id:
            return None

        for rule in self._rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    # --- Actions ---

    def action_add(self) -> None:
        """Open the form to add a new recurring rule."""
        from hledger_textual.screens.recurring_form import RecurringFormScreen

        def on_save(result: RecurringRule | None) -> None:
            if result is not None:
                self._do_add(result)

        self.app.push_screen(
            RecurringFormScreen(journal_file=self.journal_file),
            callback=on_save,
        )

    def action_edit(self) -> None:
        """Open the form to edit the selected recurring rule."""
        rule = self._get_selected_rule()
        if not rule:
            return

        from hledger_textual.screens.recurring_form import RecurringFormScreen

        old_rule_id = rule.rule_id

        def on_save(result: RecurringRule | None) -> None:
            if result is not None:
                self._do_update(old_rule_id, result)

        self.app.push_screen(
            RecurringFormScreen(journal_file=self.journal_file, rule=rule),
            callback=on_save,
        )

    def action_delete(self) -> None:
        """Delete the selected recurring rule (with confirmation)."""
        rule = self._get_selected_rule()
        if not rule:
            return

        from hledger_textual.screens.recurring_delete_confirm import RecurringDeleteConfirmModal

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._do_delete(rule.rule_id)

        self.app.push_screen(
            RecurringDeleteConfirmModal(rule),
            callback=on_confirm,
        )

    def action_generate(self) -> None:
        """Generate pending recurring transactions."""
        self._check_and_generate()

    def action_refresh(self) -> None:
        """Reload recurring data."""
        self._load_recurring_data()
        self.notify("Refreshed", timeout=2)

    def action_filter(self) -> None:
        """Show/focus the filter input."""
        self.query_one("#recurring-toolbar-content").add_class("hidden")
        filter_bar = self.query_one(".filter-bar")
        filter_bar.add_class("visible")
        filter_input = self.query_one("#recurring-filter-input", Input)
        filter_input.disabled = False
        filter_input.focus()

    def action_dismiss_filter(self) -> None:
        """Hide the filter input and clear the filter."""
        filter_bar = self.query_one(".filter-bar")
        if filter_bar.has_class("visible"):
            filter_bar.remove_class("visible")
            filter_input = self.query_one("#recurring-filter-input", Input)
            filter_input.value = ""
            filter_input.disabled = True
            self.filter_text = ""
            self.query_one("#recurring-toolbar-content").remove_class("hidden")
            self._update_table()
            self.query_one("#recurring-table", DataTable).focus()

    def action_cursor_down(self) -> None:
        """Move cursor down in the table."""
        self.query_one("#recurring-table", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up in the table."""
        self.query_one("#recurring-table", DataTable).action_cursor_up()

    # --- Event handlers ---

    @on(Input.Changed, "#recurring-filter-input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        """Filter recurring rules as the user types."""
        self.filter_text = event.value
        self._update_table()

    # --- Generation flow ---

    @work(thread=True)
    def _check_and_generate(self) -> None:
        """Check for pending generations and show confirmation dialog."""
        if not self._recurring_path:
            return

        rules = parse_recurring_rules(self._recurring_path)
        pending = find_pending_generations(rules)

        if not pending:
            self.app.call_from_thread(
                self.notify, "All recurring transactions are up to date", timeout=3
            )
            return

        self.app.call_from_thread(self._show_generate_dialog, pending)

    def _show_generate_dialog(
        self,
        pending: list[tuple[RecurringRule, list]],
    ) -> None:
        """Show the generation confirmation dialog."""
        from hledger_textual.screens.recurring_generate import RecurringGenerateScreen

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._do_generate(pending)

        self.app.push_screen(
            RecurringGenerateScreen(pending),
            callback=on_confirm,
        )

    @work(thread=True)
    def _do_generate(
        self,
        pending: list[tuple[RecurringRule, list]],
    ) -> None:
        """Generate transactions and update last_generated dates."""
        if not self._recurring_path:
            return

        generated_count = 0
        try:
            for rule, dates in pending:
                for target_date in dates:
                    txn = build_transaction_from_rule(rule, target_date)
                    append_transaction(self.journal_file, txn)
                    generated_count += 1

                # Update last_generated to the latest date
                latest = max(dates)
                update_last_generated(
                    self._recurring_path,
                    rule.rule_id,
                    latest.isoformat(),
                    self.journal_file,
                )

            self.app.call_from_thread(self._reload)
            self.app.call_from_thread(
                self.notify,
                f"Generated {generated_count} transaction{'s' if generated_count != 1 else ''}",
                timeout=3,
            )
        except (RecurringError, JournalError) as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    # --- Mutation helpers ---

    @work(thread=True)
    def _do_add(self, rule: RecurringRule) -> None:
        """Add a recurring rule and reload."""
        if not self._recurring_path:
            return
        try:
            add_recurring_rule(self._recurring_path, rule, self.journal_file)
            self.app.call_from_thread(self._reload)
            self.app.call_from_thread(self.notify, "Recurring rule added", timeout=3)
        except RecurringError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    @work(thread=True)
    def _do_update(self, old_rule_id: str, new_rule: RecurringRule) -> None:
        """Update a recurring rule and reload."""
        if not self._recurring_path:
            return
        try:
            update_recurring_rule(
                self._recurring_path, old_rule_id, new_rule, self.journal_file
            )
            self.app.call_from_thread(self._reload)
            self.app.call_from_thread(self.notify, "Recurring rule updated", timeout=3)
        except RecurringError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    @work(thread=True)
    def _do_delete(self, rule_id: str) -> None:
        """Delete a recurring rule and reload."""
        if not self._recurring_path:
            return
        try:
            delete_recurring_rule(self._recurring_path, rule_id, self.journal_file)
            self.app.call_from_thread(self._reload)
            self.app.call_from_thread(self.notify, "Recurring rule deleted", timeout=3)
        except RecurringError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    def _reload(self) -> None:
        """Reload recurring data after a mutation."""
        self._load_recurring_data()
