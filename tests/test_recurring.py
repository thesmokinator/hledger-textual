"""Tests for recurring transaction file management."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from hledger_textual.models import (
    Amount,
    AmountStyle,
    Posting,
    RecurringRule,
    TransactionStatus,
)
from hledger_textual.recurring import (
    RecurringError,
    _format_recurring_file,
    _parse_amount_string,
    ensure_recurring_file,
    generate_rule_id,
    parse_recurring_rules,
)
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

    def test_empty_raises(self):
        """Empty string raises RecurringError."""
        with pytest.raises(RecurringError):
            _parse_amount_string("")

    def test_invalid_raises(self):
        """Unparseable string raises RecurringError."""
        with pytest.raises(RecurringError):
            _parse_amount_string("abc")


class TestParseRecurringRules:
    """Tests for parse_recurring_rules."""

    def test_parse_sample(self, sample_recurring_journal_path: Path):
        """Parse rules from sample recurring journal."""
        rules = parse_recurring_rules(sample_recurring_journal_path)
        assert len(rules) == 2

        assert rules[0].rule_id == "rent-001"
        assert rules[0].period_expr == "monthly"
        assert rules[0].description == "Rent payment"
        assert rules[0].last_generated == "2026-02-01"
        assert len(rules[0].postings) == 2
        assert rules[0].postings[0].account == "Expenses:Rent"
        assert rules[0].postings[0].amounts[0].quantity == Decimal("800.00")
        assert rules[0].postings[1].account == "Assets:Bank:Checking"
        assert rules[0].postings[1].amounts == []

        assert rules[1].rule_id == "grocery-001"
        assert rules[1].period_expr == "every 2 weeks"
        assert rules[1].description == "Grocery run"
        assert rules[1].last_generated is None
        assert len(rules[1].postings) == 2

    def test_parse_empty_file(self, tmp_path: Path):
        """Parse empty file returns empty list."""
        recurring_file = tmp_path / "empty.journal"
        recurring_file.write_text("")
        assert parse_recurring_rules(recurring_file) == []

    def test_parse_nonexistent(self, tmp_path: Path):
        """Nonexistent file returns empty list."""
        assert parse_recurring_rules(tmp_path / "nope.journal") == []

    def test_parse_with_status(self, tmp_path: Path):
        """Parse rule with cleared status."""
        recurring_file = tmp_path / "status.journal"
        recurring_file.write_text(
            "~ monthly  * Cleared rent  ; recurring-id:r-001\n"
            "    Expenses:Rent                                   €800.00\n"
            "    Assets:Bank:Checking\n"
        )
        rules = parse_recurring_rules(recurring_file)
        assert len(rules) == 1
        assert rules[0].status == TransactionStatus.CLEARED
        assert rules[0].description == "Cleared rent"

    def test_parse_with_code(self, tmp_path: Path):
        """Parse rule with code."""
        recurring_file = tmp_path / "code.journal"
        recurring_file.write_text(
            "~ monthly  (INV-001) Rent  ; recurring-id:r-002\n"
            "    Expenses:Rent                                   €800.00\n"
            "    Assets:Bank:Checking\n"
        )
        rules = parse_recurring_rules(recurring_file)
        assert len(rules) == 1
        assert rules[0].code == "INV-001"
        assert rules[0].description == "Rent"


class TestEnsureRecurringFile:
    """Tests for ensure_recurring_file."""

    def test_creates_recurring_file(self, tmp_path: Path):
        """Creates recurring.journal if missing."""
        journal = tmp_path / "test.journal"
        journal.write_text("; some journal\n")

        recurring_path = ensure_recurring_file(journal)
        assert recurring_path.exists()
        assert recurring_path.name == "recurring.journal"

    def test_adds_include_directive(self, tmp_path: Path):
        """Adds include directive to main journal."""
        journal = tmp_path / "test.journal"
        journal.write_text("; some journal\n")

        ensure_recurring_file(journal)
        content = journal.read_text()
        assert "include recurring.journal" in content

    def test_does_not_duplicate_include(self, tmp_path: Path):
        """Does not add include directive if already present."""
        journal = tmp_path / "test.journal"
        journal.write_text("include recurring.journal\n\n; some journal\n")
        recurring = tmp_path / "recurring.journal"
        recurring.write_text("")

        ensure_recurring_file(journal)
        content = journal.read_text()
        assert content.count("include recurring.journal") == 1

    def test_idempotent(self, tmp_path: Path):
        """Calling twice is safe."""
        journal = tmp_path / "test.journal"
        journal.write_text("; some journal\n")

        ensure_recurring_file(journal)
        ensure_recurring_file(journal)

        content = journal.read_text()
        assert content.count("include recurring.journal") == 1


class TestFormatRecurringFile:
    """Tests for _format_recurring_file."""

    def test_empty_rules(self):
        """Empty rules list produces empty content."""
        assert _format_recurring_file([]) == ""

    def test_format_rules(self, euro_style: AmountStyle):
        """Formats rules as periodic transactions."""
        rules = [
            RecurringRule(
                rule_id="rent-001",
                period_expr="monthly",
                description="Rent payment",
                postings=[
                    Posting(
                        account="Expenses:Rent",
                        amounts=[Amount(commodity="€", quantity=Decimal("800.00"), style=euro_style)],
                    ),
                    Posting(account="Assets:Bank:Checking"),
                ],
                last_generated="2026-02-01",
            ),
        ]
        content = _format_recurring_file(rules)
        assert "~ monthly" in content
        assert "Rent payment" in content
        assert "recurring-id:rent-001" in content
        assert "last-generated:2026-02-01" in content
        assert "€800.00" in content
        assert "Assets:Bank:Checking" in content

    def test_roundtrip(self, sample_recurring_journal_path: Path):
        """Parse then format produces valid content that can be re-parsed."""
        rules = parse_recurring_rules(sample_recurring_journal_path)
        content = _format_recurring_file(rules)
        tmp_path = sample_recurring_journal_path.parent / "roundtrip_recurring.journal"
        try:
            tmp_path.write_text(content)
            reparsed = parse_recurring_rules(tmp_path)
            assert len(reparsed) == len(rules)
            for orig, rt in zip(rules, reparsed):
                assert orig.rule_id == rt.rule_id
                assert orig.period_expr == rt.period_expr
                assert orig.description == rt.description
                assert orig.last_generated == rt.last_generated
                assert len(orig.postings) == len(rt.postings)
        finally:
            tmp_path.unlink(missing_ok=True)


class TestGenerateRuleId:
    """Tests for generate_rule_id."""

    def test_generates_slug(self):
        """Generates a slug-based ID."""
        rule_id = generate_rule_id("Rent payment")
        assert rule_id.startswith("rent-payment-")
        assert len(rule_id) > len("rent-payment-")

    def test_unique(self):
        """Multiple calls produce different IDs."""
        ids = {generate_rule_id("Test") for _ in range(10)}
        assert len(ids) == 10

    def test_empty_description(self):
        """Empty description produces valid ID."""
        rule_id = generate_rule_id("")
        assert rule_id.startswith("rule-")


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestRecurringCRUD:
    """Integration tests for recurring CRUD operations (require hledger)."""

    def test_add_rule(self, tmp_journal_with_recurring: Path):
        """Add a recurring rule."""
        from hledger_textual.recurring import add_recurring_rule

        recurring_path = tmp_journal_with_recurring.parent / "recurring.journal"
        new_rule = RecurringRule(
            rule_id="transport-001",
            period_expr="monthly",
            description="Train pass",
            postings=[
                Posting(
                    account="Expenses:Transport",
                    amounts=[
                        Amount(
                            commodity="€",
                            quantity=Decimal("100.00"),
                            style=AmountStyle(commodity_side="L", commodity_spaced=False, precision=2),
                        )
                    ],
                ),
                Posting(account="Assets:Bank:Checking"),
            ],
        )
        add_recurring_rule(recurring_path, new_rule, tmp_journal_with_recurring)
        rules = parse_recurring_rules(recurring_path)
        rule_ids = [r.rule_id for r in rules]
        assert "transport-001" in rule_ids

    def test_add_duplicate_raises(self, tmp_journal_with_recurring: Path):
        """Adding a duplicate rule_id raises RecurringError."""
        from hledger_textual.recurring import add_recurring_rule

        recurring_path = tmp_journal_with_recurring.parent / "recurring.journal"
        dup_rule = RecurringRule(
            rule_id="rent-001",
            period_expr="weekly",
            description="Duplicate",
            postings=[
                Posting(
                    account="Expenses:Other",
                    amounts=[
                        Amount(
                            commodity="€",
                            quantity=Decimal("50.00"),
                            style=AmountStyle(commodity_side="L", commodity_spaced=False, precision=2),
                        )
                    ],
                ),
                Posting(account="Assets:Bank:Checking"),
            ],
        )
        with pytest.raises(RecurringError, match="already exists"):
            add_recurring_rule(recurring_path, dup_rule, tmp_journal_with_recurring)

    def test_update_rule(self, tmp_journal_with_recurring: Path):
        """Update an existing recurring rule."""
        from hledger_textual.recurring import update_recurring_rule

        recurring_path = tmp_journal_with_recurring.parent / "recurring.journal"
        new_rule = RecurringRule(
            rule_id="rent-001",
            period_expr="monthly",
            description="Updated rent",
            postings=[
                Posting(
                    account="Expenses:Rent",
                    amounts=[
                        Amount(
                            commodity="€",
                            quantity=Decimal("900.00"),
                            style=AmountStyle(commodity_side="L", commodity_spaced=False, precision=2),
                        )
                    ],
                ),
                Posting(account="Assets:Bank:Checking"),
            ],
            last_generated="2026-02-01",
        )
        update_recurring_rule(recurring_path, "rent-001", new_rule, tmp_journal_with_recurring)
        rules = parse_recurring_rules(recurring_path)
        rent_rule = next(r for r in rules if r.rule_id == "rent-001")
        assert rent_rule.description == "Updated rent"
        assert rent_rule.postings[0].amounts[0].quantity == Decimal("900.00")

    def test_delete_rule(self, tmp_journal_with_recurring: Path):
        """Delete a recurring rule."""
        from hledger_textual.recurring import delete_recurring_rule

        recurring_path = tmp_journal_with_recurring.parent / "recurring.journal"
        delete_recurring_rule(recurring_path, "grocery-001", tmp_journal_with_recurring)
        rules = parse_recurring_rules(recurring_path)
        rule_ids = [r.rule_id for r in rules]
        assert "grocery-001" not in rule_ids

    def test_delete_nonexistent_raises(self, tmp_journal_with_recurring: Path):
        """Deleting a nonexistent rule raises RecurringError."""
        from hledger_textual.recurring import delete_recurring_rule

        recurring_path = tmp_journal_with_recurring.parent / "recurring.journal"
        with pytest.raises(RecurringError, match="No recurring rule found"):
            delete_recurring_rule(recurring_path, "nope-999", tmp_journal_with_recurring)

    def test_update_last_generated(self, tmp_journal_with_recurring: Path):
        """Update last_generated date for a rule."""
        from hledger_textual.recurring import update_last_generated

        recurring_path = tmp_journal_with_recurring.parent / "recurring.journal"
        update_last_generated(recurring_path, "rent-001", "2026-03-01", tmp_journal_with_recurring)
        rules = parse_recurring_rules(recurring_path)
        rent_rule = next(r for r in rules if r.rule_id == "rent-001")
        assert rent_rule.last_generated == "2026-03-01"
