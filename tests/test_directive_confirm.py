"""Tests for the directive-write preview and confirmation (issue #273)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from textual.app import App, ComposeResult
from textual.widgets import Static

from hledger_textual.config import load_confirm_directive_writes
from hledger_textual.models import DirectiveWritePlan
from hledger_textual.screens.directive_confirm import DirectiveConfirmModal
from tests.conftest import has_hledger


def _plan(tmp_path: Path, added: list[str] | None = None) -> DirectiveWritePlan:
    """A simple include-insertion plan."""
    return DirectiveWritePlan(
        target_file=tmp_path / "main.journal",
        content="include budget.journal\n\njournal\n",
        added=added or ["include budget.journal"],
    )


class _HostApp(App):
    """Minimal app that pushes the confirmation modal directly."""

    def __init__(self, plans, reason: str) -> None:
        super().__init__()
        self._plans = plans
        self._reason = reason
        self._result: tuple[bool, bool] | None | object = "unset"

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(
            DirectiveConfirmModal(self._plans, self._reason), callback=self._store
        )

    def _store(self, result) -> None:
        self._result = result


class TestDirectiveConfirmModal:
    """The modal shows the precise diff; Cancel writes nothing."""

    async def test_confirm_returns_true(self, tmp_path: Path):
        app = _HostApp([_plan(tmp_path)], "reason")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#btn-directive-confirm")
            await pilot.pause()
            assert app._result == (True, False)

    async def test_cancel_returns_none(self, tmp_path: Path):
        app = _HostApp([_plan(tmp_path)], "reason")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#btn-directive-cancel")
            await pilot.pause()
            assert app._result is None

    async def test_escape_cancels(self, tmp_path: Path):
        app = _HostApp([_plan(tmp_path)], "reason")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app._result is None

    async def test_dont_ask_is_reported(self, tmp_path: Path):
        app = _HostApp([_plan(tmp_path)], "reason")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#directive-confirm-dont-ask")
            await pilot.click("#btn-directive-confirm")
            await pilot.pause()
            assert app._result == (True, True)

    async def test_diff_shows_file_and_lines(self, tmp_path: Path):
        """The preview names the target file relative to the journal dir."""
        app = _HostApp([_plan(tmp_path)], "reason")
        async with app.run_test() as pilot:
            await pilot.pause()
            diff = app.screen.query_one("#directive-confirm-diff", Static)
            content = str(diff.content)
            assert "main.journal" in content
            assert "+ include budget.journal" in content
            assert "reason" in str(
                app.screen.query_one("#directive-confirm-reason", Static).content
            )

    async def test_new_file_creation_is_shown(self, tmp_path: Path):
        plan = DirectiveWritePlan(
            target_file=tmp_path / "budget.journal", content="", creates_file=True
        )
        app = _HostApp([plan], "reason")
        async with app.run_test() as pilot:
            await pilot.pause()
            diff = app.screen.query_one("#directive-confirm-diff", Static)
            assert "Create budget.journal" in str(diff.content)


class TestConfirmDirectiveWritesFlow:
    """The flow helper honours the config key and persists "don't ask again"."""

    def _widget(self, tmp_path: Path, auto_result=None):
        """A widget double recording pushed screens.

        With *auto_result*, the fake push_screen immediately invokes the
        callback with it (simulating the user's choice).
        """
        pushed: list[tuple] = []

        class _App:
            read_only = False

            def push_screen(self, screen, callback=None):
                pushed.append((screen, callback))
                if auto_result is not None and callback is not None:
                    callback(auto_result)

        return SimpleNamespace(app=_App(), _pushed=pushed)

    def _config(self, tmp_path, monkeypatch, text: str = "") -> None:
        """Point the config loader at a temp file."""
        config = tmp_path / "config.toml"
        config.write_text(text)
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config)

    def test_disabled_config_runs_callback_immediately(
        self, tmp_path, monkeypatch
    ):
        from hledger_textual.screens.directive_confirm import (
            confirm_directive_writes,
        )

        self._config(tmp_path, monkeypatch, 'confirm_directive_writes = "false"\n')
        widget = self._widget(tmp_path)
        called: list[str] = []
        confirm_directive_writes(
            widget,
            [_plan(tmp_path)],
            "reason",
            on_ok=lambda: called.append("ok"),
        )
        assert called == ["ok"]
        assert not widget._pushed

    def test_enabled_config_pushes_modal(self, tmp_path, monkeypatch):
        from hledger_textual.screens.directive_confirm import (
            confirm_directive_writes,
        )

        self._config(tmp_path, monkeypatch)
        widget = self._widget(tmp_path)
        confirm_directive_writes(
            widget, [_plan(tmp_path)], "reason", on_ok=lambda: None
        )
        screen, _callback = widget._pushed[0]
        assert isinstance(screen, DirectiveConfirmModal)

    def test_accept_runs_callback(self, tmp_path, monkeypatch):
        from hledger_textual.screens.directive_confirm import (
            confirm_directive_writes,
        )

        self._config(tmp_path, monkeypatch)
        widget = self._widget(tmp_path, auto_result=(True, False))
        called: list[str] = []
        confirm_directive_writes(
            widget, [_plan(tmp_path)], "reason", on_ok=lambda: called.append("ok")
        )
        assert called == ["ok"]
        assert load_confirm_directive_writes() is True

    def test_dont_ask_persists_config(self, tmp_path, monkeypatch):
        from hledger_textual.screens.directive_confirm import (
            confirm_directive_writes,
        )

        self._config(tmp_path, monkeypatch)
        widget = self._widget(tmp_path, auto_result=(True, True))
        called: list[str] = []
        confirm_directive_writes(
            widget, [_plan(tmp_path)], "reason", on_ok=lambda: called.append("ok")
        )
        assert called == ["ok"]
        assert load_confirm_directive_writes() is False

    def test_cancel_writes_nothing(self, tmp_path, monkeypatch):
        from hledger_textual.screens.directive_confirm import (
            confirm_directive_writes,
        )

        self._config(tmp_path, monkeypatch)
        widget = self._widget(tmp_path, auto_result=None)
        called: list[str] = []
        confirm_directive_writes(
            widget, [_plan(tmp_path)], "reason", on_ok=lambda: called.append("ok")
        )
        assert called == []
        assert load_confirm_directive_writes() is True

    def test_no_plans_skips_modal(self, tmp_path, monkeypatch):
        """When nothing needs to change, the callback runs without a modal."""
        from hledger_textual.screens.directive_confirm import (
            confirm_directive_writes,
        )

        self._config(tmp_path, monkeypatch)
        widget = self._widget(tmp_path)
        called: list[str] = []
        confirm_directive_writes(widget, [], "reason", on_ok=lambda: called.append("ok"))
        assert called == ["ok"]
        assert not widget._pushed


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestBudgetAddWithConfirmation:
    """Budget add previews the include write; acceptance writes exactly once."""

    def _journal(self, tmp_path: Path) -> Path:
        journal = tmp_path / "main.journal"
        journal.write_text(
            "2024-03-10 * Grocery\n    expenses:food  10.00\n    assets:checking\n"
        )
        return journal

    def _widget(self, auto_result):
        """A widget double that auto-answers the confirmation modal."""
        pushed: list[tuple] = []

        class _App:
            read_only = False

            def push_screen(self, screen, callback=None):
                pushed.append((screen, callback))
                if callback is not None:
                    callback(auto_result)

        return SimpleNamespace(app=_App(), _pushed=pushed)

    def test_accept_writes_exactly_once(self, tmp_path: Path):
        from hledger_textual.budget import (
            BUDGET_FILENAME,
            BudgetRule,
            add_budget_rule,
            include_insert_plans,
        )
        from hledger_textual.models import Amount, AmountStyle
        from hledger_textual.screens.directive_confirm import confirm_directive_writes

        journal = self._journal(tmp_path)
        rule = BudgetRule(
            account="Expenses:Food",
            amount=Amount(commodity="€", quantity=1, style=AmountStyle()),
        )

        plans = include_insert_plans(journal)
        assert plans, "expected an include-insertion plan"

        confirm_directive_writes(
            self._widget((True, False)),
            plans,
            "reason",
            on_ok=lambda: add_budget_rule(
                journal.parent / BUDGET_FILENAME, rule, journal
            ),
        )

        text = journal.read_text()
        assert text.count("include budget.journal") == 1
        assert (journal.parent / BUDGET_FILENAME).exists()

    def test_cancel_writes_nothing(self, tmp_path: Path):
        from hledger_textual.budget import (
            BUDGET_FILENAME,
            BudgetRule,
            add_budget_rule,
            include_insert_plans,
        )
        from hledger_textual.models import Amount, AmountStyle
        from hledger_textual.screens.directive_confirm import confirm_directive_writes

        journal = self._journal(tmp_path)
        before = journal.read_bytes()
        rule = BudgetRule(
            account="Expenses:Food",
            amount=Amount(commodity="€", quantity=1, style=AmountStyle()),
        )

        confirm_directive_writes(
            self._widget(None),
            include_insert_plans(journal),
            "reason",
            on_ok=lambda: add_budget_rule(
                journal.parent / BUDGET_FILENAME, rule, journal
            ),
        )

        assert journal.read_bytes() == before
        assert not (journal.parent / BUDGET_FILENAME).exists()
