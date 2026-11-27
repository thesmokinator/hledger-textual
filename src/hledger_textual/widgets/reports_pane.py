"""Reports pane widget with multi-period financial reports (IS, BS, CF)."""

from __future__ import annotations

from datetime import date, timedelta
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
from hledger_textual.comparison import (
    append_comparison_columns,
    normalize_comparison_headers,
    without_comparison_columns,
)
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
        Binding("y", "toggle_comparison", "Compare", show=True, priority=True),
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
        #: Year-over-year comparison state (issue #278): "off", "year" or
        #: "quarter".  Yearly columns come from hledger's native `-Y`/`-Q`
        #: intervals; balance-sheet columns stay end-of-period balances.
        self._comparison: str = "off"
        #: Calendar years covered by the comparison window, in order.
        self._comparison_years: list[int] = []
        #: Number of hledger period columns before the appended Δ / Δ%.
        self._comparison_base_cols: int = 0
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
        if self._comparison == "year":
            period_name = "Yearly comparison"
        elif self._comparison == "quarter":
            period_name = "Quarterly comparison"

        text = Text()
        text.append(report_name, style="bold")
        text.append("  ·  ", style="dim")
        text.append(period_name, style="dim")
        text.append("  ·  ", style="dim")
        text.append(self._window_display_range(), style="dim")

        self.query_one("#report-context-bar", Static).update(text)

    def _window_display_range(self) -> str:
        """Return the month span the report window covers, e.g. ``2024-07 → 2024-12``.

        Derived from the shared period selection: a range selection names
        itself, ``all`` says "All time", and a month anchor produces the
        window given the current length setting.
        """
        period = get_period(self)
        if self._comparison != "off" and self._comparison_years:
            years = self._comparison_years
            return f"{years[0]} → {years[-1]}"
        if period.kind == "all":
            return "All time"
        if period.kind == "range":
            return period.label
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

    def set_comparison(self, mode: str) -> None:
        """Set the year-over-year comparison mode (issue #278).

        Args:
            mode: One of ``"off"``, ``"year"`` or ``"quarter"``.
        """
        if mode not in ("off", "year", "quarter"):
            raise ValueError(f"Unknown comparison mode: {mode!r}")
        self._comparison = mode
        if mode == "off":
            self._comparison_years = []

    def action_toggle_comparison(self) -> None:
        """Cycle comparison mode: off → yearly → quarterly → off."""
        if self._custom_report_name is not None:
            return
        order = ("off", "year", "quarter")
        nxt = order[(order.index(self._comparison) + 1) % len(order)]
        self.set_comparison(nxt)
        labels = {"off": "Comparison off", "year": "Yearly comparison", "quarter": "Quarterly comparison"}
        self.notify(labels[nxt], timeout=2)
        self._load_report_data()

    def _comparison_range(self) -> tuple[str, str]:
        """Return the year-snapped ``(begin, end)`` window for comparison.

        The current period window is widened to full calendar years, going
        back at least 3 years from the end year so a single-month selection
        still compares meaningfully.  Yearly columns come from one native
        hledger ``-Y``/``-Q`` query over this span.

        Returns:
            ``(begin, end)`` ISO date strings, end exclusive.
        """
        begin, end = self._period_range()
        if end is not None:
            end_year = (date.fromisoformat(end) - timedelta(days=1)).year
        else:
            anchor = get_period(self).begin or date.today()
            end_year = anchor.year
        begin_year = (
            date.fromisoformat(begin).year if begin is not None else end_year
        )
        if end_year - begin_year < 2:
            begin_year = end_year - 2
        self._comparison_years = list(range(begin_year, end_year + 1))
        return f"{begin_year}-01-01", f"{end_year + 1}-01-01"

    def _comparison_range_query(self) -> str:
        """Return a date query covering the whole comparison window."""
        years = self._comparison_years
        if not years:
            return ""
        return f"date:{years[0]}..{years[-1]}"

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

    def _period_range(self) -> tuple[str | None, str | None]:
        """Calculate begin and end dates for the report window.

        A shared selection of kind ``range`` (including year spans) is used
        directly as the window.  ``all`` reports on the whole journal.
        Otherwise the window ends at the anchor month of the shared period
        selection (issue #263) with the length from ``_period_months``.

        Returns:
            A ``(begin, end)`` tuple of date strings in ``YYYY-MM-DD``
            format, where *end* is exclusive (hledger ``-e``).  Both are
            ``None`` for the whole journal.
        """
        period = get_period(self)
        if period.kind == "all":
            return None, None
        if (
            period.kind == "range"
            and period.begin is not None
            and period.end is not None
        ):
            return period.begin.isoformat(), period.end.isoformat()

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
            comparison = self._comparison
            if comparison == "off":
                begin, end = self._period_range()
                interval: str = "month"
                self._comparison_base_cols = 0
            else:
                begin, end = self._comparison_range()
                interval = comparison
            self._period_begin = date.fromisoformat(begin) if begin else None
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
                    interval=interval,
                )

            def _load_investments() -> ReportData:
                return load_investment_report(
                    self.journal_file,
                    period_begin=begin,
                    period_end=end,
                    commodity=commodity,
                    cache=self._cache,
                    interval=interval,
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
            if comparison != "off":
                headers = normalize_comparison_headers(
                    data.period_headers, comparison
                )
                data = ReportData(
                    title=data.title, period_headers=headers, rows=data.rows
                )
                self._comparison_base_cols = len(headers)
                data = append_comparison_columns(data)
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

        In comparison mode columns are whole years (``date:2024``) or
        quarters (``date:2024-04``); Δ / Δ% columns map to ``""`` and the
        drill-down falls back to the whole comparison window.

        Args:
            col_index: Zero-based index into ``period_headers``.

        Returns:
            A string like ``'date:2026-01'``, or ``""`` when unmappable.
        """
        if self._comparison != "off" and self._comparison_years:
            years = self._comparison_years
            if self._comparison == "year":
                if 0 <= col_index < len(years):
                    return f"date:{years[col_index]}"
                return ""
            quarters = len(years) * 4
            if 0 <= col_index < quarters:
                year = years[0] + col_index // 4
                month = 1 + 3 * (col_index % 4)
                return f"date:{year}-{month:02d}"
            return ""
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
            headers = self._report_data.period_headers
            if period_idx < len(headers):
                date_query = self._column_to_date_query(period_idx)
                subtitle = headers[period_idx]
                if (
                    self._comparison != "off"
                    and not date_query
                    and self._comparison_years
                ):
                    date_query = self._comparison_range_query()
                    years = self._comparison_years
                    subtitle = f"{years[0]} → {years[-1]}"

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

        chart_data = extract_chart_data(
            without_comparison_columns(self._report_data), self._report_type
        )
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
