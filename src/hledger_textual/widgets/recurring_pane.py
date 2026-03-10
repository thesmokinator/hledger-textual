"""Recurring transactions pane widget with CRUD and batch generation."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable

from hledger_textual.models import RecurringRule
from hledger_textual.recurring import (
    RecurringError,
    add_recurring_rule,
    compute_pending,
    delete_recurring_rule,
    ensure_recurring_file,
    generate_transactions,
    parse_recurring_rules,
    update_recurring_rule,
)
from hledger_textual.widgets.pane_mixin import DataTablePaneMixin


class RecurringPane(DataTablePaneMixin, Widget):
    """Widget for managing recurring transaction rules."""

    _main_table_id = "recurring-table"
    _fixed_column_widths = {0: 12, 2: 10, 3: 10}

    BINDINGS = [
        Binding("a", "add", "Add", show=True, priority=True),
        Binding("e", "edit", "Edit", show=True, priority=True),
        Binding("enter", "edit", "Edit", show=False),
        Binding("d", "delete", "Delete", show=True, priority=True),
        Binding("g", "generate", "Generate", show=True, priority=True),
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    class JournalChanged(Message):
        """Posted when recurring transactions are generated (journal mutated)."""

    def __init__(self, journal_file: Path, **kwargs) -> None:
        """Initialize the pane.

        Args:
            journal_file: Path to the hledger journal file.
        """
        super().__init__(**kwargs)
        self.journal_file = journal_file
        self._recurring_path: Path | None = None
        self._rules: list[RecurringRule] = []

    def compose(self) -> ComposeResult:
        """Create the pane layout."""
        yield DataTable(id="recurring-table")

    def on_mount(self) -> None:
        """Set up the DataTable and load recurring rules."""
        table = self._get_main_table()
        table.cursor_type = "row"
        table.add_column("Period", width=12)
        table.add_column("Description", width=20)
        table.add_column("Start", width=10)
        table.add_column("End", width=10)
        table.add_column("Postings", width=20)
        self._load_data()
        table.focus()

    @work(thread=True, exclusive=True)
    def _load_data(self) -> None:
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
        """Refresh the DataTable with current rules."""
        table = self.query_one("#recurring-table", DataTable)
        table.clear()

        if not self._rules:
            table.add_row(
                "No recurring rules. Press [a] to add one.",
                "", "", "", "",
            )
            return

        for rule in self._rules:
            postings_summary = ", ".join(
                p.account for p in rule.postings if p.account
            )
            table.add_row(
                rule.period_expr,
                rule.description,
                rule.start_date or "",
                rule.end_date or "",
                postings_summary,
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

        old_id = rule.rule_id

        def on_save(result: RecurringRule | None) -> None:
            if result is not None:
                self._do_update(old_id, result)

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
        """Compute pending transactions and open the generate preview screen."""
        if not self._rules:
            self.notify("No recurring rules defined", severity="warning", timeout=3)
            return

        today = date.today()
        pending: list[tuple[RecurringRule, list[date]]] = []

        for rule in self._rules:
            try:
                dates = compute_pending(rule, self.journal_file, today)
            except Exception:
                dates = []
            if dates:
                pending.append((rule, dates))

        if not pending:
            self.notify("No pending transactions to generate", timeout=3)
            return

        from hledger_textual.screens.recurring_generate import RecurringGenerateScreen

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._do_generate(pending)

        self.app.push_screen(
            RecurringGenerateScreen(pending),
            callback=on_confirm,
        )

    def action_refresh(self) -> None:
        """Reload recurring rules."""
        self._load_data()
        self.notify("Refreshed", timeout=2)

    # --- Mutation workers ---

    @work(thread=True)
    def _do_add(self, rule: RecurringRule) -> None:
        """Add a recurring rule and reload."""
        if not self._recurring_path:
            return
        try:
            add_recurring_rule(self._recurring_path, rule, self.journal_file)
            self.app.call_from_thread(self._load_data)
            self.app.call_from_thread(self.notify, "Recurring rule added", timeout=3)
        except RecurringError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    @work(thread=True)
    def _do_update(self, old_id: str, new_rule: RecurringRule) -> None:
        """Update a recurring rule and reload."""
        if not self._recurring_path:
            return
        try:
            update_recurring_rule(
                self._recurring_path, old_id, new_rule, self.journal_file
            )
            self.app.call_from_thread(self._load_data)
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
            self.app.call_from_thread(self._load_data)
            self.app.call_from_thread(self.notify, "Recurring rule deleted", timeout=3)
        except RecurringError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    @work(thread=True)
    def _do_generate(self, pending: list[tuple[RecurringRule, list[date]]]) -> None:
        """Generate transactions for all pending (rule, dates) pairs."""
        for rule, dates in pending:
            try:
                generate_transactions(rule, dates, self.journal_file)
            except RecurringError as exc:
                self.app.call_from_thread(
                    self.notify, str(exc), severity="error", timeout=8
                )
                return

        total = sum(len(d) for _, d in pending)
        self.app.call_from_thread(
            self.notify, f"Generated {total} transaction(s)", timeout=3
        )
        self.app.call_from_thread(self.post_message, self.JournalChanged())
