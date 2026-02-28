"""Tests for the BudgetFormScreen modal (save logic, validation, buttons)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from hledger_textual.models import Amount, AmountStyle, BudgetRule
from hledger_textual.screens.budget_form import BudgetFormScreen


class _FormApp(App):
    """Minimal app that opens a BudgetFormScreen modal for isolated testing."""

    def __init__(self, journal_file: Path, rule: BudgetRule | None = None) -> None:
        """Initialize with a journal file path and optional rule for edit mode."""
        super().__init__()
        self._journal_file = journal_file
        self._rule = rule
        self.results: list[BudgetRule | None] = []

    def compose(self) -> ComposeResult:
        """Compose a placeholder widget under the modal."""
        yield Static("test")

    def on_mount(self) -> None:
        """Push the form modal immediately on mount."""
        self.push_screen(
            BudgetFormScreen(self._journal_file, rule=self._rule),
            callback=self.results.append,
        )


class TestBudgetFormSave:
    """Tests for valid and invalid form submissions in BudgetFormScreen._save()."""

    async def test_valid_form_dismisses_with_budget_rule(self, tmp_path: Path):
        """Clicking Save with valid data dismisses the modal with a BudgetRule."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form.query_one("#budget-input-account", Input).value = "Expenses:Food"
            form.query_one("#budget-input-amount", Input).value = "500.00"
            form.query_one("#budget-input-commodity", Input).value = "€"
            await pilot.click(form.query_one("#btn-budget-save"))
            await pilot.pause()
            assert len(app.results) == 1
            rule = app.results[0]
            assert isinstance(rule, BudgetRule)
            assert rule.account == "Expenses:Food"
            assert rule.amount.quantity == Decimal("500.00")
            assert rule.amount.commodity == "€"

    async def test_empty_account_rejected(self, tmp_path: Path):
        """Empty account field keeps the form open."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form.query_one("#budget-input-account", Input).value = ""
            form.query_one("#budget-input-amount", Input).value = "500.00"
            await pilot.click(form.query_one("#btn-budget-save"))
            await pilot.pause()
            assert isinstance(app.screen, BudgetFormScreen)
            assert app.results == []

    async def test_empty_amount_rejected(self, tmp_path: Path):
        """Empty amount field keeps the form open."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form.query_one("#budget-input-account", Input).value = "Expenses:Food"
            form.query_one("#budget-input-amount", Input).value = ""
            await pilot.click(form.query_one("#btn-budget-save"))
            await pilot.pause()
            assert isinstance(app.screen, BudgetFormScreen)
            assert app.results == []

    async def test_invalid_amount_rejected(self, tmp_path: Path):
        """Non-numeric amount keeps the form open."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form.query_one("#budget-input-account", Input).value = "Expenses:Food"
            form.query_one("#budget-input-amount", Input).value = "abc"
            await pilot.click(form.query_one("#btn-budget-save"))
            await pilot.pause()
            assert isinstance(app.screen, BudgetFormScreen)

    async def test_zero_amount_rejected(self, tmp_path: Path):
        """Zero amount keeps the form open."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form.query_one("#budget-input-account", Input).value = "Expenses:Food"
            form.query_one("#budget-input-amount", Input).value = "0"
            await pilot.click(form.query_one("#btn-budget-save"))
            await pilot.pause()
            assert isinstance(app.screen, BudgetFormScreen)

    async def test_negative_amount_rejected(self, tmp_path: Path):
        """Negative amount keeps the form open."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form.query_one("#budget-input-account", Input).value = "Expenses:Food"
            form.query_one("#budget-input-amount", Input).value = "-100.00"
            await pilot.click(form.query_one("#btn-budget-save"))
            await pilot.pause()
            assert isinstance(app.screen, BudgetFormScreen)

    async def test_empty_commodity_defaults_to_configured(self, tmp_path: Path, monkeypatch):
        """Empty commodity is replaced with the configured default symbol."""
        monkeypatch.setattr(
            "hledger_textual.screens.budget_form.load_default_commodity",
            lambda: "£",
        )
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form.query_one("#budget-input-account", Input).value = "Expenses:Food"
            form.query_one("#budget-input-amount", Input).value = "500.00"
            form.query_one("#budget-input-commodity", Input).value = ""
            await pilot.click(form.query_one("#btn-budget-save"))
            await pilot.pause()
            assert len(app.results) == 1
            assert app.results[0].amount.commodity == "£"

    async def test_cancel_button_dismisses_with_none(self, tmp_path: Path):
        """Clicking Cancel dismisses the modal with None."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click(app.screen.query_one("#btn-budget-cancel"))
            await pilot.pause()
            assert app.results == [None]

    async def test_escape_key_dismisses_with_none(self, tmp_path: Path):
        """Pressing Escape dismisses the modal with None."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.results == [None]


class TestBudgetFormEditMode:
    """Tests for BudgetFormScreen in edit mode (pre-filled from existing rule)."""

    @pytest.fixture
    def sample_rule(self) -> BudgetRule:
        """A sample BudgetRule for edit-mode testing."""
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        return BudgetRule(
            account="Expenses:Groceries",
            amount=Amount(commodity="€", quantity=Decimal("800.00"), style=style),
        )

    async def test_edit_form_is_detected_as_edit(self, tmp_path: Path, sample_rule):
        """is_edit property is True when a rule is provided."""
        app = _FormApp(tmp_path / "test.journal", rule=sample_rule)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.is_edit is True

    async def test_edit_form_prefills_account(self, tmp_path: Path, sample_rule):
        """Edit form pre-fills the account field from the existing rule."""
        app = _FormApp(tmp_path / "test.journal", rule=sample_rule)
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            assert form.query_one("#budget-input-account", Input).value == "Expenses:Groceries"

    async def test_edit_form_prefills_amount(self, tmp_path: Path, sample_rule):
        """Edit form pre-fills the amount field from the existing rule."""
        app = _FormApp(tmp_path / "test.journal", rule=sample_rule)
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            assert form.query_one("#budget-input-amount", Input).value == "800.00"

    async def test_edit_form_prefills_commodity(self, tmp_path: Path, sample_rule):
        """Edit form pre-fills the commodity field from the existing rule."""
        app = _FormApp(tmp_path / "test.journal", rule=sample_rule)
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            assert form.query_one("#budget-input-commodity", Input).value == "€"

    async def test_edit_form_saves_updated_rule(self, tmp_path: Path, sample_rule):
        """Changing the amount in edit mode saves a new rule with the updated value."""
        app = _FormApp(tmp_path / "test.journal", rule=sample_rule)
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form.query_one("#budget-input-amount", Input).value = "900.00"
            await pilot.click(form.query_one("#btn-budget-save"))
            await pilot.pause()
            assert len(app.results) == 1
            saved = app.results[0]
            assert saved.account == "Expenses:Groceries"
            assert saved.amount.quantity == Decimal("900.00")
