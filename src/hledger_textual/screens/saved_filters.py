"""Modal screen for browsing and applying saved search filters."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from hledger_textual.config import delete_filter, load_saved_filters
from hledger_textual.widgets.click_select_datatable import ClickSelectDataTable


class SavedFiltersModal(ModalScreen[str | None]):
    """Browse, apply, and delete named search filters.

    Dismisses with the selected query string on Enter, or with ``None``
    when closed without a selection.
    """

    BINDINGS = [
        Binding("escape", "dismiss_none", "Close", show=True),
        Binding("d", "delete_selected", "Delete", show=True),
    ]

    def compose(self) -> ComposeResult:
        """Render the browse dialog."""
        with Vertical(id="saved-filters-dialog"):
            yield Static("Saved Filters", id="saved-filters-title")
            yield ClickSelectDataTable(id="saved-filters-table", show_cursor=True)
            yield Static(
                "Enter: apply  ·  d: delete  ·  Escape: close",
                id="saved-filters-hint",
            )

    def on_mount(self) -> None:
        """Populate the filters table."""
        table = self.query_one("#saved-filters-table", DataTable)
        table.cursor_type = "row"
        table.show_header = True
        table.add_column("Name", width=22)
        table.add_column("Query")
        self._reload_table()
        table.focus()

    def _reload_table(self) -> None:
        """Clear and repopulate the table from config."""
        table = self.query_one("#saved-filters-table", DataTable)
        table.clear()
        filters = load_saved_filters()
        if not filters:
            table.add_row("[dim]No saved filters yet[/dim]", "", key="__empty__")
        else:
            for name, query in filters.items():
                table.add_row(name, query, key=name)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Apply the selected filter and close the modal."""
        key = event.row_key.value if event.row_key else None
        if not key or key == "__empty__":
            return
        filters = load_saved_filters()
        query = filters.get(key)
        if query:
            self.dismiss(query)

    def action_delete_selected(self) -> None:
        """Delete the currently highlighted filter."""
        table = self.query_one("#saved-filters-table", DataTable)
        if table.row_count == 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        key = row_key.value if row_key else None
        if not key or key == "__empty__":
            return
        delete_filter(key)
        self._reload_table()

    def action_dismiss_none(self) -> None:
        """Close the modal without applying any filter."""
        self.dismiss(None)
