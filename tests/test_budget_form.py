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
            await pilot.pause(delay=0.5)
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

    async def test_edit_form_prefills_category(self, tmp_path: Path, euro_style):
        """Edit form pre-fills the category field from the existing rule."""
        rule = BudgetRule(
            account="Expenses:Groceries",
            amount=Amount(commodity="€", quantity=Decimal("800.00"), style=euro_style),
            category="Food",
        )
        app = _FormApp(tmp_path / "test.journal", rule=rule)
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            assert form.query_one("#budget-input-category", Input).value == "Food"


class TestBudgetFormCategory:
    """Tests for the Category field in BudgetFormScreen."""

    async def test_new_form_category_empty_by_default(self, tmp_path: Path):
        """New rule form has empty category field."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            assert form.query_one("#budget-input-category", Input).value == ""

    async def test_category_saved_with_rule(self, tmp_path: Path):
        """Category value is included in the returned BudgetRule."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form.query_one("#budget-input-account", Input).value = "Expenses:Rent"
            form.query_one("#budget-input-amount", Input).value = "800.00"
            form.query_one("#budget-input-commodity", Input).value = "€"
            form.query_one("#budget-input-category", Input).value = "Fixed"
            await pilot.click(form.query_one("#btn-budget-save"))
            await pilot.pause()
            assert len(app.results) == 1
            assert app.results[0].category == "Fixed"

    async def test_empty_category_saves_as_empty_string(self, tmp_path: Path):
        """Leaving category blank saves an empty string (not None)."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form.query_one("#budget-input-account", Input).value = "Expenses:Food"
            form.query_one("#budget-input-amount", Input).value = "200.00"
            form.query_one("#budget-input-commodity", Input).value = "€"
            await pilot.click(form.query_one("#btn-budget-save"))
            await pilot.pause()
            assert len(app.results) == 1
            assert app.results[0].category == ""


class TestBudgetFormUnknownAccountWarning:
    """Tests for the on-blur inline warning when the account is not in the journal."""

    async def test_warns_when_account_unknown_after_blur(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Typing an unknown account and tabbing away shows the inline warning widget."""
        from hledger_textual.screens import budget_form

        # Pretend the journal already knows about a couple of accounts so the
        # form has something to compare against.
        monkeypatch.setattr(
            budget_form,
            "load_accounts",
            lambda _path: ["Expenses:Food", "Expenses:Rent", "Income:Salary"],
        )

        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen

            account_input = form.query_one("#budget-input-account", Input)
            warning = form.query_one("#budget-account-warning", Static)
            # Warning starts hidden with empty content.
            assert warning.has_class("hidden")
            assert str(warning.renderable) == ""

            account_input.value = "Expenses:Groceres"  # typo, not in known list
            account_input.focus()
            await pilot.pause()
            # Move focus away from the account field to fire the blur event.
            form.query_one("#budget-input-amount", Input).focus()
            await pilot.pause()

            rendered = str(warning.renderable)
            assert not warning.has_class("hidden"), "Warning widget should be visible after blur on unknown account"
            assert "Expenses:Groceres" in rendered and "not found" in rendered, (
                f"Expected unknown-account inline warning, got {rendered!r}"
            )

    async def test_no_warning_when_account_is_known(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Tabbing away from a known account keeps the inline warning hidden."""
        from hledger_textual.screens import budget_form

        monkeypatch.setattr(
            budget_form,
            "load_accounts",
            lambda _path: ["Expenses:Food", "Expenses:Rent"],
        )

        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen

            account_input = form.query_one("#budget-input-account", Input)
            warning = form.query_one("#budget-account-warning", Static)

            account_input.value = "Expenses:Food"
            account_input.focus()
            await pilot.pause()
            form.query_one("#budget-input-amount", Input).focus()
            await pilot.pause()

            assert warning.has_class("hidden"), "Warning should stay hidden for known accounts"
            assert str(warning.renderable) == ""

    async def test_no_warning_when_journal_has_no_accounts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """If load_accounts returns nothing, blur leaves the warning hidden (fresh journal)."""
        from hledger_textual.screens import budget_form

        monkeypatch.setattr(budget_form, "load_accounts", lambda _path: [])

        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen

            account_input = form.query_one("#budget-input-account", Input)
            warning = form.query_one("#budget-account-warning", Static)

            account_input.value = "Anything:Goes"
            account_input.focus()
            await pilot.pause()
            form.query_one("#budget-input-amount", Input).focus()
            await pilot.pause()

            assert warning.has_class("hidden")
            assert str(warning.renderable) == ""

    async def test_warning_cleared_after_correcting_to_known_account(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Fixing a typo to a known account hides the previously-shown warning on the next blur."""
        from hledger_textual.screens import budget_form

        monkeypatch.setattr(
            budget_form,
            "load_accounts",
            lambda _path: ["Expenses:Food", "Expenses:Rent"],
        )

        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen

            account_input = form.query_one("#budget-input-account", Input)
            amount_input = form.query_one("#budget-input-amount", Input)
            warning = form.query_one("#budget-account-warning", Static)

            # First blur: unknown account -> warning visible.
            account_input.value = "Expenses:Fod"
            account_input.focus()
            await pilot.pause()
            amount_input.focus()
            await pilot.pause()
            assert not warning.has_class("hidden")

            # Correct the account, re-focus, then blur again.
            account_input.focus()
            await pilot.pause()
            account_input.value = "Expenses:Food"
            amount_input.focus()
            await pilot.pause()
            assert warning.has_class("hidden")
            assert str(warning.renderable) == ""

    async def test_warning_is_grouped_with_account_field(self, tmp_path: Path):
        """The inline warning lives in the same field group as the account input."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen

            account_group = form.query_one(".form-field-group")
            warning = form.query_one("#budget-account-warning", Static)

            assert warning.parent is account_group
