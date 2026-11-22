"""Tests for read-only mode (issue #271)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.config import load_read_only, parse_args
from hledger_textual.models import Transaction
from hledger_textual.widgets.pane_mixin import (
    READ_ONLY_MESSAGE,
    is_read_only,
    run_mutation,
    refuse_read_only,
)
from tests.conftest import has_hledger, wait_until


class TestReadOnlyHelpers:
    """Unit tests for the read-only guard helpers."""

    def _widget(self, read_only) -> SimpleNamespace:
        """A widget double whose app exposes the given read_only value."""
        app = SimpleNamespace(read_only=read_only)
        app.notify = MagicMock()
        return SimpleNamespace(app=app, notify=MagicMock())

    def test_is_read_only_true(self):
        assert is_read_only(self._widget(True))

    def test_is_read_only_false(self):
        assert not is_read_only(self._widget(False))

    def test_is_read_only_missing_attribute(self):
        widget = SimpleNamespace(app=SimpleNamespace())
        assert not is_read_only(widget)

    def test_is_read_only_mock_is_not_true(self):
        """MagicMock truthiness must not enable the mode."""
        widget = SimpleNamespace(app=MagicMock())
        assert not is_read_only(widget)

    def test_refuse_read_only_notifies_and_blocks(self):
        widget = self._widget(True)
        assert refuse_read_only(widget)
        widget.notify.assert_called_once()
        assert READ_ONLY_MESSAGE in widget.notify.call_args[0]

    def test_refuse_read_only_passes_when_disabled(self):
        widget = self._widget(False)
        assert not refuse_read_only(widget)
        widget.notify.assert_not_called()

    def test_run_mutation_blocked_in_read_only(self):
        """run_mutation refuses to run the mutation in read-only mode."""
        widget = self._widget(True)
        widget.app.call_from_thread = lambda fn, *a, **k: fn(*a, **k)
        mutate = MagicMock()
        run_mutation(widget, mutate, success_message="ok", error_cls=ValueError)
        mutate.assert_not_called()


class TestReadOnlyConfig:
    """CLI flag, config key and environment variable resolution."""

    def test_parse_args_read_only(self):
        args = parse_args(["--read-only"])
        assert args.read_only is True
        args = parse_args([])
        assert args.read_only is False

    def test_config_key(self, tmp_path: Path, monkeypatch):
        config = tmp_path / "config.toml"
        config.write_text("read_only = true\n")
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config)
        assert load_read_only() is True

    def test_config_key_false(self, tmp_path: Path, monkeypatch):
        config = tmp_path / "config.toml"
        config.write_text("read_only = false\n")
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config)
        assert load_read_only() is False

    def test_missing_config_returns_false(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(
            "hledger_textual.config._CONFIG_PATH", tmp_path / "none.toml"
        )
        assert load_read_only() is False

    def test_env_var(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(
            "hledger_textual.config._CONFIG_PATH", tmp_path / "none.toml"
        )
        monkeypatch.setenv("HLEDGER_TEXTUAL_READ_ONLY", "1")
        assert load_read_only() is True


def _journal(tmp_path: Path) -> Path:
    """Write a plain journal with one transaction."""
    journal = tmp_path / "main.journal"
    journal.write_text(
        "2024-03-10 * Grocery\n    expenses:food  10.00\n    assets:checking\n"
    )
    return journal


def _ro_toasts(app: HledgerTuiApp) -> list[str]:
    """Read-only refusal toasts visible in the app's notification list."""
    return [
        str(n.message)
        for n in getattr(app, "_notifications", [])
        if "Read-only" in str(n.message)
    ]


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestReadOnlyIntegration:
    """With --read-only nothing is written and exports/search still work."""

    @pytest.fixture
    def ro_app(self, tmp_path: Path) -> HledgerTuiApp:
        """A read-only app over a single-transaction journal."""
        journal = _journal(tmp_path)
        app = HledgerTuiApp(journal_file=journal, read_only=True)
        app._journal_bytes_snapshot = journal.read_bytes()
        return app

    async def test_footer_shows_read_only(self, ro_app: HledgerTuiApp):
        """The footer carries a persistent READ-ONLY marker."""
        async with ro_app.run_test() as pilot:
            await pilot.pause()
            footer = ro_app.query_one("#footer-bar")
            assert "READ-ONLY" in str(footer.content)

    async def test_append_is_refused_without_writing(
        self, ro_app: HledgerTuiApp
    ):
        """Adding a transaction notifies and leaves the journal untouched."""
        from hledger_textual.widgets.transactions_pane import TransactionsPane

        journal = ro_app.journal_file
        txn = Transaction(
            date="2024-03-11",
            index=1,
            description="Blocked",
            postings=[],
        )
        async with ro_app.run_test(notifications=True) as pilot:
            await pilot.pause(delay=0.5)
            pane = ro_app.query_one(TransactionsPane)
            pane._do_append(txn)
            await wait_until(pilot, lambda: _ro_toasts(ro_app))
            assert journal.read_bytes() == ro_app._journal_bytes_snapshot

    async def test_budget_add_is_refused(self, ro_app: HledgerTuiApp):
        """Adding a budget rule notifies and creates no file."""
        from hledger_textual.budget import BUDGET_FILENAME, BudgetRule
        from hledger_textual.models import Amount, AmountStyle
        from hledger_textual.widgets.budget_pane import BudgetPane

        journal = ro_app.journal_file
        rule = BudgetRule(
            account="Expenses:Food",
            amount=Amount(
                commodity="€", quantity=1, style=AmountStyle()
            ),
        )
        async with ro_app.run_test(notifications=True) as pilot:
            await pilot.pause(delay=0.5)
            ro_app._activate_section("budget")
            await pilot.pause(delay=0.5)
            pane = ro_app.query_one(BudgetPane)
            pane._do_add(rule)
            await wait_until(pilot, lambda: _ro_toasts(ro_app))
            assert journal.read_bytes() == ro_app._journal_bytes_snapshot
            assert not (journal.parent / BUDGET_FILENAME).exists()

    async def test_search_still_works(self, ro_app: HledgerTuiApp):
        """Search is unaffected in read-only mode."""
        from hledger_textual.widgets.transactions_table import TransactionsTable

        async with ro_app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            ro_app._activate_section("transactions")
            await pilot.pause(delay=0.5)
            table = ro_app.query_one(TransactionsTable)
            table.apply_saved_filter("income:salary")
            await wait_until(
                pilot, lambda: table._search_query == "income:salary"
            )
            # No write happened.
            assert (
                ro_app.journal_file.read_bytes() == ro_app._journal_bytes_snapshot
            )

    async def test_period_navigation_still_works(self, ro_app: HledgerTuiApp):
        """Period navigation is unaffected in read-only mode."""
        from hledger_textual.period import year_selection

        async with ro_app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            ro_app.period_selection = year_selection(2024)
            await pilot.pause(delay=0.5)
            assert ro_app.period_selection == year_selection(2024)
            assert (
                ro_app.journal_file.read_bytes() == ro_app._journal_bytes_snapshot
            )
