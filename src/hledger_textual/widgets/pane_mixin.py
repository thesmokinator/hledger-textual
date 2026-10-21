"""Shared mixin for pane widgets backed by a DataTable."""

from __future__ import annotations

from textual import work
from textual.widgets import DataTable

from hledger_textual.error_messages import humanize_error
from hledger_textual.widgets import distribute_column_widths


class DataTablePaneMixin:
    """Mixin providing on_show, on_resize, cursor navigation, and export for DataTable panes.

    Subclasses must set ``_main_table_id`` (the CSS id of their DataTable)
    and ``_fixed_column_widths`` (a dict of column-index to fixed width).

    Panes with several tables may set ``_additional_tables`` (a dict of
    CSS id to fixed widths) to have their widths recalculated on resize
    too, and panes whose tables must not receive keyboard focus may set
    ``_focus_on_show`` to ``False``.

    To support export, subclasses should override ``get_export_data()``.
    """

    _main_table_id: str
    _fixed_column_widths: dict[int, int] = {}
    _flex_column_weights: dict[int, int] = {}
    _additional_tables: dict[str, dict[int, int]] = {}
    _focus_on_show: bool = True

    def _get_main_table(self) -> DataTable:
        """Return the pane's primary DataTable."""
        return self.query_one(f"#{self._main_table_id}", DataTable)

    def on_show(self) -> None:
        """Restore focus to the table when the pane becomes visible."""
        if self._focus_on_show:
            self._get_main_table().focus()

    def on_resize(self) -> None:
        """Recalculate column widths when the pane is resized."""
        distribute_column_widths(
            self._get_main_table(), self._fixed_column_widths, self._flex_column_weights
        )
        for table_id, widths in self._additional_tables.items():
            distribute_column_widths(self.query_one(f"#{table_id}", DataTable), widths)

    def action_cursor_down(self) -> None:
        """Move cursor down in the table."""
        self._get_main_table().action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up in the table."""
        self._get_main_table().action_cursor_up()

    def action_cursor_left(self) -> None:
        """Move cursor left in the table."""
        self._get_main_table().action_cursor_left()

    def action_cursor_right(self) -> None:
        """Move cursor right in the table."""
        self._get_main_table().action_cursor_right()

    def get_export_data(self):
        """Return an :class:`ExportData` for the currently visible table data.

        Subclasses should override this to provide pane-specific export content.

        Returns:
            An ExportData instance, or None if export is not supported.
        """
        return None

    def action_export(self) -> None:
        """Open the export modal and export visible data to CSV or PDF."""
        from hledger_textual.config import load_export_dir
        from hledger_textual.export import default_filename

        data = self.get_export_data()
        if data is None:
            self.notify("Export not available for this pane", severity="warning", timeout=3)
            return

        from hledger_textual.screens.export_modal import ExportModal

        filename = default_filename(data.pane_name, "csv")
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
        """Execute the export in a background thread.

        Args:
            data: The ExportData to export.
            fmt: Export format ("csv" or "pdf").
            filename: The target filename.
            directory: The target directory path.
        """
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
            title, body = humanize_error(exc)
            self.app.call_from_thread(
                self.notify,
                f"Export failed: {body}",
                title=title,
                severity="error",
                timeout=10,
            )
