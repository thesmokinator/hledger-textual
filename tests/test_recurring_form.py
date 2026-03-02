"""Tests for the RecurringFormScreen modal (save logic, validation, buttons)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from textual.app import App, ComposeResult
from textual.widgets import Input, Select, Static

from hledger_textual.models import (
    Amount,
    AmountStyle,
    Posting,
    RecurringRule,
    TransactionStatus,
)
from hledger_textual.screens.recurring_form import RecurringFormScreen
from tests.conftest import has_hledger


class _FormApp(App):
    """Minimal app that opens a RecurringFormScreen modal for isolated testing."""

    def __init__(self, journal_file: Path, rule: RecurringRule | None = None) -> None:
        """Initialize with a journal file path and optional rule for edit mode."""
        super().__init__()
        self._journal_file = journal_file
        self._rule = rule
        self.results: list[RecurringRule | None] = []

    def compose(self) -> ComposeResult:
        """Compose a placeholder widget under the modal."""
        yield Static("test")

    def on_mount(self) -> None:
        """Push the form modal immediately on mount."""
        self.push_screen(
            RecurringFormScreen(self._journal_file, rule=self._rule),
            callback=self.results.append,
        )


class TestRecurringFormSave:
    """Tests for valid and invalid form submissions."""

    async def test_valid_form_dismisses_with_rule(self, tmp_path: Path):
        """Saving with valid data dismisses the modal with a RecurringRule."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            # Period defaults to "monthly"
            form.query_one("#recurring-input-description", Input).value = "Rent"
            # Add accounts to posting rows
            from hledger_textual.widgets.posting_row import PostingRow
            rows = list(form.query_one("#recurring-postings-container").query(PostingRow))
            rows[0].query_one(f"#account-0", Input).value = "Expenses:Rent"
            rows[0].query_one(f"#amount-0", Input).value = "800.00"
            rows[1].query_one(f"#account-1", Input).value = "Assets:Bank"
            form._save()
            await pilot.pause()
            assert len(app.results) == 1
            rule = app.results[0]
            assert isinstance(rule, RecurringRule)
            assert rule.description == "Rent"
            assert rule.period_expr == "monthly"
            assert len(rule.postings) == 2

    async def test_empty_description_rejected(self, tmp_path: Path):
        """Empty description keeps the form open."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form.query_one("#recurring-input-description", Input).value = ""
            form._save()
            await pilot.pause()
            assert isinstance(app.screen, RecurringFormScreen)
            assert app.results == []

    async def test_insufficient_postings_rejected(self, tmp_path: Path):
        """Less than 2 postings with accounts keeps the form open."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form.query_one("#recurring-input-description", Input).value = "Test"
            # Only fill one posting
            from hledger_textual.widgets.posting_row import PostingRow
            rows = list(form.query_one("#recurring-postings-container").query(PostingRow))
            rows[0].query_one(f"#account-0", Input).value = "Expenses:Rent"
            rows[0].query_one(f"#amount-0", Input).value = "800.00"
            # Leave second posting empty
            form._save()
            await pilot.pause()
            assert isinstance(app.screen, RecurringFormScreen)
            assert app.results == []

    async def test_cancel_button_dismisses_with_none(self, tmp_path: Path):
        """Clicking Cancel dismisses the modal with None."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click(app.screen.query_one("#btn-recurring-cancel"))
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


class TestRecurringFormEditMode:
    """Tests for RecurringFormScreen in edit mode."""

    @pytest.fixture
    def sample_rule(self) -> RecurringRule:
        """A sample RecurringRule for edit-mode testing."""
        style = AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)
        return RecurringRule(
            rule_id="rent-001",
            period_expr="monthly",
            description="Rent payment",
            postings=[
                Posting(
                    account="Expenses:Rent",
                    amounts=[Amount(commodity="€", quantity=Decimal("800.00"), style=style)],
                ),
                Posting(account="Assets:Bank:Checking"),
            ],
            last_generated="2026-02-01",
        )

    async def test_edit_form_is_detected_as_edit(self, tmp_path: Path, sample_rule):
        """is_edit property is True when a rule is provided."""
        app = _FormApp(tmp_path / "test.journal", rule=sample_rule)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.is_edit is True

    async def test_edit_form_prefills_description(self, tmp_path: Path, sample_rule):
        """Edit form pre-fills the description field."""
        app = _FormApp(tmp_path / "test.journal", rule=sample_rule)
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            assert form.query_one("#recurring-input-description", Input).value == "Rent payment"

    async def test_edit_form_preserves_rule_id(self, tmp_path: Path, sample_rule):
        """Edit form preserves the original rule_id."""
        app = _FormApp(tmp_path / "test.journal", rule=sample_rule)
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form._save()
            await pilot.pause()
            assert len(app.results) == 1
            saved = app.results[0]
            assert saved.rule_id == "rent-001"

    async def test_edit_form_preserves_last_generated(self, tmp_path: Path, sample_rule):
        """Edit form preserves the last_generated date."""
        app = _FormApp(tmp_path / "test.journal", rule=sample_rule)
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form._save()
            await pilot.pause()
            assert len(app.results) == 1
            saved = app.results[0]
            assert saved.last_generated == "2026-02-01"

    async def test_new_form_generates_new_rule_id(self, tmp_path: Path):
        """New form generates a fresh rule_id."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            form.query_one("#recurring-input-description", Input).value = "Test"
            from hledger_textual.widgets.posting_row import PostingRow
            rows = list(form.query_one("#recurring-postings-container").query(PostingRow))
            rows[0].query_one(f"#account-0", Input).value = "Expenses:Test"
            rows[0].query_one(f"#amount-0", Input).value = "100.00"
            rows[1].query_one(f"#account-1", Input).value = "Assets:Bank"
            form._save()
            await pilot.pause()
            assert len(app.results) == 1
            saved = app.results[0]
            assert saved.rule_id.startswith("test-")
            assert saved.last_generated is None


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestRecurringFormValidationHint:
    """Tests for real-time validation hint in the custom period field."""

    async def test_custom_period_shows_valid_hint(self, tmp_path: Path):
        """Typing a valid custom period shows a green validation hint."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            # Select "Custom..."
            form.query_one("#recurring-select-period", Select).value = "__custom__"
            await pilot.pause()
            # Type a valid expression
            form.query_one("#recurring-input-custom-period", Input).value = "every friday"
            await pilot.pause(delay=0.5)  # Wait for debounce + validation
            hint = form.query_one("#custom-period-hint", Static)
            assert hint.has_class("valid")

    async def test_custom_period_shows_invalid_hint(self, tmp_path: Path):
        """Typing an invalid custom period shows a red validation hint."""
        app = _FormApp(tmp_path / "test.journal")
        async with app.run_test() as pilot:
            await pilot.pause()
            form = app.screen
            # Select "Custom..."
            form.query_one("#recurring-select-period", Select).value = "__custom__"
            await pilot.pause()
            # Type an invalid expression
            form.query_one("#recurring-input-custom-period", Input).value = "nonsense"
            await pilot.pause(delay=0.5)  # Wait for debounce + validation
            hint = form.query_one("#custom-period-hint", Static)
            assert hint.has_class("invalid")
