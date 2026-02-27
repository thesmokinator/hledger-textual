"""Tests for the distribute_column_widths helper."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import DataTable

from hledger_textual.widgets import distribute_column_widths


class _TableApp(App):
    """Minimal app with a DataTable for testing column distribution."""

    def compose(self) -> ComposeResult:
        yield DataTable()


class TestDistributeColumnWidths:
    """Tests for distribute_column_widths."""

    async def test_single_flex_fills_remaining(self):
        """A single flex column expands to fill all remaining space."""
        app = _TableApp()
        async with app.run_test(size=(100, 10)) as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.add_column("Name", width=10)
            table.add_column("Amount", width=14)
            table.add_column("Pct", width=20)

            distribute_column_widths(table, {1: 14, 2: 20})

            cols = table.ordered_columns
            assert cols[1].width == 14
            assert cols[2].width == 20
            # Flex col 0 gets the rest: 100 - 2 (scrollbar) - (14 + 20) - 3*2 padding
            assert cols[0].width == 100 - 2 - 14 - 20 - 6

    async def test_flex_minimum_width(self):
        """The flex column never goes below the minimum (5 per col)."""
        app = _TableApp()
        async with app.run_test(size=(30, 10)) as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.add_column("Name", width=10)
            table.add_column("A", width=20)
            table.add_column("B", width=20)

            distribute_column_widths(table, {1: 20, 2: 20})

            cols = table.ordered_columns
            # Remaining is very small, but min is enforced
            assert cols[0].width >= 5

    async def test_multiple_flex_with_equal_weights(self):
        """Multiple flex columns split remaining space equally by default."""
        app = _TableApp()
        async with app.run_test(size=(100, 10)) as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.add_column("Date", width=12)
            table.add_column("Desc", width=20)
            table.add_column("Accounts", width=20)

            # Col 0 fixed, cols 1 and 2 flex (equal weight)
            distribute_column_widths(table, {0: 12})

            cols = table.ordered_columns
            assert cols[0].width == 12
            remaining = 100 - 2 - 12 - 3 * 2  # 80
            assert cols[1].width + cols[2].width == remaining

    async def test_multiple_flex_with_custom_weights(self):
        """Flex columns respect custom weight ratios."""
        app = _TableApp()
        async with app.run_test(size=(100, 10)) as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.add_column("Date", width=12)
            table.add_column("Status", width=8)
            table.add_column("Desc", width=20)
            table.add_column("Accts", width=20)
            table.add_column("Amount", width=16)

            # Cols 0,1 fixed; cols 2,3,4 flex with weights 3:3:2
            distribute_column_widths(
                table, {0: 12, 1: 8}, {2: 3, 3: 3, 4: 2}
            )

            cols = table.ordered_columns
            assert cols[0].width == 12
            assert cols[1].width == 8
            remaining = 100 - 2 - 12 - 8 - 5 * 2  # 68
            # Weight 3/8 of 68 ≈ 25, weight 2/8 ≈ 17
            assert cols[2].width > cols[4].width
            assert cols[2].width + cols[3].width + cols[4].width == remaining

    async def test_empty_table_no_crash(self):
        """Calling on a table with no columns does not crash."""
        app = _TableApp()
        async with app.run_test(size=(80, 10)) as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            distribute_column_widths(table, {1: 14})

    async def test_all_fixed_no_crash(self):
        """When all columns are fixed, no error occurs."""
        app = _TableApp()
        async with app.run_test(size=(80, 10)) as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.add_column("A", width=20)
            table.add_column("B", width=20)

            distribute_column_widths(table, {0: 20, 1: 20})

            cols = table.ordered_columns
            assert cols[0].width == 20
            assert cols[1].width == 20
