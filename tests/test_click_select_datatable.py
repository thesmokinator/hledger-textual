"""Tests for single-click DataTable selection."""

from __future__ import annotations

from textual.app import App, ComposeResult

from hledger_textual.widgets.click_select_datatable import ClickSelectDataTable


class _ClickApp(App):
    """Minimal app hosting a click-select table."""

    def __init__(self) -> None:
        """Initialize the selected-row list."""
        super().__init__()
        self.selected: list[str] = []

    def compose(self) -> ComposeResult:
        """Mount the table."""
        yield ClickSelectDataTable(id="table")

    def on_mount(self) -> None:
        """Populate the table with two rows."""
        table = self.query_one(ClickSelectDataTable)
        table.cursor_type = "row"
        table.add_column("Name")
        table.add_row("one", key="one")
        table.add_row("two", key="two")

    def on_data_table_row_selected(self, event) -> None:
        """Record selected row keys."""
        self.selected.append(event.row_key.value)


async def test_first_click_selects_row() -> None:
    """A single click on an unhighlighted row selects it."""
    app = _ClickApp()
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        table = app.query_one(ClickSelectDataTable)
        app.selected.clear()

        await pilot.click(table, offset=(2, 2))
        await pilot.pause()

        assert table.cursor_row == 1
        assert app.selected == ["two"]


async def test_click_on_selected_row_selects_once() -> None:
    """Clicking an already-highlighted row posts one selection."""
    app = _ClickApp()
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        table = app.query_one(ClickSelectDataTable)

        await pilot.click(table, offset=(2, 2))
        await pilot.pause()
        app.selected.clear()

        await pilot.click(table, offset=(2, 2))
        await pilot.pause()

        assert app.selected == ["two"]


async def test_header_click_does_not_select() -> None:
    """Clicking the header does not post a row selection."""
    app = _ClickApp()
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        table = app.query_one(ClickSelectDataTable)
        app.selected.clear()

        await pilot.click(table, offset=(2, 0))
        await pilot.pause()

        assert app.selected == []
