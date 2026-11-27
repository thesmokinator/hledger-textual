"""Modal screen for browsing period presets and saved period views."""

from __future__ import annotations

from datetime import date

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from hledger_textual.config import delete_period_view, load_period_views
from hledger_textual.period import all_selection, parse_period
from hledger_textual.period_presets import get_preset, list_presets
from hledger_textual.widgets.click_select_datatable import ClickSelectDataTable


class PeriodPresetsModal(ModalScreen[object | None]):
    """Browse presets and saved views, applying the chosen period.

    Dismisses with the selected :class:`PeriodSelection` on Enter, or with
    ``None`` when closed without a selection.  Unparseable stored
    expressions fall back to the All-time selection instead of failing.
    """

    BINDINGS = [
        Binding("escape", "dismiss_none", "Close", show=True),
        Binding("d", "delete_selected", "Delete view", show=True),
        Binding("r", "rename_selected", "Rename view", show=True),
    ]

    def __init__(self, today: date | None = None, **kwargs) -> None:
        """Initialise the modal.

        Args:
            today: Reference date for preset arithmetic; defaults to today.
        """
        super().__init__(**kwargs)
        self._today = today or date.today()

    def compose(self) -> ComposeResult:
        """Render the presets dialog."""
        with Vertical(id="period-presets-dialog"):
            yield Static("Period presets", id="period-presets-title")
            yield ClickSelectDataTable(id="period-presets-table", show_cursor=True)
            yield Static(
                "Enter: apply  ·  d: delete view  ·  r: rename view"
                "  ·  Escape: close",
                id="period-presets-hint",
            )

    def on_mount(self) -> None:
        """Populate the presets table."""
        table = self.query_one("#period-presets-table", DataTable)
        table.cursor_type = "row"
        table.show_header = True
        table.add_column("Preset / View", width=22)
        table.add_column("Period")
        self._reload_table()
        table.focus()

    def _reload_table(self) -> None:
        """Clear and repopulate the table from presets plus config."""
        table = self.query_one("#period-presets-table", DataTable)
        table.clear()
        for preset_id, label in list_presets():
            expr = get_preset(preset_id, self._today).period_expr
            table.add_row(label, expr or "All time", key=f"preset:{preset_id}")
        for name, expr in load_period_views().items():
            table.add_row(name, expr or "All time", key=f"view:{name}")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Apply the selected preset or view and close the modal."""
        key = event.row_key.value if event.row_key else None
        if not key:
            return
        if key.startswith("preset:"):
            self.dismiss(get_preset(key[len("preset:"):], self._today))
            return
        if key.startswith("view:"):
            name = key[len("view:"):]
            expr = load_period_views().get(name)
            if expr is None:
                return
            if expr == "":
                self.dismiss(all_selection())
                return
            selection = parse_period(expr, today=self._today)
            self.dismiss(selection if selection is not None else all_selection())

    def action_delete_selected(self) -> None:
        """Delete the currently highlighted saved view (presets are kept)."""
        table = self.query_one("#period-presets-table", DataTable)
        if table.row_count == 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        key = row_key.value if row_key else None
        if not key or not key.startswith("view:"):
            return
        delete_period_view(key[len("view:"):])
        self._reload_table()

    def action_rename_selected(self) -> None:
        """Rename the highlighted view via the save dialog."""
        from hledger_textual.screens.save_period_view import SavePeriodViewModal

        table = self.query_one("#period-presets-table", DataTable)
        if table.row_count == 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        key = row_key.value if row_key else None
        if not key or not key.startswith("view:"):
            return
        old_name = key[len("view:"):]
        expr = load_period_views().get(old_name)
        if expr is None:
            return

        def on_result(new_name: str | None) -> None:
            if new_name is not None and new_name != old_name:
                delete_period_view(old_name)
            self._reload_table()

        self.app.push_screen(
            SavePeriodViewModal(current_expr=expr, initial_name=old_name),
            callback=on_result,
        )

    def action_dismiss_none(self) -> None:
        """Close the modal without applying any period."""
        self.dismiss(None)
