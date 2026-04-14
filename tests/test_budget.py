"""Tests for budget file management."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from hledger_textual.budget import (
    BudgetError,
    _format_budget_file,
    _parse_amount_string,
    ensure_budget_file,
    parse_budget_rules,
)
from hledger_textual.models import Amount, AmountStyle, BudgetRule
from tests.conftest import has_hledger


class TestParseAmountString:
    """Tests for _parse_amount_string."""

    def test_left_commodity(self):
        """Parse amount with left-side commodity."""
        qty, commodity = _parse_amount_string("€800.00")
        assert qty == Decimal("800.00")
        assert commodity == "€"

    def test_right_commodity(self):
        """Parse amount with right-side commodity."""
        qty, commodity = _parse_amount_string("800.00EUR")
        assert qty == Decimal("800.00")
        assert commodity == "EUR"

    def test_dollar(self):
        """Parse dollar amount."""
        qty, commodity = _parse_amount_string("$150.50")
        assert qty == Decimal("150.50")
        assert commodity == "$"

    def test_empty_raises(self):
        """Empty string raises BudgetError."""
        with pytest.raises(BudgetError):
            _parse_amount_string("")

    def test_invalid_raises(self):
        """Unparseable string raises BudgetError."""
        with pytest.raises(BudgetError):
            _parse_amount_string("abc")


class TestParseBudgetRules:
    """Tests for parse_budget_rules."""

    def test_parse_sample(self, sample_budget_journal_path: Path):
        """Parse rules from sample budget journal."""
        rules = parse_budget_rules(sample_budget_journal_path)
        assert len(rules) == 2
        assert rules[0].account == "Expenses:Groceries"
        assert rules[0].amount.quantity == Decimal("800.00")
        assert rules[0].amount.commodity == "€"
        assert rules[1].account == "Expenses:Restaurant"
        assert rules[1].amount.quantity == Decimal("150.00")
        assert rules[1].amount.commodity == "€"

    def test_parse_empty_file(self, tmp_path: Path):
        """Parse empty file returns empty list."""
        budget_file = tmp_path / "empty.journal"
        budget_file.write_text("")
        assert parse_budget_rules(budget_file) == []

    def test_parse_nonexistent(self, tmp_path: Path):
        """Nonexistent file returns empty list."""
        assert parse_budget_rules(tmp_path / "nope.journal") == []

    def test_skips_assets_budget(self, sample_budget_journal_path: Path):
        """Assets:Budget balancing account is not included in rules."""
        rules = parse_budget_rules(sample_budget_journal_path)
        accounts = [r.account for r in rules]
        assert "Assets:Budget" not in accounts

    def test_parse_header_with_from_date(self, tmp_path: Path):
        """Parses rules from a periodic header with a 'from' date modifier."""
        content = (
            "~ monthly from 2023-01-01\n"
            "    Expenses:Rent                               €800.00\n"
            "    Assets:Budget\n"
        )
        budget_file = tmp_path / "budget.journal"
        budget_file.write_text(content)
        rules = parse_budget_rules(budget_file)
        assert len(rules) == 1
        assert rules[0].account == "Expenses:Rent"
        assert rules[0].amount.quantity == Decimal("800.00")

    def test_parse_header_with_from_and_to_dates(self, tmp_path: Path):
        """Parses rules from a periodic header with both 'from' and 'to' modifiers."""
        content = (
            "~ monthly from 2023-04-15 to 2023-06-16\n"
            "    Expenses:Utilities                          $400.00\n"
            "    Assets:Budget\n"
        )
        budget_file = tmp_path / "budget.journal"
        budget_file.write_text(content)
        rules = parse_budget_rules(budget_file)
        assert len(rules) == 1
        assert rules[0].account == "Expenses:Utilities"
        assert rules[0].amount.quantity == Decimal("400.00")

    def test_parse_multiple_blocks_mixed_headers(self, tmp_path: Path):
        """Parses rules from both bare and date-qualified periodic headers."""
        content = (
            "~ monthly\n"
            "    Expenses:Groceries                          €400.00\n"
            "    Assets:Budget\n"
            "\n"
            "~ monthly from 2024-01-01\n"
            "    Expenses:Rent                               €800.00\n"
            "    Assets:Budget\n"
        )
        budget_file = tmp_path / "budget.journal"
        budget_file.write_text(content)
        rules = parse_budget_rules(budget_file)
        accounts = [r.account for r in rules]
        assert "Expenses:Groceries" in accounts
        assert "Expenses:Rent" in accounts


class TestEnsureBudgetFile:
    """Tests for ensure_budget_file."""

    def test_creates_budget_file(self, tmp_path: Path):
        """Creates budget.journal if missing."""
        journal = tmp_path / "test.journal"
        journal.write_text("; some journal\n")

        budget_path = ensure_budget_file(journal)
        assert budget_path.exists()
        assert budget_path.name == "budget.journal"

    def test_adds_include_directive(self, tmp_path: Path):
        """Adds include directive to main journal."""
        journal = tmp_path / "test.journal"
        journal.write_text("; some journal\n")

        ensure_budget_file(journal)
        content = journal.read_text()
        assert "include budget.journal" in content

    def test_does_not_duplicate_include(self, tmp_path: Path):
        """Does not add include directive if already present."""
        journal = tmp_path / "test.journal"
        journal.write_text("include budget.journal\n\n; some journal\n")
        budget = tmp_path / "budget.journal"
        budget.write_text("")

        ensure_budget_file(journal)
        content = journal.read_text()
        assert content.count("include budget.journal") == 1

    def test_idempotent(self, tmp_path: Path):
        """Calling twice is safe."""
        journal = tmp_path / "test.journal"
        journal.write_text("; some journal\n")

        ensure_budget_file(journal)
        ensure_budget_file(journal)

        content = journal.read_text()
        assert content.count("include budget.journal") == 1


class TestFormatBudgetFile:
    """Tests for _format_budget_file."""

    def test_empty_rules(self):
        """Empty rules list produces empty content."""
        assert _format_budget_file([]) == ""

    def test_format_rules(self, euro_style: AmountStyle):
        """Formats rules as periodic transaction."""
        rules = [
            BudgetRule(
                account="Expenses:Groceries",
                amount=Amount(commodity="€", quantity=Decimal("800.00"), style=euro_style),
            ),
            BudgetRule(
                account="Expenses:Restaurant",
                amount=Amount(commodity="€", quantity=Decimal("150.00"), style=euro_style),
            ),
        ]
        content = _format_budget_file(rules)
        assert "~ monthly" in content
        assert "Expenses:Groceries" in content
        assert "€800.00" in content
        assert "Expenses:Restaurant" in content
        assert "€150.00" in content
        assert "Assets:Budget" in content

    def test_roundtrip(self, sample_budget_journal_path: Path):
        """Parse then format produces valid content that can be re-parsed."""
        rules = parse_budget_rules(sample_budget_journal_path)
        content = _format_budget_file(rules)
        tmp_path = sample_budget_journal_path.parent / "roundtrip.journal"
        try:
            tmp_path.write_text(content)
            reparsed = parse_budget_rules(tmp_path)
            assert len(reparsed) == len(rules)
            for orig, rt in zip(rules, reparsed):
                assert orig.account == rt.account
                assert orig.amount.quantity == rt.amount.quantity
                assert orig.amount.commodity == rt.amount.commodity
        finally:
            tmp_path.unlink(missing_ok=True)


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestBudgetCRUD:
    """Integration tests for budget CRUD operations (require hledger)."""

    def test_add_rule(self, tmp_journal_with_budget: Path):
        """Add a budget rule."""
        from hledger_textual.budget import add_budget_rule

        budget_path = tmp_journal_with_budget.parent / "budget.journal"
        new_rule = BudgetRule(
            account="Expenses:Transport",
            amount=Amount(
                commodity="€",
                quantity=Decimal("100.00"),
                style=AmountStyle(commodity_side="L", commodity_spaced=False, precision=2),
            ),
        )
        add_budget_rule(budget_path, new_rule, tmp_journal_with_budget)
        rules = parse_budget_rules(budget_path)
        accounts = [r.account for r in rules]
        assert "Expenses:Transport" in accounts

    def test_add_duplicate_raises(self, tmp_journal_with_budget: Path):
        """Adding a duplicate account raises BudgetError."""
        from hledger_textual.budget import add_budget_rule

        budget_path = tmp_journal_with_budget.parent / "budget.journal"
        dup_rule = BudgetRule(
            account="Expenses:Groceries",
            amount=Amount(
                commodity="€",
                quantity=Decimal("500.00"),
                style=AmountStyle(commodity_side="L", commodity_spaced=False, precision=2),
            ),
        )
        with pytest.raises(BudgetError, match="already exists"):
            add_budget_rule(budget_path, dup_rule, tmp_journal_with_budget)

    def test_update_rule(self, tmp_journal_with_budget: Path):
        """Update an existing budget rule."""
        from hledger_textual.budget import update_budget_rule

        budget_path = tmp_journal_with_budget.parent / "budget.journal"
        new_rule = BudgetRule(
            account="Expenses:Groceries",
            amount=Amount(
                commodity="€",
                quantity=Decimal("900.00"),
                style=AmountStyle(commodity_side="L", commodity_spaced=False, precision=2),
            ),
        )
        update_budget_rule(budget_path, "Expenses:Groceries", new_rule, tmp_journal_with_budget)
        rules = parse_budget_rules(budget_path)
        grocery_rule = next(r for r in rules if r.account == "Expenses:Groceries")
        assert grocery_rule.amount.quantity == Decimal("900.00")

    def test_delete_rule(self, tmp_journal_with_budget: Path):
        """Delete a budget rule."""
        from hledger_textual.budget import delete_budget_rule

        budget_path = tmp_journal_with_budget.parent / "budget.journal"
        delete_budget_rule(budget_path, "Expenses:Restaurant", tmp_journal_with_budget)
        rules = parse_budget_rules(budget_path)
        accounts = [r.account for r in rules]
        assert "Expenses:Restaurant" not in accounts

    def test_delete_nonexistent_raises(self, tmp_journal_with_budget: Path):
        """Deleting a nonexistent rule raises BudgetError."""
        from hledger_textual.budget import delete_budget_rule

        budget_path = tmp_journal_with_budget.parent / "budget.journal"
        with pytest.raises(BudgetError, match="No budget rule found"):
            delete_budget_rule(budget_path, "Expenses:Nope", tmp_journal_with_budget)


class TestBudgetRuleCategory:
    """Tests for category field on BudgetRule (parse, format, roundtrip)."""

    def test_parse_rule_with_category(self, tmp_path: Path):
        """Parses category from inline posting comment."""
        content = (
            "~ monthly\n"
            "    Expenses:Rent                               €800.00  ; category: Fixed\n"
            "    Expenses:Groceries                          €400.00  ; category: Food\n"
            "    Assets:Budget\n"
        )
        budget_file = tmp_path / "budget.journal"
        budget_file.write_text(content)
        rules = parse_budget_rules(budget_file)
        assert len(rules) == 2
        assert rules[0].category == "Fixed"
        assert rules[1].category == "Food"

    def test_parse_rule_without_category(self, tmp_path: Path):
        """Rules without category comment get empty string category."""
        content = (
            "~ monthly\n"
            "    Expenses:Groceries                          €800.00\n"
            "    Assets:Budget\n"
        )
        budget_file = tmp_path / "budget.journal"
        budget_file.write_text(content)
        rules = parse_budget_rules(budget_file)
        assert len(rules) == 1
        assert rules[0].category == ""

    def test_format_rule_with_category(self, euro_style: AmountStyle):
        """Formats rule with category as inline posting comment."""
        rule = BudgetRule(
            account="Expenses:Rent",
            amount=Amount(commodity="€", quantity=Decimal("800.00"), style=euro_style),
            category="Fixed",
        )
        content = _format_budget_file([rule])
        assert "; category: Fixed" in content

    def test_format_rule_without_category(self, euro_style: AmountStyle):
        """Formats rule without category — no comment appended."""
        rule = BudgetRule(
            account="Expenses:Groceries",
            amount=Amount(commodity="€", quantity=Decimal("400.00"), style=euro_style),
        )
        content = _format_budget_file([rule])
        assert "; category:" not in content

    def test_category_roundtrip(self, tmp_path: Path, euro_style: AmountStyle):
        """Category survives a format → write → parse roundtrip."""
        rules = [
            BudgetRule(
                account="Expenses:Rent",
                amount=Amount(commodity="€", quantity=Decimal("800.00"), style=euro_style),
                category="Fixed",
            ),
            BudgetRule(
                account="Expenses:Groceries",
                amount=Amount(commodity="€", quantity=Decimal("400.00"), style=euro_style),
                category="Food",
            ),
            BudgetRule(
                account="Expenses:Other",
                amount=Amount(commodity="€", quantity=Decimal("50.00"), style=euro_style),
            ),
        ]
        budget_file = tmp_path / "budget.journal"
        budget_file.write_text(_format_budget_file(rules))
        reparsed = parse_budget_rules(budget_file)
        assert reparsed[0].category == "Fixed"
        assert reparsed[1].category == "Food"
        assert reparsed[2].category == ""


class TestBudgetAlertThreshold:
    """Tests for load_budget_alert_threshold config helper."""

    def test_returns_none_when_absent(self, tmp_path: Path, monkeypatch):
        """Returns None when [budget] alert_threshold is not configured."""
        from hledger_textual import config as cfg
        monkeypatch.setattr(cfg, "_load_config_dict", lambda: {})
        from hledger_textual.config import load_budget_alert_threshold
        assert load_budget_alert_threshold() is None

    def test_returns_float_when_configured(self, monkeypatch):
        """Returns the configured threshold as a float."""
        from hledger_textual import config as cfg
        monkeypatch.setattr(cfg, "_load_config_dict", lambda: {"budget": {"alert_threshold": 80}})
        from hledger_textual.config import load_budget_alert_threshold
        assert load_budget_alert_threshold() == 80.0

    def test_returns_none_for_invalid_value(self, monkeypatch):
        """Returns None for non-numeric values."""
        from hledger_textual import config as cfg
        monkeypatch.setattr(cfg, "_load_config_dict", lambda: {"budget": {"alert_threshold": "bad"}})
        from hledger_textual.config import load_budget_alert_threshold
        assert load_budget_alert_threshold() is None

    def test_returns_none_for_zero(self, monkeypatch):
        """Returns None for threshold of 0 (out of valid range)."""
        from hledger_textual import config as cfg
        monkeypatch.setattr(cfg, "_load_config_dict", lambda: {"budget": {"alert_threshold": 0}})
        from hledger_textual.config import load_budget_alert_threshold
        assert load_budget_alert_threshold() is None
