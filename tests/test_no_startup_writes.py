"""Regression tests: launching the app never writes to the journal (issue #270)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from hledger_textual.budget import (
    BUDGET_FILENAME,
    BudgetRule,
    add_budget_rule,
    ensure_budget_file,
)
from hledger_textual.models import Amount, AmountStyle, Posting
from hledger_textual.recurring import (
    RECURRING_FILENAME,
    RecurringRule,
    add_recurring_rule,
    ensure_recurring_file,
)
from tests.conftest import has_hledger

JOURNAL = "2024-03-10 * Grocery\n    expenses:food  10.00\n    assets:checking\n"


def _journal(tmp_path: Path) -> Path:
    """Write a plain single-transaction journal."""
    journal = tmp_path / "main.journal"
    journal.write_text(JOURNAL)
    return journal


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestNoWritesOnLaunch:
    """Launching the app never modifies the journal or its directory."""

    def test_ensure_calls_are_noops(self, tmp_path: Path):
        """ensure_* without create touches nothing."""
        journal = _journal(tmp_path)
        before = journal.read_bytes()

        ensure_budget_file(journal)
        ensure_recurring_file(journal)

        assert journal.read_bytes() == before
        assert not (tmp_path / BUDGET_FILENAME).exists()
        assert not (tmp_path / RECURRING_FILENAME).exists()


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestFirstRuleCreatesFile:
    """The first rule is the only moment the auxiliary files appear."""

    def _rule(self, account: str = "Expenses:Food") -> BudgetRule:
        """Return a simple euro budget rule."""
        return BudgetRule(
            account=account,
            amount=Amount(
                commodity="€", quantity=Decimal("50.00"), style=AmountStyle()
            ),
        )

    def test_first_budget_rule_creates_file_and_include(self, tmp_path: Path):
        """add_budget_rule creates budget.journal and the include line."""
        journal = _journal(tmp_path)
        budget_path = tmp_path / BUDGET_FILENAME

        add_budget_rule(budget_path, self._rule(), journal)

        assert budget_path.exists()
        text = journal.read_text()
        assert text.count("include budget.journal") == 1
        # The include is prepended before the existing content.
        assert text.splitlines()[0] == "include budget.journal"
        # The original journal content survives after the include block.
        assert JOURNAL in text

    def test_second_budget_rule_does_not_duplicate_include(self, tmp_path: Path):
        """Adding another rule leaves the include exactly once."""
        journal = _journal(tmp_path)
        budget_path = tmp_path / BUDGET_FILENAME

        add_budget_rule(budget_path, self._rule(), journal)
        add_budget_rule(budget_path, self._rule("Expenses:Rent"), journal)

        assert journal.read_text().count("include budget.journal") == 1

    def test_first_recurring_rule_creates_file_and_include(self, tmp_path: Path):
        """add_recurring_rule creates recurring.journal and the include line."""
        journal = _journal(tmp_path)
        recurring_path = tmp_path / RECURRING_FILENAME
        rule = RecurringRule(
            rule_id="abc",
            period_expr="monthly",
            description="Rent",
            postings=[
                Posting(
                    account="expenses:rent",
                    amounts=[
                        Amount(
                            commodity="€",
                            quantity=Decimal("100.00"),
                            style=AmountStyle(),
                        )
                    ],
                ),
                Posting(
                    account="assets:checking",
                    amounts=[
                        Amount(
                            commodity="€",
                            quantity=Decimal("-100.00"),
                            style=AmountStyle(),
                        )
                    ],
                ),
            ],
        )

        add_recurring_rule(recurring_path, rule, journal)

        assert recurring_path.exists()
        text = journal.read_text()
        assert text.count("include recurring.journal") == 1
        assert JOURNAL in text

    def test_edit_targets_right_lines_after_include_insert(
        self, tmp_path: Path
    ):
        """After the include insert, editing an existing transaction is exact."""
        from hledger_textual.hledger import load_transactions
        from hledger_textual.journal import replace_transaction

        journal = _journal(tmp_path)
        budget_path = tmp_path / BUDGET_FILENAME
        add_budget_rule(budget_path, self._rule(), journal)

        # Fresh load resolves source positions AFTER the insert.
        txns = load_transactions(journal)
        assert len(txns) == 1
        original = txns[0]

        import dataclasses

        updated = dataclasses.replace(original, description="Groceries!")
        replace_transaction(journal, original, updated)

        reload_txns = load_transactions(journal)
        assert [t.description for t in reload_txns] == ["Groceries!"]
        # The include line is untouched by the edit.
        assert journal.read_text().count("include budget.journal") == 1
