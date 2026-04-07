"""Reports pane widget with multi-period financial reports (IS, BS, CF)."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from rich.text import Text
from textual.widgets import DataTable, Select, Static

from hledger_textual.cache import HledgerCache
from hledger_textual.config import (
    delete_custom_report,
    load_custom_reports,
    load_default_commodity,
    save_custom_report,
)
from hledger_textual.hledger import HledgerError, load_investment_report, load_report, run_custom_report
from hledger_textual.models import CustomReport, ReportData, ReportRow
from hledger_textual.widgets import distribute_column_widths
from hledger_textual.widgets.constants import TREE_INDENT
from hledger_textual.widgets.formatting import fmt_amount_str
from hledger_textual.widgets.pane_mixin import DataTablePaneMixin
from hledger_textual.widgets.pane_toolbar import PaneToolbar
from hledger_textual.widgets.report_chart import extract_chart_data

_ONLY_SEPS = re.compile(r'^[\s=\-\+\|]+$')
_STANDALONE_ZERO = re.compile(r'(?<![\d.])0(?![\d.])')

_REPORT_LABELS = {"is": "Income Statement", "bs": "Balance Sheet", "cf": "Cash Flow"}
_PERIOD_LABELS = {3: "3 months", 6: "6 months", 12: "12 months", 0: "Year to date"}

_REPORT_TYPES = [
    ("Income Statement", "is"),
    ("Balance Sheet", "bs"),
    ("Cash Flow", "cf"),
]

_PERIOD_RANGES = [
    ("3 months", 3),
    ("6 months", 6),
    ("12 months", 12),
    ("Year to date", 0),
]


def _format_custom_output(raw: str, *, skip_title: bool = False) -> Text:
    """Apply Rich styling to raw hledger text output.

    Improvements applied:

    - ``||`` and ``++`` replaced with Unicode box-drawing characters (``│`` / ``┼``)
    - Separator lines (``===`` / ``---``) are dimmed
    - Standalone zero values are dimmed
    - The report title (first non-empty, non-indented line) is rendered bold,
      unless ``skip_title`` is ``True`` in which case it is omitted entirely.
      Lines that start with whitespace are treated as data rows, not titles.
    - Total rows (lines after the ``---`` separator) are rendered bold yellow

    Args:
        raw: Raw stdout string from hledger.
        skip_title: When ``True``, the first non-empty, non-indented line (the
            hledger-generated title) is dropped from the output.  Use this when
            the report name is already displayed in a separate header widget.
            Lines that start with whitespace (data rows from simple commands
            like ``bal``) are never treated as titles.

    Returns:
        A :class:`rich.text.Text` ready for use in a :class:`~textual.widgets.Static`.
    """
    result = Text(no_wrap=False)
    lines = raw.splitlines()
    after_total_sep = False
    title_done = False

    for line in lines:
        display = line.replace('++', '┼').replace('||', '│')

        # Title: first non-empty line.  Hledger titles (e.g. "Balance
        # Sheet 2026-03-31") never start with whitespace, whereas data
        # rows from simple commands like ``bal`` are indented for amount
        # alignment.  Only treat the line as a title when it starts at
        # column 0; otherwise fall through to normal data handling.
        if not title_done:
            if display.strip():
                title_done = True
                if not display[0].isspace():
                    if not skip_title:
                        result.append(display + "\n", style="bold")
                    continue
                # First non-empty line is indented → data row, fall through
            else:
                if not skip_title:
                    result.append("\n")
                continue

        # Separator lines: only =, -, +, |, and spaces
        if _ONLY_SEPS.match(line):
            if line.strip() and '-' in line and '=' not in line:
                after_total_sep = True
            result.append(display + "\n", style="dim")
            continue

        # Total rows (after the --- separator)
        if after_total_sep:
            result.append(display + "\n", style="bold yellow")
            continue

        # Regular data line: dim standalone zero values
        line_text = Text(no_wrap=False)
        pos = 0
        for m in _STANDALONE_ZERO.finditer(display):
            if m.start() > pos:
                line_text.append(display[pos:m.start()])
            line_text.append("0", style="dim")
            pos = m.end()
        if pos < len(display):
            line_text.append(display[pos:])
        line_text.append("\n")
        result.append_text(line_text)

    return result


def _merge_investments(is_data: ReportData, inv_data: ReportData) -> ReportData:
    """Append investment rows as a new section to an Income Statement report.

    Args:
        is_data: The original Income Statement report data.
        inv_data: Investment balance report data.

    Returns:
        A new :class:`ReportData` with the investment rows appended.
    """
    merged_rows = list(is_data.rows)

    n_periods = len(is_data.period_headers)
    merged_rows.append(ReportRow(
        account="Investments",
        amounts=[""] * n_periods,
        is_section_header=True,
    ))

    for row in inv_data.rows:
        if not row.is_section_header and not row.is_total:
            account = row.account
            if ":" in account:
                account = account.rsplit(":", 1)[-1]
            merged_rows.append(ReportRow(
                account=account,
                amounts=row.amounts,
            ))

    return ReportData(
        title=is_data.title,
        period_headers=is_data.period_headers,
        rows=merged_rows,
    )


class ReportsPane(DataTablePaneMixin, Widget):
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
        Binding("x", "export", "Export", show=False, priority=True),
        Binding("n", "new_custom_report", "New report", show=True, priority=True),
        Binding("e", "edit_custom_report", "Edit report", show=False, priority=True),
        Binding("d", "delete_custom_report", "Delete report", show=False, priority=True),
        Binding("escape", "back_to_builtin", "Back", show=False),
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
        self._report_type: str = "is"
        self._period_months: int = 6
        self._report_data: ReportData | None = None
        self._fixed_widths: dict[int, int] = {}
        self._show_investments: bool = False
        self._tree_mode: bool = False
        self._sort_amount: bool = False
        self._custom_report_name: str | None = None
        self._period_begin: date | None = None
        self._table_rows: list[ReportRow | None] = []
        self._row_full_paths: list[str] = []

    def compose(self) -> ComposeResult:
        """Create the pane layout."""
        with PaneToolbar():
            yield Select(
                [(label, value) for label, value in _REPORT_TYPES],
                value="is",
                id="report-type-select",
                allow_blank=False,
            )
            yield Select(
                [(label, value) for label, value in _PERIOD_RANGES],
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
        yield DataTable(id="reports-table")
        with VerticalScroll(id="custom-report-output"):
            yield Static("", id="custom-report-text")

    def on_mount(self) -> None:
        """Set up the DataTable and load report data."""
        table = self.query_one("#reports-table", DataTable)
        table.cursor_type = "cell"
        self._refresh_custom_report_select()
        self._update_context_bar_builtin()
        self._load_report_data()

    def on_resize(self) -> None:
        """Recalculate column widths when the pane is resized."""
        if self._fixed_widths:
            table = self.query_one("#reports-table", DataTable)
            distribute_column_widths(table, self._fixed_widths)

    # --- Context bar ---

    def _update_context_bar_builtin(self) -> None:
        """Refresh the context bar to show the active built-in report and period."""
        report_name = _REPORT_LABELS.get(self._report_type, self._report_type)
        period_name = _PERIOD_LABELS.get(self._period_months, "")

        text = Text()
        text.append(report_name, style="bold")
        text.append("  ·  ", style="dim")
        text.append(period_name, style="dim")

        self.query_one("#report-context-bar", Static).update(text)

    def _update_context_bar_custom(self, name: str, command: str) -> None:
        """Refresh the context bar to show the active custom report name and command.

        Args:
            name: The custom report name.
            command: The hledger command string.
        """
        text = Text()
        text.append(name, style="bold")
        if command:
            text.append("  ·  ", style="dim")
            text.append(command, style="dim")

        self.query_one("#report-context-bar", Static).update(text)

    # --- View toggle ---

    def _set_custom_view(self, active: bool) -> None:
        """Toggle between the built-in report view and the custom report output view.

        When ``active`` is ``True``, the DataTable and period Select are hidden
        and the raw-output area is shown.  The inverse applies when ``False``.
        A :class:`CustomReportStateChanged` message is posted so that the app
        can update the footer accordingly.

        Args:
            active: ``True`` to show the custom report output; ``False`` for the
                built-in DataTable view.
        """
        table = self.query_one("#reports-table", DataTable)
        output = self.query_one("#custom-report-output", VerticalScroll)
        period_select = self.query_one("#report-period-select", Select)
        type_select = self.query_one("#report-type-select", Select)

        table.display = not active
        output.display = active
        type_select.display = not active
        period_select.display = not active

        self.post_message(self.CustomReportStateChanged(active))

    # --- Custom report Select ---

    def _refresh_custom_report_select(self, select_name: str | None = None) -> None:
        """Reload custom report options in the Select widget.

        Args:
            select_name: If provided, sets the Select to this report name
                after refreshing the options.
        """
        reports = load_custom_reports()
        select = self.query_one("#custom-report-select", Select)
        options = [(name, name) for name in reports]
        select.set_options(options)
        if select_name is not None and select_name in reports:
            select.value = select_name

    # --- Period calculation ---

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
        begin, end = self._period_range()
        self._period_begin = date.fromisoformat(begin)
        commodity = load_default_commodity()

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
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
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
                    data = _merge_investments(data, inv_data)
            except HledgerError:
                pass

        self._report_data = data
        self.app.call_from_thread(self._apply_report)

    @work(thread=True, exclusive=True, group="reports-load")
    def _load_custom_report_data(self) -> None:
        """Load custom report output in a background thread."""
        if self._custom_report_name is None:
            return

        reports = load_custom_reports()
        command = reports.get(self._custom_report_name)
        if command is None:
            return

        try:
            output = run_custom_report(self.journal_file, command)
        except HledgerError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )
            output = f"Error: {exc}"

        self.app.call_from_thread(self._apply_custom_output, output, command)

    # --- Apply methods ---

    def _apply_custom_output(self, output: str, command: str) -> None:
        """Display custom report output with Rich styling.

        The hledger-generated title line is suppressed because the report name
        is already shown in the context bar.

        Args:
            output: The raw text returned by hledger.
            command: The command used, forwarded to the context bar.
        """
        static = self.query_one("#custom-report-text", Static)
        static.update(_format_custom_output(output.rstrip(), skip_title=True))
        if self._custom_report_name:
            self._update_context_bar_custom(self._custom_report_name, command)

    def _apply_report(self) -> None:
        """Apply loaded report data to the DataTable."""
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

        n_cols = len(data.period_headers) + 1
        empty_row = [""] * n_cols

        self._table_rows = []
        self._row_full_paths = []
        path_stack: list[str] = []

        for idx, row in enumerate(data.rows):
            if row.is_section_header and idx > 0:
                table.add_row(*empty_row)
                self._table_rows.append(None)
                self._row_full_paths.append("")
            elif row.is_total:
                table.add_row(*empty_row)
                self._table_rows.append(None)
                self._row_full_paths.append("")

            # Compute full account path for tree mode
            if row.is_section_header or row.is_total:
                full_path = ""
                if row.is_section_header:
                    path_stack.clear()
            else:
                if self._tree_mode:
                    while len(path_stack) > row.depth:
                        path_stack.pop()
                    if path_stack:
                        full_path = f"{path_stack[-1]}:{row.account}"
                    else:
                        full_path = row.account
                    if len(path_stack) == row.depth:
                        path_stack.append(full_path)
                    else:
                        path_stack[row.depth] = full_path
                else:
                    full_path = row.account

            if row.is_section_header:
                account_text = Text.from_markup(
                    f"[bold cyan]{row.account}[/bold cyan]", emoji=False
                )
            elif row.is_total:
                account_text = Text.from_markup(
                    f"[bold yellow]{row.account}[/bold yellow]", emoji=False
                )
            else:
                account_text = Text(TREE_INDENT * row.depth + row.account)

            cells = [account_text]
            for amt in row.amounts:
                formatted = fmt_amount_str(amt)
                if row.is_total:
                    cells.append(f"[bold]{formatted}[/bold]")
                else:
                    cells.append(formatted)

            while len(cells) < len(data.period_headers) + 1:
                cells.append("")

            table.add_row(*cells)
            self._table_rows.append(row)
            self._row_full_paths.append(full_path)

        if self._fixed_widths:
            distribute_column_widths(table, self._fixed_widths)

        self._update_context_bar_builtin()

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

        report_label = _REPORT_LABELS.get(self._report_type, self._report_type)
        period_label = _PERIOD_LABELS.get(self._period_months, "")
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

    def action_new_custom_report(self) -> None:
        """Open the form to create a new custom report."""
        from hledger_textual.screens.custom_report_form import CustomReportFormScreen

        def _on_result(report: CustomReport | None) -> None:
            if report is None:
                return
            save_custom_report(report.name, report.command)
            self._custom_report_name = report.name
            self._refresh_custom_report_select(select_name=report.name)
            self._set_custom_view(active=True)
            self._load_custom_report_data()

        self.app.push_screen(CustomReportFormScreen(), _on_result)

    def action_edit_custom_report(self) -> None:
        """Open the form to edit the currently selected custom report."""
        if self._custom_report_name is None:
            self.notify("No custom report selected", severity="warning", timeout=3)
            return

        from hledger_textual.screens.custom_report_form import CustomReportFormScreen

        reports = load_custom_reports()
        command = reports.get(self._custom_report_name, "")
        old_name = self._custom_report_name
        report = CustomReport(name=old_name, command=command)

        def _on_result(updated: CustomReport | None) -> None:
            if updated is None:
                return
            if updated.name != old_name:
                delete_custom_report(old_name)
            save_custom_report(updated.name, updated.command)
            self._custom_report_name = updated.name
            self._refresh_custom_report_select(select_name=updated.name)
            self._update_context_bar_custom(updated.name, updated.command)
            self._load_custom_report_data()

        self.app.push_screen(CustomReportFormScreen(report=report), _on_result)

    def action_delete_custom_report(self) -> None:
        """Open a confirmation dialog to delete the currently selected custom report."""
        if self._custom_report_name is None:
            self.notify("No custom report selected", severity="warning", timeout=3)
            return

        from hledger_textual.screens.custom_report_delete_confirm import (
            CustomReportDeleteConfirmModal,
        )

        name = self._custom_report_name

        def _on_result(confirmed: bool) -> None:
            if not confirmed:
                return
            delete_custom_report(name)
            self._custom_report_name = None
            self._refresh_custom_report_select()
            self._set_custom_view(active=False)
            self._update_context_bar_builtin()
            self._load_report_data()

        self.app.push_screen(CustomReportDeleteConfirmModal(name), _on_result)

    def action_back_to_builtin(self) -> None:
        """Return from custom report view to the built-in report view."""
        if self._custom_report_name is None:
            return
        self._custom_report_name = None
        self.query_one("#custom-report-select", Select).clear()
        self._set_custom_view(active=False)
        self._update_context_bar_builtin()
        self._load_report_data()

    # --- Event handlers ---

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
