"""DataTable subclass that selects on the first click."""

from __future__ import annotations

from textual import events
from textual.coordinate import Coordinate
from textual.widgets import DataTable


class ClickSelectDataTable(DataTable):
    """DataTable that posts a selection on the first click.

    Textual 7.5 changed the DataTable mouse behaviour so that the first click
    only highlights a row or cell and a second click selects it.  The
    application uses single-click drill-down in the Summary portfolio, Saved
    Filters and Reports tables, so this subclass restores the previous
    behaviour.

    Textual dispatches message handlers for every class in the MRO, so the
    base ``DataTable._on_click`` still runs and moves the cursor.  This
    override only schedules the extra selection when the click targets a
    different coordinate; clicks on an already-highlighted row are handled by
    the base class without a duplicate message.
    """

    async def _on_click(self, event: events.Click) -> None:
        """Schedule a selection for the first click on a data cell."""
        meta = event.style.meta
        row = meta.get("row")
        column = meta.get("column")
        if (
            row is None
            or column is None
            or not self.show_cursor
            or self.cursor_type == "none"
            or (self.show_header and row == -1)
            or (self.show_row_labels and column == -1)
        ):
            return

        candidate = Coordinate(row, column)
        if candidate != self.cursor_coordinate and self.is_valid_coordinate(candidate):
            self.call_after_refresh(self._select_after_click, candidate)

    def _select_after_click(self, candidate: Coordinate) -> None:
        """Post the selection once the base click handler has moved the cursor."""
        if self.is_mounted and self.cursor_coordinate == candidate:
            self.action_select_cursor()
