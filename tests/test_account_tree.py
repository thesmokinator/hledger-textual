"""Tests for account tree hierarchy feature."""

from __future__ import annotations

from unittest.mock import patch


from hledger_textual.hledger import load_account_tree_balances
from hledger_textual.models import AccountNode


# --- Tree parsing tests ---


_TREE_CSV = '''"account","balance"
"Assets","€10,000.00"
"  Bank","€8,000.00"
"    Checking","€5,000.00"
"    Savings","€3,000.00"
"  Investments","€2,000.00"
"Expenses","€3,500.00"
"  Groceries","€850.00"
"  Rent","€2,000.00"
"  Utilities","€650.00"
"Income","-€4,200.00"
"  Salary","-€4,000.00"
"  Freelance","-€200.00"
'''


class TestLoadAccountTreeBalances:
    """Tests for load_account_tree_balances parsing."""

    def test_returns_root_nodes(self) -> None:
        """Should return three root nodes: Assets, Expenses, Income."""
        with patch("hledger_textual.hledger.run_hledger", return_value=_TREE_CSV):
            roots = load_account_tree_balances("test.journal")

        assert len(roots) == 3
        assert roots[0].name == "Assets"
        assert roots[1].name == "Expenses"
        assert roots[2].name == "Income"

    def test_root_full_path(self) -> None:
        """Root nodes should have their name as full_path."""
        with patch("hledger_textual.hledger.run_hledger", return_value=_TREE_CSV):
            roots = load_account_tree_balances("test.journal")

        assert roots[0].full_path == "Assets"
        assert roots[1].full_path == "Expenses"

    def test_child_full_path(self) -> None:
        """Child nodes should have colon-separated full_path."""
        with patch("hledger_textual.hledger.run_hledger", return_value=_TREE_CSV):
            roots = load_account_tree_balances("test.journal")

        assets = roots[0]
        assert assets.children[0].full_path == "Assets:Bank"
        assert assets.children[1].full_path == "Assets:Investments"

    def test_grandchild_full_path(self) -> None:
        """Grandchild nodes should have full colon-separated path."""
        with patch("hledger_textual.hledger.run_hledger", return_value=_TREE_CSV):
            roots = load_account_tree_balances("test.journal")

        bank = roots[0].children[0]
        assert bank.children[0].full_path == "Assets:Bank:Checking"
        assert bank.children[1].full_path == "Assets:Bank:Savings"

    def test_depth_assignment(self) -> None:
        """Nodes should have correct depth values."""
        with patch("hledger_textual.hledger.run_hledger", return_value=_TREE_CSV):
            roots = load_account_tree_balances("test.journal")

        assert roots[0].depth == 0
        assert roots[0].children[0].depth == 1
        assert roots[0].children[0].children[0].depth == 2

    def test_balances_preserved(self) -> None:
        """Node balances should match the CSV data."""
        with patch("hledger_textual.hledger.run_hledger", return_value=_TREE_CSV):
            roots = load_account_tree_balances("test.journal")

        assert roots[0].balance == "€10,000.00"
        assert roots[0].children[0].balance == "€8,000.00"
        assert roots[0].children[0].children[0].balance == "€5,000.00"

    def test_children_count(self) -> None:
        """Parent nodes should have correct number of children."""
        with patch("hledger_textual.hledger.run_hledger", return_value=_TREE_CSV):
            roots = load_account_tree_balances("test.journal")

        assert len(roots[0].children) == 2  # Bank, Investments
        assert len(roots[0].children[0].children) == 2  # Checking, Savings
        assert len(roots[0].children[1].children) == 0  # Investments is leaf
        assert len(roots[1].children) == 3  # Groceries, Rent, Utilities

    def test_leaf_nodes_have_no_children(self) -> None:
        """Leaf nodes should have empty children list."""
        with patch("hledger_textual.hledger.run_hledger", return_value=_TREE_CSV):
            roots = load_account_tree_balances("test.journal")

        checking = roots[0].children[0].children[0]
        assert checking.children == []

    def test_nodes_default_expanded(self) -> None:
        """All nodes should start expanded by default."""
        with patch("hledger_textual.hledger.run_hledger", return_value=_TREE_CSV):
            roots = load_account_tree_balances("test.journal")

        assert roots[0].expanded is True
        assert roots[0].children[0].expanded is True

    def test_empty_output(self) -> None:
        """Should return empty list for empty CSV."""
        with patch("hledger_textual.hledger.run_hledger", return_value='"account","balance"\n'):
            roots = load_account_tree_balances("test.journal")

        assert roots == []


# --- AccountNode model tests ---


class TestAccountNode:
    """Tests for AccountNode dataclass."""

    def test_toggle_expanded(self) -> None:
        """Should be able to toggle expanded state."""
        node = AccountNode(
            name="Assets",
            full_path="Assets",
            balance="€100",
            depth=0,
            children=[
                AccountNode(name="Bank", full_path="Assets:Bank", balance="€100", depth=1)
            ],
        )
        assert node.expanded is True
        node.expanded = False
        assert node.expanded is False

    def test_node_without_children(self) -> None:
        """Leaf node should have empty children by default."""
        node = AccountNode(name="Checking", full_path="Assets:Bank:Checking", balance="€50", depth=2)
        assert node.children == []
        assert node.expanded is True


# --- Tree rendering logic tests ---


class TestTreeRendering:
    """Tests for tree view rendering helpers in AccountsPane."""

    def _make_tree(self) -> list[AccountNode]:
        """Create a simple test tree."""
        checking = AccountNode(name="Checking", full_path="Assets:Bank:Checking", balance="€5,000", depth=2)
        savings = AccountNode(name="Savings", full_path="Assets:Bank:Savings", balance="€3,000", depth=2)
        bank = AccountNode(name="Bank", full_path="Assets:Bank", balance="€8,000", depth=1, children=[checking, savings])
        assets = AccountNode(name="Assets", full_path="Assets", balance="€8,000", depth=0, children=[bank])
        groceries = AccountNode(name="Groceries", full_path="Expenses:Groceries", balance="€500", depth=1)
        expenses = AccountNode(name="Expenses", full_path="Expenses", balance="€500", depth=0, children=[groceries])
        return [assets, expenses]

    def test_collect_filtered_rows_match_leaf(self) -> None:
        """Filter matching a leaf should include its ancestors."""
        from hledger_textual.widgets.accounts_pane import AccountsPane

        pane = AccountsPane.__new__(AccountsPane)
        pane._tree_roots = self._make_tree()

        rows = pane._collect_filtered_rows(pane._tree_roots[0], 0, "checking")
        paths = [r[0] for r in rows]
        assert "Assets" in paths
        assert "Assets:Bank" in paths
        assert "Assets:Bank:Checking" in paths
        assert "Assets:Bank:Savings" not in paths

    def test_collect_filtered_rows_match_parent(self) -> None:
        """Filter matching a parent should include all its descendants."""
        from hledger_textual.widgets.accounts_pane import AccountsPane

        pane = AccountsPane.__new__(AccountsPane)
        pane._tree_roots = self._make_tree()

        rows = pane._collect_filtered_rows(pane._tree_roots[0], 0, "bank")
        paths = [r[0] for r in rows]
        assert "Assets" in paths
        assert "Assets:Bank" in paths
        assert "Assets:Bank:Checking" in paths
        assert "Assets:Bank:Savings" in paths

    def test_collect_filtered_rows_no_match(self) -> None:
        """Filter with no match should return empty list."""
        from hledger_textual.widgets.accounts_pane import AccountsPane

        pane = AccountsPane.__new__(AccountsPane)
        pane._tree_roots = self._make_tree()

        rows = pane._collect_filtered_rows(pane._tree_roots[0], 0, "xyz")
        assert rows == []
