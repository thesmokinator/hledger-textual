"""Tests for recurring transaction file management."""

from __future__ import annotations

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from hledger_textual.models import Amount, AmountStyle, Posting, RecurringRule
from hledger_textual.recurring import (
    RECURRING_FILENAME,
    RecurringError,
    _format_recurring_file,
    _generate_occurrences,
    _parse_amount_string,
    add_recurring_rule,
    compute_pending,
    delete_recurring_rule,
    ensure_recurring_file,
    parse_recurring_rules,
    update_recurring_rule,
)
from tests.conftest import has_hledger

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def euro_style() -> AmountStyle:
    """Standard Euro amount style."""
    return AmountStyle(commodity_side="L", commodity_spaced=False, precision=2)


@pytest.fixture
def sample_recurring_path() -> Path:
    """Path to the sample recurring.journal fixture."""
    return FIXTURES_DIR / "sample_recurring.journal"


@pytest.fixture
def sample_rule(euro_style: AmountStyle) -> RecurringRule:
    """A sample recurring rule for testing."""
    return RecurringRule(
        rule_id="rent-001",
        period_expr="monthly",
        description="Rent payment",
        start_date="2026-01-01",
        postings=[
            Posting(
                account="expenses:rent",
                amounts=[Amount(commodity="€", quantity=Decimal("800.00"), style=euro_style)],
            ),
            Posting(account="assets:bank:checking", amounts=[]),
        ],
    )


# ---------------------------------------------------------------------------
# _parse_amount_string
# ---------------------------------------------------------------------------


class TestParseAmountString:
    """Tests for _parse_amount_string."""

    def test_left_commodity(self):
        """Parse amount with left-side commodity symbol."""
        qty, commodity = _parse_amount_string("€800.00")
        assert qty == Decimal("800.00")
        assert commodity == "€"

    def test_right_commodity(self):
        """Parse amount with right-side commodity code."""
        qty, commodity = _parse_amount_string("800.00EUR")
        assert qty == Decimal("800.00")
        assert commodity == "EUR"

    def test_dollar(self):
        """Parse dollar amount."""
        qty, commodity = _parse_amount_string("$150.50")
        assert qty == Decimal("150.50")
        assert commodity == "$"

    def test_negative(self):
        """Parse negative amount."""
        qty, commodity = _parse_amount_string("€-50.00")
        assert qty == Decimal("-50.00")
        assert commodity == "€"

    def test_empty_raises(self):
        """Empty string raises RecurringError."""
        with pytest.raises(RecurringError):
            _parse_amount_string("")

    def test_invalid_raises(self):
        """Unparseable string raises RecurringError."""
        with pytest.raises(RecurringError):
            _parse_amount_string("notanamount")


# ---------------------------------------------------------------------------
# parse_recurring_rules
# ---------------------------------------------------------------------------


class TestParseRecurringRules:
    """Tests for parse_recurring_rules."""

    def test_empty_file(self, tmp_path: Path):
        """Empty file returns empty list."""
        f = tmp_path / "recurring.journal"
        f.write_text("")
        assert parse_recurring_rules(f) == []

    def test_nonexistent_file(self, tmp_path: Path):
        """Nonexistent file returns empty list."""
        assert parse_recurring_rules(tmp_path / "nope.journal") == []

    def test_single_rule(self, tmp_path: Path):
        """Parse a single rule correctly."""
        content = (
            "~ monthly from 2026-01-01  ; rule-id:rent-001 Rent payment\n"
            "    expenses:rent                       €800.00\n"
            "    assets:bank:checking\n"
        )
        f = tmp_path / "recurring.journal"
        f.write_text(content)
        rules = parse_recurring_rules(f)
        assert len(rules) == 1
        assert rules[0].rule_id == "rent-001"
        assert rules[0].period_expr == "monthly"
        assert rules[0].description == "Rent payment"
        assert rules[0].start_date == "2026-01-01"
        assert rules[0].end_date is None

    def test_multiple_rules(self, sample_recurring_path: Path):
        """Parse multiple rules from the fixture file."""
        rules = parse_recurring_rules(sample_recurring_path)
        assert len(rules) == 2
        assert rules[0].rule_id == "rent-001"
        assert rules[1].rule_id == "groceries-001"

    def test_rule_postings(self, sample_recurring_path: Path):
        """Postings are parsed correctly."""
        rules = parse_recurring_rules(sample_recurring_path)
        rent = rules[0]
        assert len(rent.postings) == 2
        assert rent.postings[0].account == "expenses:rent"
        assert rent.postings[0].amounts[0].quantity == Decimal("800.00")
        assert rent.postings[0].amounts[0].commodity == "€"
        # Balancing posting has no amounts
        assert rent.postings[1].account == "assets:bank:checking"
        assert rent.postings[1].amounts == []

    def test_rule_without_rule_id_skipped(self, tmp_path: Path):
        """Rules without rule-id tag are skipped."""
        content = (
            "~ monthly\n"
            "    expenses:rent                       €800.00\n"
            "    assets:bank:checking\n"
        )
        f = tmp_path / "recurring.journal"
        f.write_text(content)
        rules = parse_recurring_rules(f)
        assert rules == []

    def test_rule_with_end_date(self, tmp_path: Path):
        """Rule with end date is parsed correctly."""
        content = (
            "~ monthly from 2026-01-01 to 2026-12-31  ; rule-id:lease-001 Office lease\n"
            "    expenses:office                      €500.00\n"
            "    assets:bank\n"
        )
        f = tmp_path / "recurring.journal"
        f.write_text(content)
        rules = parse_recurring_rules(f)
        assert len(rules) == 1
        assert rules[0].end_date == "2026-12-31"

    def test_postings_with_thousands_separator(self, tmp_path: Path):
        """Amounts with thousands separators (commas) are parsed correctly."""
        content = (
            "~ monthly from 2026-05-01  ; rule-id:mortgage-001 Mortgage\n"
            "    expenses:mortgage:interest              $1,320.28\n"
            "    liabilities:property:mortgage            216.47\n"
            "    assets:operating                        $-1,536.75\n"
        )
        f = tmp_path / "recurring.journal"
        f.write_text(content)
        rules = parse_recurring_rules(f)
        assert len(rules) == 1
        rule = rules[0]
        assert len(rule.postings) == 3
        assert rule.postings[0].account == "expenses:mortgage:interest"
        assert rule.postings[0].amounts[0].quantity == Decimal("1320.28")
        assert rule.postings[0].amounts[0].commodity == "$"
        assert rule.postings[2].account == "assets:operating"
        assert rule.postings[2].amounts[0].quantity == Decimal("-1536.75")

    def test_roundtrip(self, sample_recurring_path: Path, tmp_path: Path):
        """Parse then format then re-parse produces identical results."""
        rules = parse_recurring_rules(sample_recurring_path)
        content = _format_recurring_file(rules)
        out = tmp_path / "out.journal"
        out.write_text(content)
        reparsed = parse_recurring_rules(out)
        assert len(reparsed) == len(rules)
        for orig, rt in zip(rules, reparsed):
            assert orig.rule_id == rt.rule_id
            assert orig.period_expr == rt.period_expr
            assert orig.description == rt.description
            assert orig.start_date == rt.start_date


# ---------------------------------------------------------------------------
# _generate_occurrences
# ---------------------------------------------------------------------------


class TestGenerateOccurrences:
    """Tests for _generate_occurrences."""

    def test_monthly_three_months(self):
        """Monthly period generates three dates over three months."""
        start = date(2026, 1, 1)
        end = date(2026, 3, 1)
        result = _generate_occurrences(start, "monthly", end)
        assert result == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]

    def test_weekly(self):
        """Weekly period generates correct weekly dates."""
        start = date(2026, 1, 5)
        end = date(2026, 1, 26)
        result = _generate_occurrences(start, "weekly", end)
        assert result == [
            date(2026, 1, 5),
            date(2026, 1, 12),
            date(2026, 1, 19),
            date(2026, 1, 26),
        ]

    def test_biweekly(self):
        """Biweekly period advances by 14 days."""
        start = date(2026, 1, 1)
        end = date(2026, 2, 1)
        result = _generate_occurrences(start, "biweekly", end)
        assert result == [date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 29)]

    def test_quarterly(self):
        """Quarterly period generates 4 dates in a year."""
        start = date(2026, 1, 1)
        end = date(2026, 12, 31)
        result = _generate_occurrences(start, "quarterly", end)
        assert result == [
            date(2026, 1, 1),
            date(2026, 4, 1),
            date(2026, 7, 1),
            date(2026, 10, 1),
        ]

    def test_yearly(self):
        """Yearly period generates one date per year."""
        start = date(2024, 1, 1)
        end = date(2026, 12, 31)
        result = _generate_occurrences(start, "yearly", end)
        assert result == [date(2024, 1, 1), date(2025, 1, 1), date(2026, 1, 1)]

    def test_daily(self):
        """Daily period generates a date for each day."""
        start = date(2026, 1, 1)
        end = date(2026, 1, 3)
        result = _generate_occurrences(start, "daily", end)
        assert result == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]

    def test_start_equals_end(self):
        """When start equals end, only one date is generated."""
        d = date(2026, 3, 1)
        result = _generate_occurrences(d, "monthly", d)
        assert result == [d]

    def test_end_before_start_returns_empty(self):
        """End before start returns empty list."""
        result = _generate_occurrences(date(2026, 3, 1), "monthly", date(2026, 1, 1))
        assert result == []

    def test_monthly_end_of_month_clamping(self):
        """Monthly from Jan 31 advances to Feb 28 (clamped)."""
        start = date(2026, 1, 31)
        end = date(2026, 3, 31)
        result = _generate_occurrences(start, "monthly", end)
        assert result[0] == date(2026, 1, 31)
        assert result[1] == date(2026, 2, 28)
        assert result[2] == date(2026, 3, 31)

    def test_unknown_period_returns_single(self):
        """Unknown period returns only the start date."""
        result = _generate_occurrences(date(2026, 1, 1), "foobar", date(2026, 12, 31))
        assert result == [date(2026, 1, 1)]

    def test_bimonthly(self):
        """Bimonthly period advances by 2 months."""
        start = date(2026, 1, 1)
        end = date(2026, 7, 1)
        result = _generate_occurrences(start, "bimonthly", end)
        assert result == [
            date(2026, 1, 1),
            date(2026, 3, 1),
            date(2026, 5, 1),
            date(2026, 7, 1),
        ]


# ---------------------------------------------------------------------------
# compute_pending (unit — hledger mocked)
# ---------------------------------------------------------------------------


class TestComputePending:
    """Tests for compute_pending with mocked hledger calls."""

    def test_no_start_date_returns_empty(self, sample_rule: RecurringRule):
        """Rule without start_date returns empty list."""
        rule = RecurringRule(
            rule_id="test-001",
            period_expr="monthly",
            description="Test",
        )
        result = compute_pending(rule, Path("/fake/main.journal"), date(2026, 3, 1))
        assert result == []

    def test_all_pending_when_none_generated(self, sample_rule: RecurringRule):
        """All dates are pending when no transactions have been generated yet."""
        today = date(2026, 3, 1)
        with patch(
            "hledger_textual.recurring.load_transactions", return_value=[]
        ):
            result = compute_pending(
                sample_rule, Path("/fake/main.journal"), today
            )
        # 2026-01-01, 2026-02-01, 2026-03-01 → 3 dates
        assert result == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]

    def test_already_generated_filtered_out(self, sample_rule: RecurringRule):
        """Dates with already-generated transactions are excluded."""
        from hledger_textual.models import Transaction

        generated_txn = Transaction(
            index=1,
            date="2026-01-01",
            description="Rent payment",
            postings=[],
        )
        today = date(2026, 3, 1)
        with patch(
            "hledger_textual.recurring.load_transactions",
            return_value=[generated_txn],
        ):
            result = compute_pending(
                sample_rule, Path("/fake/main.journal"), today
            )
        assert date(2026, 1, 1) not in result
        assert date(2026, 2, 1) in result
        assert date(2026, 3, 1) in result

    def test_all_generated_returns_empty(self, sample_rule: RecurringRule):
        """Returns empty list when all dates have already been generated."""
        from hledger_textual.models import Transaction

        generated = [
            Transaction(index=i, date=d, description="x", postings=[])
            for i, d in enumerate(["2026-01-01", "2026-02-01", "2026-03-01"])
        ]
        today = date(2026, 3, 1)
        with patch(
            "hledger_textual.recurring.load_transactions",
            return_value=generated,
        ):
            result = compute_pending(
                sample_rule, Path("/fake/main.journal"), today
            )
        assert result == []

    def test_end_date_respected(self, euro_style: AmountStyle):
        """Dates after end_date are not included."""
        rule = RecurringRule(
            rule_id="limited-001",
            period_expr="monthly",
            description="Limited",
            start_date="2026-01-01",
            end_date="2026-02-01",
            postings=[],
        )
        today = date(2026, 6, 1)
        with patch(
            "hledger_textual.recurring.load_transactions", return_value=[]
        ):
            result = compute_pending(rule, Path("/fake/main.journal"), today)
        assert result == [date(2026, 1, 1), date(2026, 2, 1)]

    def test_hledger_error_treats_as_empty(self, sample_rule: RecurringRule):
        """If hledger fails, treats generated set as empty (all dates pending)."""
        from hledger_textual.hledger import HledgerError

        today = date(2026, 2, 1)
        with patch(
            "hledger_textual.recurring.load_transactions",
            side_effect=HledgerError("fail"),
        ):
            result = compute_pending(
                sample_rule, Path("/fake/main.journal"), today
            )
        assert date(2026, 1, 1) in result
        assert date(2026, 2, 1) in result


# ---------------------------------------------------------------------------
# ensure_recurring_file
# ---------------------------------------------------------------------------


class TestEnsureRecurringFile:
    """Tests for ensure_recurring_file."""

    def test_creates_recurring_file(self, tmp_path: Path):
        """Creates recurring.journal next to the main journal."""
        journal = tmp_path / "test.journal"
        journal.write_text("; some journal\n")

        recurring_path = ensure_recurring_file(journal)
        assert recurring_path.exists()
        assert recurring_path.name == RECURRING_FILENAME

    def test_adds_include_directive(self, tmp_path: Path):
        """Adds include directive to main journal."""
        journal = tmp_path / "test.journal"
        journal.write_text("; some journal\n")

        ensure_recurring_file(journal)
        content = journal.read_text()
        assert f"include {RECURRING_FILENAME}" in content

    def test_does_not_duplicate_include(self, tmp_path: Path):
        """Does not add include directive if already present."""
        journal = tmp_path / "test.journal"
        journal.write_text(f"include {RECURRING_FILENAME}\n\n; some journal\n")
        recurring = tmp_path / RECURRING_FILENAME
        recurring.write_text("")

        ensure_recurring_file(journal)
        content = journal.read_text()
        assert content.count(f"include {RECURRING_FILENAME}") == 1

    def test_idempotent(self, tmp_path: Path):
        """Calling twice is safe."""
        journal = tmp_path / "test.journal"
        journal.write_text("; some journal\n")

        ensure_recurring_file(journal)
        ensure_recurring_file(journal)

        content = journal.read_text()
        assert content.count(f"include {RECURRING_FILENAME}") == 1


# ---------------------------------------------------------------------------
# _format_recurring_file
# ---------------------------------------------------------------------------


class TestFormatRecurringFile:
    """Tests for _format_recurring_file."""

    def test_empty_rules(self):
        """Empty list produces empty string."""
        assert _format_recurring_file([]) == ""

    def test_single_rule_format(self, sample_rule: RecurringRule):
        """Formats a single rule with header and postings."""
        content = _format_recurring_file([sample_rule])
        assert "~ monthly from 2026-01-01" in content
        assert "rule-id:rent-001" in content
        assert "Rent payment" in content
        assert "expenses:rent" in content
        assert "€800.00" in content
        assert "assets:bank:checking" in content

    def test_multiple_rules_separated(self, sample_recurring_path: Path):
        """Multiple rules are separated by blank lines."""
        rules = parse_recurring_rules(sample_recurring_path)
        content = _format_recurring_file(rules)
        # Two rule headers present
        assert content.count("~ ") == 2
        # Separated by blank line
        assert "\n\n" in content


# ---------------------------------------------------------------------------
# CRUD operations (require hledger for validation)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestRecurringCRUD:
    """Integration tests for add/update/delete_recurring_rule."""

    @pytest.fixture
    def tmp_recurring_setup(self, tmp_path: Path) -> tuple[Path, Path]:
        """Set up a temporary journal + recurring.journal pair."""
        sample = FIXTURES_DIR / "sample.journal"
        journal = tmp_path / "test.journal"
        shutil.copy2(sample, journal)

        recurring = tmp_path / RECURRING_FILENAME
        recurring.write_text("")

        # Add include directive
        content = journal.read_text()
        journal.write_text(f"include {RECURRING_FILENAME}\n\n{content}")

        return journal, recurring

    def test_add_rule(
        self,
        tmp_recurring_setup: tuple[Path, Path],
        sample_rule: RecurringRule,
    ):
        """add_recurring_rule appends a rule and it can be re-parsed."""
        journal, recurring = tmp_recurring_setup
        add_recurring_rule(recurring, sample_rule, journal)

        rules = parse_recurring_rules(recurring)
        assert len(rules) == 1
        assert rules[0].rule_id == "rent-001"

    def test_add_duplicate_raises(
        self,
        tmp_recurring_setup: tuple[Path, Path],
        sample_rule: RecurringRule,
    ):
        """Adding a rule with duplicate ID raises RecurringError."""
        journal, recurring = tmp_recurring_setup
        add_recurring_rule(recurring, sample_rule, journal)

        with pytest.raises(RecurringError, match="already exists"):
            add_recurring_rule(recurring, sample_rule, journal)

    def test_update_rule(
        self,
        tmp_recurring_setup: tuple[Path, Path],
        sample_rule: RecurringRule,
        euro_style: AmountStyle,
    ):
        """update_recurring_rule replaces the matching rule."""
        journal, recurring = tmp_recurring_setup
        add_recurring_rule(recurring, sample_rule, journal)

        updated = RecurringRule(
            rule_id="rent-001",
            period_expr="monthly",
            description="Rent payment updated",
            start_date="2026-02-01",
            postings=[
                Posting(
                    account="expenses:rent",
                    amounts=[
                        Amount(commodity="€", quantity=Decimal("900.00"), style=euro_style)
                    ],
                ),
                Posting(account="assets:bank:checking", amounts=[]),
            ],
        )
        update_recurring_rule(recurring, "rent-001", updated, journal)

        rules = parse_recurring_rules(recurring)
        assert len(rules) == 1
        assert rules[0].description == "Rent payment updated"
        assert rules[0].postings[0].amounts[0].quantity == Decimal("900.00")

    def test_update_nonexistent_raises(
        self,
        tmp_recurring_setup: tuple[Path, Path],
        sample_rule: RecurringRule,
    ):
        """Updating a non-existent rule raises RecurringError."""
        journal, recurring = tmp_recurring_setup
        with pytest.raises(RecurringError, match="No recurring rule found"):
            update_recurring_rule(recurring, "nonexistent-001", sample_rule, journal)

    def test_delete_rule(
        self,
        tmp_recurring_setup: tuple[Path, Path],
        sample_rule: RecurringRule,
    ):
        """delete_recurring_rule removes the matching rule."""
        journal, recurring = tmp_recurring_setup
        add_recurring_rule(recurring, sample_rule, journal)

        delete_recurring_rule(recurring, "rent-001", journal)

        rules = parse_recurring_rules(recurring)
        assert rules == []

    def test_delete_nonexistent_raises(
        self,
        tmp_recurring_setup: tuple[Path, Path],
    ):
        """Deleting a non-existent rule raises RecurringError."""
        journal, recurring = tmp_recurring_setup
        with pytest.raises(RecurringError, match="No recurring rule found"):
            delete_recurring_rule(recurring, "nonexistent-001", journal)
