"""Modal screen offering a single year instead of a huge all-time view."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from hledger_textual.widgets.click_select_datatable import ClickSelectDataTable


class AllTimeModal(ModalScreen[str | None]):
    """Warn about a large all-time view and offer single years instead.

    Dismisses with ``"all"`` to load everything anyway, with a ``"YYYY"``
    year string to scope to that year, or with ``None`` on cancel.
    """

    BINDINGS = [
        Binding("escape", "dismiss_none", "Close", show=True),
    ]

    def __init__(self, years: list[int], count: int, **kwargs) -> None:
        """Initialise the modal.

        Args:
            years: Journal years newest-first offered as single-year views.
            count: Total transaction count shown in the warning.
        """
        super().__init__(**kwargs)
        self._years = years
        self._count = count

    def compose(self) -> ComposeResult:
        """Render the warning dialog."""
        with Vertical(id="all-time-dialog"):
            yield Static(
                f"All time covers {self._count} transactions",
                id="all-time-title",
            )
            yield ClickSelectDataTable(id="all-time-table", show_cursor=True)
            yield Static(
                "Enter: open year / load all  ·  Escape: cancel",
                id="all-time-hint",
            )

    def on_mount(self) -> None:
        """Populate the year table."""
        table = self.query_one("#all-time-table", DataTable)
        table.cursor_type = "row"
        table.show_header = True
        table.add_column("View", width=22)
        table.add_column("Detail")
        for year in self._years:
            table.add_row(str(year), "single year", key=f"view:{year}")
        table.add_row(
            "Load all anyway", "year by year, newest first", key="__all__"
        )
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Dismiss with the chosen scope."""
        key = event.row_key.value if event.row_key else None
        if not key:
            return
        if key == "__all__":
            self.dismiss("all")
        elif key.startswith("view:"):
            self.dismiss(key[len("view:"):])

    def action_dismiss_none(self) -> None:
        """Close the modal without loading anything."""
        self.dismiss(None)
