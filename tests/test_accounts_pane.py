"""Integration tests for the Accounts pane."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.models import AccountNode
from hledger_textual.widgets.accounts_pane import AccountsPane
from tests.conftest import has_hledger, wait_until

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


def _accounts_rows(app) -> int:
    """Row count of the accounts table, or 0 while it is not mounted yet."""
    try:
        return app.screen.query_one("#accounts-table").row_count
    except Exception:
        return 0


@pytest.fixture
def accounts_app_journal(tmp_path: Path) -> Path:
    """A temporary journal for accounts pane testing."""
    today = date.today()
    d1 = today.replace(day=1)

    content = (
        f"{d1.isoformat()} * Grocery shopping\n"
        "    expenses:food:groceries              €40.80\n"
        "    assets:bank:checking\n"
        "\n"
        f"{d1.isoformat()} Salary\n"
        "    assets:bank:checking               €3000.00\n"
        "    income:salary\n"
    )
    dest = tmp_path / "test.journal"
    dest.write_text(content)
    return dest


@pytest.fixture
def accounts_app(accounts_app_journal: Path) -> HledgerTuiApp:
    """Create an app instance for accounts testing."""
    return HledgerTuiApp(journal_file=accounts_app_journal)


class TestAccountsPane:
    """Tests for the Accounts pane display."""

    async def test_switch_to_accounts(self, accounts_app: HledgerTuiApp):
        """Pressing 2 switches to the accounts pane."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await pilot.pause(delay=0.5)
            from textual.widgets import ContentSwitcher

            switcher = accounts_app.screen.query_one(
                "#content-switcher", ContentSwitcher
            )
            assert switcher.current == "accounts"

    async def test_accounts_table_has_rows(self, accounts_app: HledgerTuiApp):
        """Accounts table shows accounts when data exists."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await pilot.pause(delay=0.5)
            table = accounts_app.screen.query_one("#accounts-table")
            assert table.row_count > 0

    async def test_accounts_refresh(self, accounts_app: HledgerTuiApp):
        """Pressing r refreshes the accounts list."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await pilot.pause(delay=0.5)
            table = accounts_app.screen.query_one("#accounts-table")
            count_before = table.row_count
            await pilot.press("r")
            await pilot.pause()
            assert table.row_count == count_before


class TestAccountsFilter:
    """Tests for the Accounts pane filter."""

    async def test_filter_shows_input(self, accounts_app: HledgerTuiApp):
        """Pressing / shows the filter input."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await pilot.pause(delay=0.5)
            await pilot.press("slash")
            await pilot.pause()
            from hledger_textual.widgets.accounts_pane import AccountsPane

            pane = accounts_app.screen.query_one(AccountsPane)
            filter_bar = pane.query_one(".filter-bar")
            assert filter_bar.has_class("visible")

    async def test_filter_narrows_results(self, accounts_app: HledgerTuiApp):
        """Typing in the filter narrows the account list."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await pilot.pause(delay=0.5)
            table = accounts_app.screen.query_one("#accounts-table")
            count_all = table.row_count
            await pilot.press("slash")
            await pilot.pause()
            filter_input = accounts_app.screen.query_one("#acc-filter-input")
            filter_input.value = "income"
            await pilot.pause()
            assert table.row_count < count_all
            assert table.row_count == 1

    async def test_escape_dismisses_filter(self, accounts_app: HledgerTuiApp):
        """Pressing Escape hides the filter and restores all rows."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await pilot.pause(delay=0.5)
            table = accounts_app.screen.query_one("#accounts-table")
            count_all = table.row_count
            await pilot.press("slash")
            await pilot.pause()
            filter_input = accounts_app.screen.query_one("#acc-filter-input")
            filter_input.value = "income"
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause(delay=0.5)
            assert table.row_count == count_all


class TestAccountDrillDown:
    """Tests for the account drill-down screen."""

    async def test_enter_opens_account_screen(self, accounts_app: HledgerTuiApp):
        """Pressing Enter on an account opens the drill-down screen."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await pilot.pause(delay=0.5)
            await pilot.press("enter")
            await pilot.pause(delay=0.5)
            from hledger_textual.screens.account_transactions import (
                AccountTransactionsScreen,
            )

            assert isinstance(accounts_app.screen, AccountTransactionsScreen)

    async def test_escape_returns_from_account_screen(
        self, accounts_app: HledgerTuiApp
    ):
        """Pressing Escape on the drill-down screen goes back."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await pilot.pause(delay=0.5)
            await pilot.press("enter")
            await pilot.pause(delay=0.5)
            await pilot.press("escape")
            await pilot.pause(delay=0.5)
            from hledger_textual.screens.account_transactions import (
                AccountTransactionsScreen,
            )

            assert not isinstance(accounts_app.screen, AccountTransactionsScreen)

    async def test_account_screen_shows_transactions(
        self, accounts_app: HledgerTuiApp
    ):
        """Drill-down screen shows transactions for the selected account."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await pilot.pause(delay=0.5)
            await pilot.press("enter")
            await pilot.pause(delay=1.0)
            table = accounts_app.screen.query_one("#transactions-table")
            assert table.row_count > 0


class TestAccountsToggleView:
    """Tests for the 't' (toggle flat/tree) keybinding."""

    async def test_toggle_changes_tree_mode(self, accounts_app: HledgerTuiApp):
        """Pressing 't' switches between flat and tree mode."""
        from hledger_textual.widgets.accounts_pane import AccountsPane

        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await pilot.pause()
            pane = accounts_app.screen.query_one(AccountsPane)
            initial = pane._tree_mode
            await pilot.press("t")
            await pilot.pause(delay=0.3)
            assert pane._tree_mode != initial

    async def test_toggle_twice_restores_mode(self, accounts_app: HledgerTuiApp):
        """Pressing 't' twice restores the original mode."""
        from hledger_textual.widgets.accounts_pane import AccountsPane

        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await pilot.pause()
            pane = accounts_app.screen.query_one(AccountsPane)
            initial = pane._tree_mode
            await pilot.press("t")
            await pilot.pause(delay=0.3)
            await pilot.press("t")
            await pilot.pause(delay=0.3)
            assert pane._tree_mode == initial


class TestAccountsTreeExport:
    """Export must work in tree mode, where only ``_tree_roots`` is loaded."""

    @pytest.fixture(autouse=True)
    def _default_flat_view(self, monkeypatch: pytest.MonkeyPatch):
        """Start in flat mode so the toggle to tree is explicit."""
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_accounts_view",
            lambda: "flat",
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.save_accounts_view",
            lambda _mode: None,
        )

    async def test_export_has_rows_in_tree_mode(self, accounts_app: HledgerTuiApp):
        """Regression: tree mode loaded only the tree, so export was empty."""
        async with accounts_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await wait_until(pilot, lambda: _accounts_rows(accounts_app) > 0)
            pane = accounts_app.screen.query_one(AccountsPane)
            await pilot.press("t")
            await wait_until(pilot, lambda: pane._tree_mode and bool(pane._tree_roots))
            data = pane.get_export_data()

        assert data.headers == ["Account", "Balance"]
        assert data.rows, "tree-mode export should not be empty"
        accounts = {row[0] for row in data.rows}
        assert "assets:bank:checking" in accounts


class TestAccountsLazyLoading:
    """Only the loader matching the current view mode should be called."""

    @pytest.fixture(autouse=True)
    def _force_flat_view(self, monkeypatch: pytest.MonkeyPatch):
        """Default these tests to flat mode regardless of user config."""
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_accounts_view",
            lambda: "flat",
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.save_accounts_view",
            lambda _mode: None,
        )

    async def test_only_active_mode_loaded_on_mount(
        self, accounts_app: HledgerTuiApp, monkeypatch: pytest.MonkeyPatch
    ):
        """Default flat mode: flat loader called, tree loader untouched."""
        flat_calls: list[dict] = []
        tree_calls: list[dict] = []

        def spy_flat(*args, **kwargs):
            flat_calls.append({"args": args, "kwargs": kwargs})
            return [("assets:x", "€1.00")]

        def spy_tree(*args, **kwargs):
            tree_calls.append({"args": args, "kwargs": kwargs})
            return []

        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_account_balances", spy_flat
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_account_tree_balances",
            spy_tree,
        )

        async with accounts_app.run_test() as pilot:
            await wait_until(pilot, lambda: len(flat_calls) >= 1)
            assert len(flat_calls) >= 1
            assert len(tree_calls) == 0

    async def test_toggle_loads_other_mode(
        self, accounts_app: HledgerTuiApp, monkeypatch: pytest.MonkeyPatch
    ):
        """After toggling to tree, the tree loader runs exactly once more."""
        flat_calls: list[dict] = []
        tree_calls: list[dict] = []

        def spy_flat(*args, **kwargs):
            flat_calls.append({"args": args, "kwargs": kwargs})
            return [("assets:x", "€1.00")]

        def spy_tree(*args, **kwargs):
            tree_calls.append({"args": args, "kwargs": kwargs})
            return []

        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_account_balances", spy_flat
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_account_tree_balances",
            spy_tree,
        )

        async with accounts_app.run_test() as pilot:
            await wait_until(pilot, lambda: len(flat_calls) >= 1)
            flat_before = len(flat_calls)
            tree_before = len(tree_calls)
            await pilot.press("6")
            await pilot.pause()
            await pilot.press("t")
            await wait_until(pilot, lambda: len(tree_calls) == tree_before + 1)
            assert len(tree_calls) == tree_before + 1
            assert len(flat_calls) == flat_before

    async def test_toggle_reloads_flat_on_toggle_back(
        self, accounts_app: HledgerTuiApp, monkeypatch: pytest.MonkeyPatch
    ):
        """Toggling tree -> flat re-invokes the flat loader (reload-per-toggle)."""
        flat_calls: list[dict] = []
        tree_calls: list[dict] = []

        def spy_flat(*args, **kwargs):
            flat_calls.append({"args": args, "kwargs": kwargs})
            return [("assets:x", "€1.00")]

        def spy_tree(*args, **kwargs):
            tree_calls.append({"args": args, "kwargs": kwargs})
            return [
                AccountNode(
                    name="assets",
                    full_path="assets",
                    balance="€1.00",
                    depth=0,
                )
            ]

        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_account_balances", spy_flat
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_account_tree_balances",
            spy_tree,
        )

        async with accounts_app.run_test() as pilot:
            await wait_until(pilot, lambda: len(flat_calls) >= 1)
            flat_after_mount = len(flat_calls)
            await pilot.press("6")
            await pilot.pause()
            pane = accounts_app.screen.query_one(AccountsPane)
            await pilot.press("t")
            await wait_until(pilot, lambda: pane._tree_mode)
            assert pane._tree_mode, "expected tree mode after first toggle"
            tree_after_first_toggle = len(tree_calls)
            await pilot.press("t")
            await wait_until(pilot, lambda: not pane._tree_mode)
            assert not pane._tree_mode, "expected flat mode after second toggle"
            assert len(tree_calls) == tree_after_first_toggle, (
                f"tree reloaded unexpectedly: {tree_calls}"
            )
            assert len(flat_calls) == flat_after_mount + 1


class TestAccountsCommodityConversion:
    """The configured default commodity must flow into the active loader."""

    @pytest.fixture(autouse=True)
    def _default_flat_view(self, monkeypatch: pytest.MonkeyPatch):
        """Most tests here need flat mode at startup; tree-mode tests override."""
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_accounts_view",
            lambda: "flat",
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.save_accounts_view",
            lambda _mode: None,
        )

    async def test_flat_load_passes_configured_commodity(
        self, accounts_app: HledgerTuiApp, monkeypatch: pytest.MonkeyPatch
    ):
        """flat mode: load_account_balances receives commodity='€'."""
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.resolve_default_commodity",
            lambda _file: "€",
        )
        seen: list[dict] = []

        def spy_flat(*args, **kwargs):
            seen.append({"args": args, "kwargs": kwargs})
            return [("assets:x", "€1.00")]

        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_account_balances", spy_flat
        )

        async with accounts_app.run_test() as pilot:
            await wait_until(pilot, lambda: len(seen) >= 1)
            assert len(seen) >= 1
            assert seen[-1]["kwargs"].get("commodity") == "€"

    async def test_flat_load_passes_none_when_unconfigured(
        self, accounts_app: HledgerTuiApp, monkeypatch: pytest.MonkeyPatch
    ):
        """flat mode with no configured commodity: commodity=None is passed."""
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.resolve_default_commodity",
            lambda _file: None,
        )
        seen: list[dict] = []

        def spy_flat(*args, **kwargs):
            seen.append({"args": args, "kwargs": kwargs})
            return [("assets:x", "€1.00")]

        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_account_balances", spy_flat
        )

        async with accounts_app.run_test() as pilot:
            await wait_until(pilot, lambda: len(seen) >= 1)
            assert len(seen) >= 1
            assert seen[-1]["kwargs"].get("commodity") is None

    async def test_tree_load_passes_configured_commodity(
        self, accounts_app_journal: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """tree mode: load_account_tree_balances receives commodity='€'."""
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_accounts_view",
            lambda: "tree",
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.resolve_default_commodity",
            lambda _file: "€",
        )
        seen: list[dict] = []

        def spy_tree(*args, **kwargs):
            seen.append({"args": args, "kwargs": kwargs})
            return []

        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_account_tree_balances",
            spy_tree,
        )

        app = HledgerTuiApp(journal_file=accounts_app_journal)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: len(seen) >= 1)
            assert len(seen) >= 1
            assert seen[-1]["kwargs"].get("commodity") == "€"

    async def test_integration_converted_balances(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """End-to-end: multicurrency journal, -X €, single-currency balance row."""
        repo_root = Path(__file__).resolve().parent.parent
        base = (repo_root / "examples" / "multicurrency.journal").read_text()
        prices = (repo_root / "examples" / "multicurrency-prices.journal").read_text()
        # Strip include directives that reference files outside tmp_path.
        base_lines = [
            line for line in base.splitlines() if not line.startswith("include ")
        ]
        journal = tmp_path / "multicurrency.journal"
        journal.write_text("\n".join(base_lines) + "\n\n" + prices)

        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.resolve_default_commodity",
            lambda _file: "€",
        )

        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await wait_until(pilot, lambda: _accounts_rows(app) > 0)
            table = app.screen.query_one("#accounts-table")
            target_row = None
            for i in range(table.row_count):
                row = table.get_row_at(i)
                account_cell = row[0]
                plain = (
                    account_cell.plain
                    if hasattr(account_cell, "plain")
                    else str(account_cell)
                )
                if plain == "assets:bank:checking":
                    target_row = row
                    break
            assert target_row is not None, (
                "assets:bank:checking row not found; rows: "
                + repr(
                    [
                        (
                            table.get_row_at(i)[0].plain
                            if hasattr(table.get_row_at(i)[0], "plain")
                            else str(table.get_row_at(i)[0])
                        )
                        for i in range(table.row_count)
                    ]
                )
            )
            balance_cell = target_row[1]
            balance_plain = (
                balance_cell.plain
                if hasattr(balance_cell, "plain")
                else str(balance_cell)
            )
            assert "€" in balance_plain
            assert "£" not in balance_plain
            assert "\n" not in balance_plain


class TestAccountsRowHeight:
    """Multi-currency rows must be tall enough to render every stacked line."""

    @pytest.fixture(autouse=True)
    def _default_flat_view(self, monkeypatch: pytest.MonkeyPatch):
        """Flat mode at startup; config writes stubbed out."""
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.load_accounts_view",
            lambda: "flat",
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.save_accounts_view",
            lambda _mode: None,
        )

    async def test_flat_multi_currency_row_has_multi_line_height(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A stacked multi-currency balance cell renders at height >= 2."""
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.resolve_default_commodity",
            lambda _file: None,
        )
        journal = tmp_path / "multi.journal"
        journal.write_text(
            "2026-01-01 * opening\n"
            "    assets:bank:checking      €100.00\n"
            "    assets:bank:checking       £50.00\n"
            "    assets:bank:savings        €42.00\n"
            "    equity:opening-balances\n"
        )
        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await wait_until(pilot, lambda: _accounts_rows(app) > 0)
            table = app.screen.query_one("#accounts-table")
            keys = {rk.value: rk for rk in table.rows.keys() if rk.value}
            target = keys.get("assets:bank:checking")
            assert target is not None, (
                f"assets:bank:checking row not found; keys: {sorted(keys)}"
            )
            height = table.get_row_height(target)
            assert height >= 2, (
                f"multi-currency row height is {height}; stacked currencies clipped"
            )

    async def test_flat_single_currency_row_stays_single_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A single-currency balance cell renders at height 1."""
        monkeypatch.setattr(
            "hledger_textual.widgets.accounts_pane.resolve_default_commodity",
            lambda _file: None,
        )
        journal = tmp_path / "multi.journal"
        journal.write_text(
            "2026-01-01 * opening\n"
            "    assets:bank:checking      €100.00\n"
            "    assets:bank:checking       £50.00\n"
            "    assets:bank:savings        €42.00\n"
            "    equity:opening-balances\n"
        )
        app = HledgerTuiApp(journal_file=journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("6")
            await wait_until(pilot, lambda: _accounts_rows(app) > 0)
            table = app.screen.query_one("#accounts-table")
            keys = {rk.value: rk for rk in table.rows.keys() if rk.value}
            target = keys.get("assets:bank:savings")
            assert target is not None
            height = table.get_row_height(target)
            assert height == 1, f"single-currency row height is {height}"
