"""Reports pane widget with multi-period financial reports (IS, BS, CF)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from rich.text import Text
from textual.widgets import DataTable, Select, Static

from hledger_textual.cache import HledgerCache
from hledger_textual.error_messages import humanize_error
from hledger_textual.config import (
    load_custom_reports,
    resolve_default_commodity,
)
from hledger_textual.hledger import HledgerError, load_investment_report, load_report, run_custom_report
from hledger_textual.models import ReportData, ReportRow
from hledger_textual.widgets import distribute_column_widths
from hledger_textual.widgets.constants import (
    REPORT_LABELS,
    REPORT_PERIOD_LABELS,
    REPORT_PERIOD_RANGES,
    REPORT_TYPES,
)
from hledger_textual.widgets.empty_state import EmptyState
from hledger_textual.widgets.loading import hide_loading_overlay, show_loading_overlay
from hledger_textual.widgets.pane_mixin import DataTablePaneMixin
from hledger_textual.widgets.pane_toolbar import PaneToolbar
from hledger_textual.widgets.report_chart import extract_chart_data
from hledger_textual.widgets.reports_custom_actions import ReportsCustomActionsMixin
from hledger_textual.widgets.reports_renderer import (
    MULTI_COMMODITY_MARKER,
    build_report_rows,
    merge_investments,
)

__all__ = ["MULTI_COMMODITY_MARKER", "ReportsPane"]


class ReportsPane(ReportsCustomActionsMixin, DataTablePaneMixin, Widget):
    """Widget showing multi-period hledger financial reports."""

    _main_table_id = "reports-table"

    class CustomReportStateChanged(Message):
        """Posted when switching between built-in and custom report modes.

        The ``active`` attribute is ``True`` when a custom report is now
        displayed, ``False`` when returning to a built-in report.
        """

        def __init__(self, active: bool) -> None:
            """Initialise the message.

            Args:
                active: Whether a custom report is now active.
            """
            super().__init__()
            self.active = active

    BINDINGS = [
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("c", "toggle_chart", "Chart", show=False, priority=True),
        Binding("i", "toggle_investments", "Investments", show=False, priority=True),
        Binding("t", "toggle_tree", "Tree/Flat", show=True, priority=True),
        Binding("S", "toggle_sort_amount", "Sort amount", show=True, priority=True),
        Binding("M", "toggle_stacked_currency", "Stacked", show=True, priority=True),
        Binding("x", "export", "Export", show=False, priority=True),
        Binding("n", "new_custom_report", "New report", show=True, priority=True),
        Binding("e", "edit_custom_report", "Edit report", show=False, priority=True),
        Binding("d", "delete_custom_report", "Delete report", show=False, priority=True),
        Binding("escape", "back_to_builtin", "Back", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("h", "cursor_left", "Left", show=False),
        Binding("l", "cursor_right", "Right", show=False),
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
        self._report_type: str = "is"
        self._period_months: int = 6
        self._report_data: ReportData | None = None
        self._fixed_widths: dict[int, int] = {}
        self._show_investments: bool = False
        self._tree_mode: bool = False
        self._sort_amount: bool = False
        self._stacked_currency: bool = True
        self._custom_report_name: str | None = None
        self._period_begin: date | None = None
        self._table_rows: list[ReportRow | None] = []
        self._row_full_paths: list[str] = []

    def compose(self) -> ComposeResult:
        """Create the pane layout."""
        with PaneToolbar():
            yield Select(
                [(label, value) for label, value in REPORT_TYPES],
                value="is",
                id="report-type-select",
                allow_blank=False,
            )
            yield Select(
                [(label, value) for label, value in REPORT_PERIOD_RANGES],
                value=6,
                id="report-period-select",
                allow_blank=False,
            )
            yield Select(
                [],
                prompt="Custom reports…",
                id="custom-report-select",
                allow_blank=True,
            )

        yield Static("", id="report-context-bar")
        yield EmptyState(
            "No data for this report",
            "Check your filters and date range.",
            icon="📭",
            id="reports-empty-state",
        )
        yield DataTable(id="reports-table")
        with VerticalScroll(id="custom-report-output"):
            yield Static("", id="custom-report-text")

    def on_mount(self) -> None:
        """Set up the DataTable and load report data."""
        table = self.query_one("#reports-table", DataTable)
        table.cursor_type = "cell"
        self._refresh_custom_report_select()
        self._update_context_bar_builtin()
        self._set_empty_state_visible(False)
        self._load_report_data()

    def on_resize(self) -> None:
        """Recalculate column widths when the pane is resized."""
        if self._fixed_widths:
            table = self.query_one("#reports-table", DataTable)
            distribute_column_widths(table, self._fixed_widths)

    # --- Context bar ---

    def _update_context_bar_builtin(self) -> None:
        """Refresh the context bar to show the active built-in report and period."""
        report_name = REPORT_LABELS.get(self._report_type, self._report_type)
        period_name = REPORT_PERIOD_LABELS.get(self._period_months, "")

        text = Text()
        text.append(report_name, style="bold")
        text.append("  ·  ", style="dim")
        text.append(period_name, style="dim")

        self.query_one("#report-context-bar", Static).update(text)

    def _period_range(self) -> tuple[str, str]:
        """Calculate begin and end dates based on the selected period range.

        Returns:
            A ``(begin, end)`` tuple of date strings in ``YYYY-MM-DD`` format.
        """
        today = date.today()
        if today.month == 12:
            end = date(today.year + 1, 1, 1)
        else:
            end = date(today.year, today.month + 1, 1)

        if self._period_months == 0:
            begin = date(today.year, 1, 1)
        else:
            month = today.month - self._period_months + 1
            year = today.year
            while month < 1:
                month += 12
                year -= 1
            begin = date(year, month, 1)

        return begin.isoformat(), end.isoformat()

    # --- Workers ---

    @work(thread=True, exclusive=True, group="reports-load")
    def _load_report_data(self) -> None:
        """Load built-in report data in a background thread."""
        self.app.call_from_thread(show_loading_overlay, self, "Loading report…")
        begin, end = self._period_range()
        self._period_begin = date.fromisoformat(begin)
        commodity = resolve_default_commodity(self.journal_file)

        try:
            data = load_report(
                self.journal_file,
                self._report_type,
                period_begin=begin,
                period_end=end,
                commodity=commodity,
                sort_amount=self._sort_amount,
                cache=self._cache,
                mode="tree" if self._tree_mode else "flat",
            )
        except HledgerError as exc:
            title, body = humanize_error(exc)
            self.app.call_from_thread(
                self.notify, body, title=title, severity="error", timeout=10
            )
            data = ReportData(title="", period_headers=[], rows=[])

        if self._show_investments and self._report_type == "is":
            try:
                inv_data = load_investment_report(
                    self.journal_file,
                    period_begin=begin,
                    period_end=end,
                    commodity=commodity,
                )
                if inv_data.rows:
                    data = merge_investments(data, inv_data)
            except HledgerError:
                pass

        self._report_data = data
        self.app.call_from_thread(self._apply_report)

    @work(thread=True, exclusive=True, group="reports-load")
    def _load_custom_report_data(self) -> None:
        """Load custom report output in a background thread."""
        if self._custom_report_name is None:
            return
        self.app.call_from_thread(show_loading_overlay, self, "Loading report…")

        reports = load_custom_reports()
        command = reports.get(self._custom_report_name)
        if command is None:
            return

        try:
            output = run_custom_report(self.journal_file, command)
        except HledgerError as exc:
            title, body = humanize_error(exc)
            self.app.call_from_thread(
                self.notify, body, title=title, severity="error", timeout=10
            )
            output = f"Error: {body}"

        self.app.call_from_thread(self._apply_custom_output, output, command)

    # --- Apply methods ---

    def _apply_report(self) -> None:
        """Apply loaded report data to the DataTable."""
        hide_loading_overlay(self)
        table = self.query_one("#reports-table", DataTable)
        data = self._report_data

        if data is None:
            return

        table.clear(columns=True)
        table.add_column("Account", key="account")
        self._fixed_widths = {}
        for i, header in enumerate(data.period_headers):
            col_idx = i + 1
            table.add_column(header, key=f"period-{i}")
            self._fixed_widths[col_idx] = 18

        rows, self._table_rows, self._row_full_paths = build_report_rows(
            data, tree_mode=self._tree_mode, stacked_currency=self._stacked_currency
        )
        for cells, auto_height in rows:
            if auto_height:
                table.add_row(*cells, height=None)
            else:
                table.add_row(*cells)

        if self._fixed_widths:
            distribute_column_widths(table, self._fixed_widths)

        self._update_context_bar_builtin()
        self._sync_empty_state()

    def _sync_empty_state(self) -> None:
        """Show the built-in report empty state when loaded data has no rows."""
        data = self._report_data
        if self._custom_report_name is not None:
            self.query_one("#reports-empty-state", EmptyState).display = False
            self.query_one("#reports-table", DataTable).display = False
            return
        visible = data is not None and not data.rows
        self._set_empty_state_visible(visible)

    def _set_empty_state_visible(self, visible: bool) -> None:
        """Toggle the empty report message and DataTable visibility."""
        self.query_one("#reports-empty-state", EmptyState).display = visible
        self.query_one("#reports-table", DataTable).display = not visible

    # --- Drill-down helpers ---

    def _column_to_date_query(self, col_index: int) -> str:
        """Convert a zero-based period column index to an hledger date query.

        Args:
            col_index: Zero-based index into ``period_headers``.

        Returns:
            A string like ``'date:2026-01'``.
        """
        if self._period_begin is None:
            return ""
        month = self._period_begin.month + col_index
        year = self._period_begin.year
        while month > 12:
            month -= 12
            year += 1
        return f"date:{year}-{month:02d}"

    # --- Actions ---

    def action_view_transactions(self) -> None:
        """Push a drill-down screen showing transactions for the selected cell."""
        if self._custom_report_name is not None:
            return
        if not self._report_data or not self._table_rows:
            return

        table = self.query_one("#reports-table", DataTable)
        if table.row_count == 0:
            return

        row_idx = table.cursor_coordinate.row
        col_idx = table.cursor_coordinate.column

        if row_idx >= len(self._table_rows):
            return

        report_row = self._table_rows[row_idx]
        if report_row is None or report_row.is_section_header or report_row.is_total:
            return

        account = self._row_full_paths[row_idx]
        if not account:
            return

        date_query: str | None = None
        subtitle = ""
        if col_idx > 0 and self._report_data.period_headers:
            period_idx = col_idx - 1
            if period_idx < len(self._report_data.period_headers):
                date_query = self._column_to_date_query(period_idx)
                subtitle = self._report_data.period_headers[period_idx]

        from hledger_textual.screens.account_transactions import (
            AccountTransactionsScreen,
        )

        self.app.push_screen(
            AccountTransactionsScreen(
                account,
                subtitle,
                self.journal_file,
                date_query=date_query,
            )
        )

    def action_toggle_chart(self) -> None:
        """Open the chart dialog for the current report."""
        if self._custom_report_name is not None:
            return
        if not self._report_data:
            self.notify("No data to chart yet", severity="warning", timeout=3)
            return

        from hledger_textual.screens.report_chart_modal import ReportChartModal

        chart_data = extract_chart_data(self._report_data, self._report_type)
        if not chart_data:
            self.notify("No chart data available for this report", severity="warning", timeout=3)
            return

        report_label = REPORT_LABELS.get(self._report_type, self._report_type)
        period_label = REPORT_PERIOD_LABELS.get(self._period_months, "")
        title = f"{report_label}  ·  {period_label}"
        self.app.push_screen(ReportChartModal(chart_data, self._report_type, title))

    def action_toggle_investments(self) -> None:
        """Toggle the Investments section on the Income Statement."""
        if self._custom_report_name is not None:
            return
        self._show_investments = not self._show_investments
        label = "Investments shown" if self._show_investments else "Investments hidden"
        self.notify(label, timeout=2)
        self._load_report_data()

    def action_toggle_tree(self) -> None:
        """Switch between flat and tree view for built-in reports."""
        if self._custom_report_name is not None:
            return
        self._tree_mode = not self._tree_mode
        self.notify("Tree view" if self._tree_mode else "Flat view", timeout=2)
        self._load_report_data()

    def action_toggle_stacked_currency(self) -> None:
        """Toggle stacked multi-currency display on/off."""
        if self._custom_report_name is not None:
            return
        self._stacked_currency = not self._stacked_currency
        label = "Stacked" if self._stacked_currency else "Flat"
        self.notify(f"Multi-currency: {label}", timeout=2)
        self._apply_report()

    def action_toggle_sort_amount(self) -> None:
        """Toggle sorting report rows by amount (hledger --sort-amount)."""
        if self._custom_report_name is not None:
            return
        self._sort_amount = not self._sort_amount
        label = "Sorted by amount" if self._sort_amount else "Sorted by account"
        self.notify(label, timeout=2)
        self._load_report_data()

    def action_refresh(self) -> None:
        """Reload report data."""
        if self._custom_report_name is not None:
            self._load_custom_report_data()
        else:
            self._load_report_data()
        self.notify("Refreshed", timeout=2)

    @on(DataTable.CellSelected, "#reports-table")
    def on_report_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle Enter / click on a report table cell to drill down."""
        self.action_view_transactions()

    @on(Select.Changed, "#report-type-select")
    def on_report_type_changed(self, event: Select.Changed) -> None:
        """Reload when the report type changes."""
        if event.value is not Select.BLANK:
            self._report_type = event.value
            if self._custom_report_name is not None:
                self._custom_report_name = None
                self.query_one("#custom-report-select", Select).clear()
                self._set_custom_view(active=False)
            self._update_context_bar_builtin()
            self._load_report_data()

    @on(Select.Changed, "#report-period-select")
    def on_period_range_changed(self, event: Select.Changed) -> None:
        """Reload when the period range changes."""
        if event.value is not Select.BLANK:
            self._period_months = event.value
            if self._custom_report_name is None:
                self._update_context_bar_builtin()
                self._load_report_data()

    @on(Select.Changed, "#custom-report-select")
    def on_custom_report_changed(self, event: Select.Changed) -> None:
        """Load and display the selected custom report."""
        if event.value is Select.BLANK:
            self._custom_report_name = None
            self._set_custom_view(active=False)
            self._update_context_bar_builtin()
            return
        self._custom_report_name = str(event.value)
        reports = load_custom_reports()
        command = reports.get(self._custom_report_name, "")
        self._update_context_bar_custom(self._custom_report_name, command)
        self._set_custom_view(active=True)
        self._load_custom_report_data()

    def get_export_data(self):
        """Return an ExportData with report rows for export.

        Returns:
            An ExportData instance with Account and period columns.
        """
        from hledger_textual.export import ExportData

        data = self._report_data
        if data is None:
            return ExportData(
                title="Report",
                headers=["Account"],
                rows=[],
                pane_name="report",
            )

        headers = ["Account"] + list(data.period_headers)
        rows: list[list[str]] = []

        for row in data.rows:
            cells = [row.account]
            cells.extend(row.amounts)
            while len(cells) < len(headers):
                cells.append("")
            rows.append(cells)

        type_labels = {"is": "Income Statement", "bs": "Balance Sheet", "cf": "Cash Flow"}
        type_label = type_labels.get(self._report_type, self._report_type)

        return ExportData(
            title=type_label,
            headers=headers,
            rows=rows,
            pane_name="report",
        )
