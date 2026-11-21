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
from hledger_textual.parallel import gather_loads
from hledger_textual.period import current_month_selection, shift_months
from hledger_textual.textual_compat import is_no_selection
from hledger_textual.widgets import distribute_column_widths
from hledger_textual.widgets.click_select_datatable import ClickSelectDataTable
from hledger_textual.widgets.constants import (
    REPORT_LABELS,
    REPORT_PERIOD_LABELS,
    REPORT_PERIOD_RANGES,
    REPORT_TYPES,
)
from hledger_textual.widgets.empty_state import EmptyState
from hledger_textual.widgets.loading import hide_loading_overlay
from hledger_textual.widgets.pane_mixin import (
    DataTablePaneMixin,
    get_period,
    request_initial_load,
    run_pane_load,
    set_empty_state_visible,
    set_period,
)
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
        Binding("T", "toggle_tree", "Tree/Flat", show=True, priority=True),
        Binding("S", "toggle_sort_amount", "Sort amount", show=True, priority=True),
        Binding("M", "toggle_stacked_currency", "Stacked", show=True, priority=True),
        Binding("x", "export", "Export", show=False, priority=True),
        Binding("n", "new_custom_report", "New report", show=True, priority=True),
        Binding("e", "edit_custom_report", "Edit report", show=False, priority=True),
        Binding("d", "delete_custom_report", "Delete report", show=False, priority=True),
        Binding("escape", "back_to_builtin", "Back", show=False),
        # Arrow keys shift the period window (issue #264); h/l/j/k keep
        # cursor navigation inside the report table.
        Binding("left", "shift_window_back", "Shift window back", show=False, priority=True),
        Binding("right", "shift_window_forward", "Shift window forward", show=False, priority=True),
        Binding("shift+left", "shift_window_year_back", "Shift window back one year", show=False, priority=True),
        Binding("shift+right", "shift_window_year_forward", "Shift window forward one year", show=False, priority=True),
        Binding("t", "today_window", "Today", show=False, priority=True),
        Binding("g", "go_to_period", "Go to period", show=True, priority=True),
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
        # Incremental rendering state: rebuild columns only when the period
        # headers change, and skip a full redraw when the same cached report
        # is applied again.
        self._rendered_headers: tuple[str, ...] | None = None
        self._rendered_data: ReportData | None = None
        self._rendered_tree: bool = False
        self._rendered_stacked: bool = True

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
        yield ClickSelectDataTable(id="reports-table")
        with VerticalScroll(id="custom-report-output"):
            yield Static("", id="custom-report-text")

    def on_mount(self) -> None:
        """Set up the DataTable and load report data."""
        table = self.query_one("#reports-table", DataTable)
        table.cursor_type = "cell"
        self._refresh_custom_report_select()
        self._update_context_bar_builtin()
        set_empty_state_visible(self, "reports-empty-state", "reports-table", False)
        request_initial_load(self, "reports", self._load_report_data)

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
        text.append("  ·  ", style="dim")
        text.append(self._window_display_range(), style="dim")

        self.query_one("#report-context-bar", Static).update(text)

    def _window_display_range(self) -> str:
        """Return the month span the report window covers, e.g. ``2024-07 → 2024-12``.

        Derived from the shared period anchor (issue #263) and the window
        length, so it always matches the data that would be loaded now.
        """
        period = get_period(self)
        anchor = period.begin or date.today()
        anchor = anchor.replace(day=1)
        if self._period_months == 0:
            begin = date(anchor.year, 1, 1)
        else:
            total = anchor.year * 12 + anchor.month - self._period_months
            begin_year, begin_month = divmod(total, 12)
            begin = date(begin_year, begin_month + 1, 1)
        return f"{begin.strftime('%Y-%m')} \u2192 {anchor.strftime('%Y-%m')}"

    # --- Window navigation (issue #264) ---

    def _window_months(self) -> int:
        """Return the shift amount for one window step.

        The window length itself (3/6/12 months, YTD) is a separate setting
        from the anchor; a YTD window shifts by a full year.
        """
        return self._period_months if self._period_months > 0 else 12

    def _shift_window(self, months: int) -> None:
        """Move the shared period anchor by *months* and reload.

        Args:
            months: Number of months to shift (negative = backwards).
        """
        set_period(self, shift_months(get_period(self), months))
        self._load_report_data()

    def action_shift_window_back(self) -> None:
        """Shift the report window back by its own length."""
        self._shift_window(-self._window_months())

    def action_shift_window_forward(self) -> None:
        """Shift the report window forward by its own length."""
        self._shift_window(self._window_months())

    def action_shift_window_year_back(self) -> None:
        """Shift the report window back by one year."""
        self._shift_window(-12)

    def action_shift_window_year_forward(self) -> None:
        """Shift the report window forward by one year."""
        self._shift_window(12)

    def action_today_window(self) -> None:
        """Return the report window to the current month."""
        set_period(self, current_month_selection())
        self._load_report_data()

    def action_go_to_period(self) -> None:
        """Open the period picker and jump to the chosen selection."""
        from hledger_textual.screens.period_picker import PeriodPickerModal

        stats = getattr(self.app, "journal_stats", None)

        def on_result(selection) -> None:
            if selection is not None:
                set_period(self, selection)
                self._load_report_data()

        self.app.push_screen(
            PeriodPickerModal(journal_stats=stats, current=get_period(self)),
            callback=on_result,
        )

    def _period_range(self) -> tuple[str, str]:
        """Calculate begin and end dates for the report window.

        The window ends at the *anchor month* of the app's shared period
        selection (issue #263) instead of always ending today: this is what
        lets a 2024 window be displayed at all.  The window length still
        comes from ``_period_months``.

        Returns:
            A ``(begin, end)`` tuple of date strings in ``YYYY-MM-DD``
            format, where *end* is exclusive (hledger ``-e``).
        """
        period = get_period(self)
        anchor = period.begin or date.today()
        anchor = anchor.replace(day=1)

        end_month = anchor.month + 1
        end_year = anchor.year
        if end_month > 12:
            end_month, end_year = 1, end_year + 1
        end = date(end_year, end_month, 1)

        if self._period_months == 0:
            begin = date(anchor.year, 1, 1)
        else:
            total = anchor.year * 12 + anchor.month - self._period_months
            begin_year, begin_month = divmod(total, 12)
            begin = date(begin_year, begin_month + 1, 1)

        return begin.isoformat(), end.isoformat()

    # --- Workers ---

    @work(thread=True, exclusive=True, group="reports-load")
    def _load_report_data(self) -> None:
        """Load built-in report data in a background thread."""

        def _load() -> ReportData:
            begin, end = self._period_range()
            self._period_begin = date.fromisoformat(begin)
            commodity = resolve_default_commodity(self.journal_file)
            show_investments = self._show_investments and self._report_type == "is"

            def _load_report() -> ReportData:
                return load_report(
                    self.journal_file,
                    self._report_type,
                    period_begin=begin,
                    period_end=end,
                    commodity=commodity,
                    sort_amount=self._sort_amount,
                    cache=self._cache,
                    mode="tree" if self._tree_mode else "flat",
                )

            def _load_investments() -> ReportData:
                return load_investment_report(
                    self.journal_file,
                    period_begin=begin,
                    period_end=end,
                    commodity=commodity,
                    cache=self._cache,
                )

            if show_investments:
                report_result, inv_result = gather_loads(
                    [_load_report, _load_investments]
                )
            else:
                report_result = _load_report()
                inv_result = None

            if isinstance(report_result, Exception):
                raise report_result
            data = report_result

            if show_investments and inv_result is not None:
                if isinstance(inv_result, HledgerError):
                    pass  # no investment data available
                elif isinstance(inv_result, Exception):
                    raise inv_result
                elif inv_result.rows:
                    data = merge_investments(data, inv_result)
            return data

        def _apply(data: ReportData) -> None:
            self._report_data = data
            self._apply_report()

        run_pane_load(
            self,
            _load,
            _apply,
            loading_message="Loading report…",
            on_error=lambda _exc: ReportData(title="", period_headers=[], rows=[]),
        )

    @work(thread=True, exclusive=True, group="reports-load")
    def _load_custom_report_data(self) -> None:
        """Load custom report output in a background thread."""
        if self._custom_report_name is None:
            return

        reports = load_custom_reports()
        command = reports.get(self._custom_report_name)
        if command is None:
            return

        run_pane_load(
            self,
            lambda: run_custom_report(self.journal_file, command),
            lambda output: self._apply_custom_output(output, command),
            loading_message="Loading report…",
            on_error=lambda exc: f"Error: {humanize_error(exc)[1]}",
        )

    # --- Apply methods ---

    def _apply_report(self) -> None:
        """Apply loaded report data to the DataTable.

        Columns are only rebuilt when the period headers change, and applying
        the same cached report twice is a no-op.  This keeps period navigation
        and tab switches from tearing down the whole table.
        """
        hide_loading_overlay(self)
        if not self.is_attached or not self.query("#reports-table"):
            return
        table = self.query_one("#reports-table", DataTable)
        data = self._report_data

        if data is None:
            return

        if (
            data is self._rendered_data
            and self._tree_mode == self._rendered_tree
            and self._stacked_currency == self._rendered_stacked
        ):
            self._sync_empty_state()
            return

        headers = tuple(data.period_headers)
        if headers != self._rendered_headers:
            table.clear(columns=True)
            table.add_column("Account", key="account")
            self._fixed_widths = {}
            for i, header in enumerate(data.period_headers):
                col_idx = i + 1
                table.add_column(header, key=f"period-{i}")
                self._fixed_widths[col_idx] = 18
            self._rendered_headers = headers
        else:
            table.clear()

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

        self._rendered_data = data
        self._rendered_tree = self._tree_mode
        self._rendered_stacked = self._stacked_currency
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
        set_empty_state_visible(self, "reports-empty-state", "reports-table", visible)

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
        if not is_no_selection(event.value):
            # Select emits Changed for its initial value while mounting; the
            # deferred initial load already covers that case.
            if event.value == self._report_type and self._custom_report_name is None:
                return
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
        if not is_no_selection(event.value):
            if event.value == self._period_months:
                return
            self._period_months = event.value
            if self._custom_report_name is None:
                self._update_context_bar_builtin()
                self._load_report_data()

    @on(Select.Changed, "#custom-report-select")
    def on_custom_report_changed(self, event: Select.Changed) -> None:
        """Load and display the selected custom report."""
        if is_no_selection(event.value):
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
            return ExportData.from_rows("Report", ["Account"], [], "report")

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

        return ExportData.from_rows(type_label, headers, rows, "report")
