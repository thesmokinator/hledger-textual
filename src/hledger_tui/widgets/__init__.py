"""Shared widget utilities."""

from __future__ import annotations

from textual.widgets import DataTable


def distribute_column_widths(
    table: DataTable,
    fixed_widths: dict[int, int],
    flex_weights: dict[int, int] | None = None,
) -> None:
    """Distribute column widths so that flex columns fill the remaining space.

    All columns listed in *fixed_widths* keep their specified width.
    Remaining space is divided among flex columns (those NOT in *fixed_widths*).

    When there is a single flex column, it takes all remaining space.
    When there are multiple flex columns, *flex_weights* controls how the
    remaining space is split.  Weights default to ``1`` for each flex column.

    Args:
        table: The DataTable to adjust.
        fixed_widths: Mapping of column index to fixed width in characters.
        flex_weights: Optional mapping of column index to relative weight for
            flex columns.  Only meaningful when more than one flex column exists.
    """
    cols = table.ordered_columns
    if not cols:
        return
    available = table.size.width
    if available <= 0:
        return

    padding_per_col = 2
    fixed_total = sum(fixed_widths.values()) + len(cols) * padding_per_col
    remaining = max(available - fixed_total, len(cols))

    # Identify flex columns and their weights
    flex_cols = [i for i in range(len(cols)) if i not in fixed_widths]
    if not flex_cols:
        # All columns are fixed — nothing to distribute
        for i, col in enumerate(cols):
            col.auto_width = False
            col.width = fixed_widths[i]
        table.refresh(layout=True)
        return

    weights = flex_weights or {}
    total_weight = sum(weights.get(i, 1) for i in flex_cols)

    flex_sizes: dict[int, int] = {}
    allocated = 0
    for j, i in enumerate(flex_cols):
        w = weights.get(i, 1)
        if j == len(flex_cols) - 1:
            # Last flex column absorbs rounding remainder
            flex_sizes[i] = max(remaining - allocated, 5)
        else:
            size = max(int(remaining * w / total_weight), 5)
            flex_sizes[i] = size
            allocated += size

    for i, col in enumerate(cols):
        col.auto_width = False
        col.width = fixed_widths.get(i, flex_sizes.get(i, 10))

    table.refresh(layout=True)
