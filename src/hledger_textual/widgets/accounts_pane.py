"""Accounts list pane widget with flat and tree views."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from rich.text import Text
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Input

from hledger_textual.cache import HledgerCache
from hledger_textual.config import load_accounts_view, save_accounts_view
from hledger_textual.hledger import (
    HledgerError,
    load_account_balances,
    load_account_tree_balances,
)
from hledger_textual.models import AccountNode
from hledger_textual.widgets.constants import TREE_INDENT
from hledger_textual.widgets.formatting import fmt_amount_str
from hledger_textual.widgets.pane_mixin import DataTablePaneMixin

_EXPANDED = "\u25bc "
_COLLAPSED = "\u25b6 "
_LEAF = "  "


class AccountsPane(DataTablePaneMixin, Widget):
    """Widget showing all accounts with their current balances."""

    _main_table_id = "accounts-table"
    _fixed_column_widths = {1: 20}

    BINDINGS = [
        Binding("enter", "view_account", "View", show=True, priority=True),
        Binding("space", "toggle_node", "Expand/Collapse", show=True, priority=True),
        Binding("t", "toggle_view", "Flat/Tree", show=True, priority=True),
        Binding("slash", "filter", "Filter", show=True, priority=True),
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("x", "export", "Export", show=False, priority=True),
        Binding("escape", "dismiss_filter", "Dismiss filter", show=False),
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
        self._balances: list[tuple[str, str]] = []
        self._tree_roots: list[AccountNode] = []
        self._tree_mode: bool = load_accounts_view() == "tree"
        self.filter_text: str = ""

    def compose(self) -> ComposeResult:
        """Create the pane layout."""
        with Horizontal(classes="filter-bar"):
            yield Input(
                placeholder="Filter by account name...",
                id="acc-filter-input",
                disabled=True,
            )
        yield DataTable(id="accounts-table")

    def on_mount(self) -> None:
        """Set up the DataTable and load account balances."""
        table = self._get_main_table()
        table.cursor_type = "row"
        table.add_column("Account", width=20)
        table.add_column("Balance", width=self._fixed_column_widths[1])
        self._load_data()
        table.focus()

    def _load_data(self) -> None:
        """Load account data from hledger for both views."""
        try:
            self._balances = load_account_balances(self.journal_file, cache=self._cache)
        except HledgerError as exc:
            self.notify(str(exc), severity="error", timeout=8)
            self._balances = []

        try:
            self._tree_roots = load_account_tree_balances(self.journal_file)
        except HledgerError:
            self._tree_roots = []

        self._update_table()

    _SEP_KEY_PREFIX = "__sep_"

    def _update_table(self) -> None:
        """Refresh the DataTable based on current view mode and filter."""
        if self._tree_mode:
            self._update_table_tree()
        else:
            self._update_table_flat()

    def _update_table_flat(self) -> None:
        """Render the flat account list."""
        table = self.query_one("#accounts-table", DataTable)
        table.clear()
        prev_group = ""
        for sep_idx, (account, balance) in enumerate(self._filtered_balances()):
            group = account.split(":")[0]
            if prev_group and group != prev_group:
                table.add_row("", "", key=f"{self._SEP_KEY_PREFIX}{sep_idx}")
            prev_group = group
            table.add_row(Text(account), fmt_amount_str(balance), key=account)

    def _update_table_tree(self) -> None:
        """Render the tree view with indentation and expand/collapse indicators."""
        table = self.query_one("#accounts-table", DataTable)
        table.clear()

        if self.filter_text:
            self._render_filtered_tree(table)
        else:
            for root in self._tree_roots:
                self._render_node(table, root, depth=0)

    def _render_node(self, table: DataTable, node: AccountNode, depth: int) -> None:
        """Recursively render a node and its visible children.

        Args:
            table: The DataTable to add rows to.
            node: The AccountNode to render.
            depth: Current indentation depth.
        """
        indent = TREE_INDENT * depth
        if node.children:
            icon = _EXPANDED if node.expanded else _COLLAPSED
        else:
            icon = _LEAF

        label = Text(f"{indent}{icon}{node.name}")
        if node.children:
            label.stylize("bold")

        table.add_row(label, fmt_amount_str(node.balance), key=node.full_path)

        if node.expanded:
            for child in node.children:
                self._render_node(table, child, depth + 1)

    def _render_filtered_tree(self, table: DataTable) -> None:
        """Render tree nodes that match the filter, expanding ancestor paths."""
        term = self.filter_text.lower()
        rows: list[tuple[str, str, int, bool]] = []
        for root in self._tree_roots:
            rows.extend(self._collect_filtered_rows(root, 0, term))

        for full_path, balance, depth, has_children in rows:
            indent = TREE_INDENT * depth
            icon = _EXPANDED if has_children else _LEAF
            label = Text(f"{indent}{icon}{full_path.rsplit(':', 1)[-1]}")
            if has_children:
                label.stylize("bold")
            table.add_row(label, fmt_amount_str(balance), key=full_path)

    def _collect_filtered_rows(
        self, node: AccountNode, depth: int, term: str
    ) -> list[tuple[str, str, int, bool]]:
        """Collect rows matching the filter for tree rendering.

        Args:
            node: The AccountNode to check.
            depth: Current depth.
            term: Lowercase filter term.

        Returns:
            List of (full_path, balance, depth, has_children) tuples.
        """
        self_match = term in node.full_path.lower()

        child_results: list[tuple[str, str, int, bool]] = []
        for child in node.children:
            child_results.extend(
                self._collect_filtered_rows(child, depth + 1, term)
            )

        if self_match or child_results:
            result = [(node.full_path, node.balance, depth, bool(node.children))]
            result.extend(child_results)
            return result

        return []

    def _filtered_balances(self) -> list[tuple[str, str]]:
        """Return flat balances filtered by the current filter text."""
        if not self.filter_text:
            return self._balances
        term = self.filter_text.lower()
        return [
            (account, balance)
            for account, balance in self._balances
            if term in account.lower()
        ]

    # --- Tree helpers ---

    def _find_node(self, full_path: str) -> AccountNode | None:
        """Find a node by its full path in the tree.

        Args:
            full_path: The colon-separated account path.

        Returns:
            The matching AccountNode, or None.
        """
        for root in self._tree_roots:
            found = self._find_in_subtree(root, full_path)
            if found:
                return found
        return None

    def _find_in_subtree(self, node: AccountNode, full_path: str) -> AccountNode | None:
        """Recursively search for a node by full path.

        Args:
            node: Current node to check.
            full_path: Target path.

        Returns:
            The matching node, or None.
        """
        if node.full_path == full_path:
            return node
        for child in node.children:
            found = self._find_in_subtree(child, full_path)
            if found:
                return found
        return None

    # --- Actions ---

    def action_toggle_node(self) -> None:
        """Toggle expand/collapse on the selected tree node."""
        if not self._tree_mode:
            return

        table = self.query_one("#accounts-table", DataTable)
        if table.row_count == 0:
            return

        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        account = row_key.value if row_key else None
        if not account or account.startswith(self._SEP_KEY_PREFIX):
            return

        node = self._find_node(account)
        if node and node.children:
            node.expanded = not node.expanded
            self._update_table()
            # Restore cursor to the toggled node
            for idx in range(table.row_count):
                rk, _ = table.coordinate_to_cell_key(Coordinate(idx, 0))
                if rk and rk.value == account:
                    table.move_cursor(row=idx)
                    break

    def action_toggle_view(self) -> None:
        """Switch between flat and tree view and persist the choice."""
        self._tree_mode = not self._tree_mode
        self._update_table()
        mode = "tree" if self._tree_mode else "flat"
        save_accounts_view(mode)
        self.notify(f"{mode.capitalize()} view", timeout=2)

    def action_view_account(self) -> None:
        """Push the account-transactions detail screen for the selected account."""
        table = self.query_one("#accounts-table", DataTable)
        if table.row_count == 0:
            return

        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        account = row_key.value if row_key else None
        if not account or account.startswith(self._SEP_KEY_PREFIX):
            return

        if self._tree_mode:
            node = self._find_node(account)
            if node and node.children:
                # Toggle expand/collapse for parent nodes
                node.expanded = not node.expanded
                self._update_table()
                for idx in range(table.row_count):
                    rk, _ = table.coordinate_to_cell_key(Coordinate(idx, 0))
                    if rk and rk.value == account:
                        table.move_cursor(row=idx)
                        break
                return

        balance = ""
        if self._tree_mode:
            node = self._find_node(account)
            if node:
                balance = node.balance
        else:
            balance = next(
                (bal for acc, bal in self._balances if acc == account), ""
            )

        from hledger_textual.screens.account_transactions import AccountTransactionsScreen

        self.app.push_screen(
            AccountTransactionsScreen(account, balance, self.journal_file)
        )

    def action_refresh(self) -> None:
        """Reload account balances from the journal."""
        self._load_data()
        self.notify("Refreshed", timeout=2)

    def action_filter(self) -> None:
        """Show/focus the filter input."""
        filter_bar = self.query_one(".filter-bar")
        filter_bar.add_class("visible")
        filter_input = self.query_one("#acc-filter-input", Input)
        filter_input.disabled = False
        filter_input.focus()

    def action_dismiss_filter(self) -> None:
        """Hide the filter input and clear the filter."""
        filter_bar = self.query_one(".filter-bar")
        if filter_bar.has_class("visible"):
            filter_bar.remove_class("visible")
            filter_input = self.query_one("#acc-filter-input", Input)
            filter_input.value = ""
            filter_input.disabled = True
            self.filter_text = ""
            self._update_table()
            self.query_one("#accounts-table", DataTable).focus()

    # --- Event handlers ---

    def get_export_data(self):
        """Return an ExportData with filtered account balances for export.

        Returns:
            An ExportData instance with Account and Balance columns.
        """
        from hledger_textual.export import ExportData

        headers = ["Account", "Balance"]
        rows: list[list[str]] = []

        for account, balance in self._filtered_balances():
            rows.append([account, balance])

        return ExportData(
            title="Accounts",
            headers=headers,
            rows=rows,
            pane_name="accounts",
        )

    @on(Input.Changed, "#acc-filter-input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        """Filter accounts as the user types."""
        self.filter_text = event.value
        self._update_table()
