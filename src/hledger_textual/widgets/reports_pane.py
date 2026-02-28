"""Reports pane widget with multi-period financial reports (IS, BS, CF)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import DataTable, Select

from hledger_textual.config import load_default_commodity
from hledger_textual.hledger import HledgerError, load_report
from hledger_textual.models import ReportData
from hledger_textual.widgets import distribute_column_widths
from hledger_textual.widgets.pane_toolbar import PaneToolbar
from hledger_textual.widgets.report_chart import ReportChart, extract_chart_data

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


class ReportsPane(Widget):
    """Widget showing multi-period hledger financial reports."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("c", "toggle_chart", "Chart", show=False, priority=True),
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
        self._report_type: str = "is"
        self._period_months: int = 6
        self._report_data: ReportData | None = None
        self._fixed_widths: dict[int, int] = {}

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

        yield DataTable(id="reports-table")
        yield ReportChart(id="report-chart")

    def on_mount(self) -> None:
        """Set up the DataTable and load report data."""
        table = self.query_one("#reports-table", DataTable)
        table.cursor_type = "row"
        self._load_report_data()

    def on_show(self) -> None:
        """Restore focus to the table when the pane becomes visible."""
        self.query_one("#reports-table", DataTable).focus()

    def on_resize(self) -> None:
        """Recalculate column widths when the pane is resized."""
        if self._fixed_widths:
            table = self.query_one("#reports-table", DataTable)
            distribute_column_widths(table, self._fixed_widths)

    def _period_range(self) -> tuple[str, str]:
        """Calculate begin and end dates based on the selected period range.

        Returns:
            A ``(begin, end)`` tuple of date strings in ``YYYY-MM-DD`` format.
        """
        today = date.today()
        # End: first day of next month
        if today.month == 12:
            end = date(today.year + 1, 1, 1)
        else:
            end = date(today.year, today.month + 1, 1)

        if self._period_months == 0:
            # Year to date
            begin = date(today.year, 1, 1)
        else:
            # Go back N months
            month = today.month - self._period_months + 1
            year = today.year
            while month < 1:
                month += 12
                year -= 1
            begin = date(year, month, 1)

        return begin.isoformat(), end.isoformat()

    @work(thread=True, exclusive=True, group="reports-load")
    def _load_report_data(self) -> None:
        """Load report data in a background thread."""
        begin, end = self._period_range()

        try:
            data = load_report(
                self.journal_file,
                self._report_type,
                period_begin=begin,
                period_end=end,
                commodity=load_default_commodity(),
            )
        except HledgerError as exc:
            self.app.call_from_thread(
                self.notify, str(exc), severity="error", timeout=8
            )
            data = ReportData(title="", period_headers=[], rows=[])

        self._report_data = data
        self.app.call_from_thread(self._apply_report)

    def _apply_report(self) -> None:
        """Apply loaded report data to the DataTable."""
        table = self.query_one("#reports-table", DataTable)
        data = self._report_data

        if data is None:
            return

        # Rebuild columns
        table.clear(columns=True)

        table.add_column("Account", key="account")
        self._fixed_widths = {}
        for i, header in enumerate(data.period_headers):
            col_idx = i + 1
            table.add_column(header, key=f"period-{i}")
            self._fixed_widths[col_idx] = 14

        # Populate rows with blank separator lines between groups
        n_cols = len(data.period_headers) + 1
        empty_row = [""] * n_cols

        for idx, row in enumerate(data.rows):
            if row.is_section_header and idx > 0:
                table.add_row(*empty_row)
            elif row.is_total:
                table.add_row(*empty_row)

            account_text = row.account
            if row.is_section_header:
                account_text = f"[bold cyan]{row.account}[/bold cyan]"
            elif row.is_total:
                account_text = f"[bold yellow]{row.account}[/bold yellow]"

            cells = [account_text]
            for amt in row.amounts:
                if row.is_total:
                    cells.append(f"[bold]{amt}[/bold]")
                else:
                    cells.append(amt)

            # Pad if amounts are fewer than period columns
            while len(cells) < len(data.period_headers) + 1:
                cells.append("")

            table.add_row(*cells)

        # Distribute widths
        if self._fixed_widths:
            distribute_column_widths(table, self._fixed_widths)

        self._update_chart()

    def _update_chart(self) -> None:
        """Extract chart data from the current report and replot."""
        chart = self.query_one("#report-chart", ReportChart)
        chart_data = extract_chart_data(self._report_data, self._report_type)
        chart.replot(chart_data, self._report_type)

    # --- Actions ---

    def action_toggle_chart(self) -> None:
        """Toggle chart visibility."""
        chart = self.query_one("#report-chart", ReportChart)
        chart.toggle_class("visible")

    def action_refresh(self) -> None:
        """Reload report data."""
        self._load_report_data()
        self.notify("Refreshed", timeout=2)

    def action_cursor_down(self) -> None:
        """Move cursor down in the table."""
        self.query_one("#reports-table", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up in the table."""
        self.query_one("#reports-table", DataTable).action_cursor_up()

    # --- Event handlers ---

    @on(Select.Changed, "#report-type-select")
    def on_report_type_changed(self, event: Select.Changed) -> None:
        """Reload when the report type changes."""
        if event.value is not Select.BLANK:
            self._report_type = event.value
            self._load_report_data()

    @on(Select.Changed, "#report-period-select")
    def on_period_range_changed(self, event: Select.Changed) -> None:
        """Reload when the period range changes."""
        if event.value is not Select.BLANK:
            self._period_months = event.value
            self._load_report_data()
