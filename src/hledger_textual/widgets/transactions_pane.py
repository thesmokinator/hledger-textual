"""Transactions list pane widget (full CRUD)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.widget import Widget

from hledger_textual.cache import HledgerCache
from hledger_textual.config import resolve_default_commodity
from hledger_textual.hledger import HledgerError, load_period_summary
from hledger_textual.models import Transaction, TransactionStatus
from hledger_textual.widgets.period_summary_cards import PeriodSummaryCards
from hledger_textual.widgets.transactions_table import TransactionsTable


class TransactionsPane(Widget):
    """Widget showing all transactions with add / edit / delete actions.

    Composes a :class:`~hledger_textual.widgets.transactions_table.TransactionsTable`
    for the shared filter bar and DataTable, and adds journal-mutation bindings
    on top.  Compact summary cards above the table show the current month's
    Income / Expenses / Net and update when the user navigates months.
    """

    BINDINGS = [
        Binding("a", "add", "Add", show=True, priority=True),
        Binding("e", "edit", "Edit", show=True, priority=True),
        Binding("enter", "edit", "Edit", show=False),
        Binding("d", "delete", "Delete", show=True, priority=True),
        Binding("c", "clone", "Clone", show=True, priority=True),
        Binding("m", "move", "Move", show=True, priority=True),
        Binding("slash", "filter", "Search", show=True, priority=True),
        Binding("f", "saved_filters", "Filters", show=False, priority=True),
        Binding("ctrl+s", "save_filter", "Save Filter", show=False, priority=True),
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("escape", "dismiss_filter", "Dismiss filter", show=False),
        Binding("left", "prev_month", "Previous month", show=False, priority=True),
        Binding("right", "next_month", "Next month", show=False, priority=True),
        Binding("t", "today_month", "Today", show=False, priority=True),
        Binding("*", "toggle_cleared", "Toggle cleared", show=False, priority=True),
        Binding(
            "exclamation_mark",
            "toggle_pending",
            "Toggle pending",
            show=False,
            priority=True,
        ),
        Binding("x", "export", "Export", show=False, priority=True),
        Binding("i", "import_csv", "Import", show=True, priority=True),
    ]

    def __init__(
        self,
        journal_file: Path,
        cache: HledgerCache | None = None,
        **kwargs,
    ) -> None:
        """Initialise the pane.

        Args:
            journal_file: Path to the hledger journal file.
            cache: Optional cache for hledger results.
        """
        super().__init__(**kwargs)
        self.journal_file = journal_file
        self._cache = cache

    def compose(self) -> ComposeResult:
        """Render compact summary cards and the shared transactions table."""
        yield PeriodSummaryCards(compact=True, id="txn-summary-cards")
        yield TransactionsTable(self.journal_file, cache=self._cache)

    def on_mount(self) -> None:
        """Load the summary for the initial month."""
        self._load_summary(self._table.current_month)

    def on_show(self) -> None:
        """Re-focus the table when the pane becomes visible."""
        self.query_one(TransactionsTable).on_show()

    @property
    def _table(self) -> TransactionsTable:
        return self.query_one(TransactionsTable)

    # ------------------------------------------------------------------
    # Month-change handler
    # ------------------------------------------------------------------

    def on_transactions_table_month_changed(
        self, event: TransactionsTable.MonthChanged
    ) -> None:
        """Reload summary cards when the displayed month changes."""
        self._load_summary(event.month)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Silently reload transactions and summary (no notification)."""
        self._table.reload()
        self._load_summary(self._table.current_month)

    def action_refresh(self) -> None:
        """Reload transactions and summary from the journal."""
        self._table.do_refresh()
        self._load_summary(self._table.current_month)

    def action_filter(self) -> None:
        """Show the filter panel."""
        self._table.show_filter()

    def action_dismiss_filter(self) -> None:
        """Hide the search bar and reset all filters."""
        self._table.dismiss_filter()

    def action_saved_filters(self) -> None:
        """Open the saved filters modal to browse and apply filters."""
        from hledger_textual.screens.saved_filters import SavedFiltersModal

        def on_select(query: str | None) -> None:
            if query:
                self._table.apply_saved_filter(query)

        self.app.push_screen(SavedFiltersModal(), callback=on_select)

    def action_save_filter(self) -> None:
        """Save the current search filter with a user-chosen name."""
        from hledger_textual.screens.save_filter import SaveFilterModal

        query = self._table.current_search_query
        if not query:
            self.notify("No active filter to save", severity="warning", timeout=3)
            return
        self.app.push_screen(SaveFilterModal(current_query=query))

    def action_prev_month(self) -> None:
        """Navigate to the previous month."""
        self._table.prev_month()

    def action_next_month(self) -> None:
        """Navigate to the next month."""
        self._table.next_month()

    def action_today_month(self) -> None:
        """Jump to the current month."""
        self._table.today_month()

    def action_add(self) -> None:
        """Open the form to add a new transaction."""
        from hledger_textual.screens.transaction_form import TransactionFormScreen

        def on_save(result: Transaction | None) -> None:
            if result is not None:
                self._do_append(result)

        self.app.push_screen(
            TransactionFormScreen(journal_file=self.journal_file),
            callback=on_save,
        )

    def action_edit(self) -> None:
        """Open the form to edit the selected transaction."""
        self._table.do_edit()

    def action_delete(self) -> None:
        """Delete the selected transaction (with confirmation)."""
        self._table.do_delete()

    def action_toggle_cleared(self) -> None:
        """Toggle the cleared status of the selected transaction."""
        self._table.do_toggle_status(TransactionStatus.CLEARED)

    def action_toggle_pending(self) -> None:
        """Toggle the pending status of the selected transaction."""
        self._table.do_toggle_status(TransactionStatus.PENDING)

    def action_clone(self) -> None:
        """Clone the selected transaction with an empty date for the user to fill."""
        import dataclasses

        from hledger_textual.screens.transaction_form import TransactionFormScreen

        txn = self._table.get_selected_transaction()
        if txn is None:
            self.notify("No transaction selected", severity="warning", timeout=3)
            return

        clone = dataclasses.replace(txn, date="", index=0)

        def on_save(result: Transaction | None) -> None:
            if result is not None:
                self._do_append(result)

        self.app.push_screen(
            TransactionFormScreen(
                journal_file=self.journal_file,
                transaction=clone,
                clone=True,
            ),
            callback=on_save,
        )

    def action_move(self) -> None:
        """Show the move dialog to change the transaction date."""
        from hledger_textual.screens.move_confirm import MoveConfirmModal

        txn = self._table.get_selected_transaction()
        if txn is None:
            self.notify("No transaction selected", severity="warning", timeout=3)
            return

        def on_confirm(new_date: str | None) -> None:
            if new_date is not None:
                self._table.do_move_to_date(txn, new_date)

        self.app.push_screen(MoveConfirmModal(txn), callback=on_confirm)

    # ------------------------------------------------------------------
    # Summary loading
    # ------------------------------------------------------------------

    @work(thread=True, exclusive=True, group="txn-summary")
    def _load_summary(self, month: date) -> None:
        """Load the period summary for *month* in a background thread.

        When *month* is the current calendar month the date range is capped at
        today so that scheduled (future) transactions do not inflate the totals.
        """
        today = date.today()
        if month.year == today.year and month.month == today.month:
            end = today + timedelta(days=1)
            period = f"{month.isoformat()}..{end.isoformat()}"
        else:
            period = month.strftime("%Y-%m")
        try:
            summary = load_period_summary(
                self.journal_file,
                period,
                cache=self._cache,
                commodity=resolve_default_commodity(self.journal_file),
            )
        except HledgerError:
            summary = None

        def _apply_summary() -> None:
            # Query on the UI thread and tolerate a pane torn down between the
            # worker finishing and this callback running.
            try:
                self.query_one(PeriodSummaryCards).update_summary(summary)
            except NoMatches:
                return

        self.app.call_from_thread(_apply_summary)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def action_export(self) -> None:
        """Open the export modal with current transaction data."""
        from hledger_textual.config import load_export_dir
        from hledger_textual.export import ExportData, default_filename
        from hledger_textual.screens.export_modal import ExportModal

        txns = self._table._all_transactions
        rows = []
        for txn in txns:
            accounts = " · ".join(p.account for p in txn.postings)
            rows.append([
                txn.date,
                txn.type_indicator,
                txn.status.symbol,
                txn.description,
                accounts,
                txn.total_amount,
            ])
        data = ExportData(
            title=f"Transactions {self._table._period_label()}",
            headers=["Date", "Type", "Status", "Description", "Accounts", "Amount"],
            rows=rows,
            pane_name="transactions",
        )
        filename = default_filename("transactions", "csv")
        export_dir = str(load_export_dir())

        def on_result(result: tuple[str, str, str] | None) -> None:
            if result is not None:
                fmt, fname, directory = result
                self._run_export(data, fmt, fname, directory)

        self.app.push_screen(
            ExportModal(default_filename=filename, default_directory=export_dir),
            callback=on_result,
        )

    @work(thread=True)
    def _run_export(self, data, fmt: str, filename: str, directory: str) -> None:
        """Execute the export in a background thread."""
        from pathlib import Path

        from hledger_textual.export import export_csv, export_pdf

        export_dir = Path(directory).expanduser().resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / filename

        try:
            if fmt == "pdf":
                export_pdf(data, path)
            else:
                export_csv(data, path)
            self.app.call_from_thread(
                self.notify, f"Exported to {path}", timeout=5
            )
        except Exception as exc:
            self.app.call_from_thread(
                self.notify, f"Export failed: {exc}", severity="error", timeout=8
            )

    # ------------------------------------------------------------------
    # Mutation helpers (add is local — only needed in the main view)
    # ------------------------------------------------------------------

    @work(thread=True)
    def _do_append(self, transaction: Transaction) -> None:
        """Append a transaction to the journal and emit JournalChanged."""
        from hledger_textual.journal import JournalError, append_transaction

        try:
            append_transaction(self.journal_file, transaction)
            self.app.call_from_thread(self.notify, "Transaction added", timeout=3)
            self.app.call_from_thread(
                self._table.post_message, TransactionsTable.JournalChanged()
            )
        except JournalError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )

    # ------------------------------------------------------------------
    # CSV Import
    # ------------------------------------------------------------------

    def action_import_csv(self) -> None:
        """Start the CSV import flow: file select -> rules manager -> wizard -> preview."""
        from hledger_textual.screens.csv_file_select import CsvFileSelectModal

        def on_file_selected(csv_path: Path | None) -> None:
            if csv_path is not None:
                self._show_rules_manager(csv_path)

        self.app.push_screen(CsvFileSelectModal(), callback=on_file_selected)

    def _show_rules_manager(self, csv_path: Path) -> None:
        """Show the rules manager after CSV file selection.

        If a companion rules file exists next to the CSV (hledger convention:
        ``bank.csv`` → ``bank.csv.rules``), it is used directly without
        opening the rules manager.
        """
        from hledger_textual.csv_import import find_companion_rules
        from hledger_textual.screens.rules_manager import RulesManagerModal

        companion = find_companion_rules(csv_path)
        if companion is not None:
            self.notify(
                f"Using companion rules: {companion.name}", timeout=4
            )
            self._preview_and_import(csv_path, companion)
            return

        def on_result(result: tuple | None) -> None:
            if result is None:
                return
            action, rules_file = result
            if action == "select" and rules_file is not None:
                self._preview_and_import(csv_path, rules_file.path)
            elif action == "new":
                self._show_wizard(csv_path, existing_rules=None)
            elif action == "edit" and rules_file is not None:
                self._show_wizard(csv_path, existing_rules=rules_file)

        self.app.push_screen(
            RulesManagerModal(self.journal_file), callback=on_result
        )

    def _show_wizard(self, csv_path: Path, existing_rules=None) -> None:
        """Show the import wizard for creating/editing rules."""
        from hledger_textual.screens.import_wizard import ImportWizardScreen

        def on_wizard_result(result: tuple | None) -> None:
            if result is not None:
                csv_p, rules_p = result
                self._preview_and_import(csv_p, rules_p)

        self.app.push_screen(
            ImportWizardScreen(
                csv_path=csv_path,
                journal_file=self.journal_file,
                existing_rules=existing_rules,
            ),
            callback=on_wizard_result,
        )

    @work(thread=True)
    def _preview_and_import(self, csv_path: Path, rules_path: Path) -> None:
        """Run preview in a thread, then show preview screen for confirmation."""
        from hledger_textual.csv_import import (
            CsvImportError,
            check_duplicates,
            preview_import,
        )
        from hledger_textual.screens.import_preview import ImportPreviewScreen

        try:
            transactions = preview_import(csv_path, rules_path)
            new_txns, dupes = check_duplicates(transactions, self.journal_file)
        except CsvImportError as exc:
            self.app.call_from_thread(
                self.notify, f"Import error: {exc}", severity="error", timeout=8
            )
            return

        def show_preview() -> None:
            def on_confirm(result: list[Transaction] | None | str) -> None:
                if result == "back":
                    self._show_rules_manager(csv_path)
                elif result:
                    self._do_import(result)

            self.app.push_screen(
                ImportPreviewScreen(new_txns, len(dupes)),
                callback=on_confirm,
            )

        self.app.call_from_thread(show_preview)

    @work(thread=True)
    def _do_import(self, transactions: list[Transaction]) -> None:
        """Import confirmed transactions into the journal."""
        from hledger_textual.journal import JournalError, append_transaction

        count = 0
        for txn in transactions:
            try:
                append_transaction(self.journal_file, txn)
                count += 1
            except JournalError as exc:
                self.app.call_from_thread(
                    self.notify,
                    f"Import failed at transaction {count + 1}: {exc}",
                    severity="error",
                    timeout=8,
                )
                break

        if count > 0:
            self.app.call_from_thread(
                self.notify,
                f"Imported {count} transaction{'s' if count != 1 else ''}",
                timeout=5,
            )
            self.app.call_from_thread(
                self._table.post_message, TransactionsTable.JournalChanged()
            )
