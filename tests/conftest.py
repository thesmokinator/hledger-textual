"""Shared test fixtures."""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from hledger_textual.models import (
    Amount,
    AmountStyle,
    BudgetRule,
    Posting,
    Transaction,
    TransactionStatus,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _fixed_number_locale():
    """Force en_US locale for all tests to get predictable amount formatting."""
    from hledger_textual.widgets.formatting import _number_locale
    _number_locale.cache_clear()
    with patch("hledger_textual.config.load_number_locale", return_value="en_US"):
        yield
    _number_locale.cache_clear()


@pytest.fixture
def sample_journal_path() -> Path:
    """Path to the sample journal fixture."""
    return FIXTURES_DIR / "sample.journal"


@pytest.fixture
def tmp_journal(tmp_path: Path, sample_journal_path: Path) -> Path:
    """A temporary copy of the sample journal for mutation tests."""
    dest = tmp_path / "test.journal"
    shutil.copy2(sample_journal_path, dest)
    return dest


@pytest.fixture
def euro_style() -> AmountStyle:
    """Standard Euro amount style."""
    return AmountStyle(
        commodity_side="L",
        commodity_spaced=False,
        decimal_mark=".",
        precision=2,
    )


@pytest.fixture
def sample_transaction(euro_style: AmountStyle) -> Transaction:
    """A sample transaction for testing."""
    return Transaction(
        index=1,
        date="2026-01-15",
        description="Grocery shopping",
        status=TransactionStatus.CLEARED,
        code="INV-001",
        comment="weekly groceries",
        postings=[
            Posting(
                account="expenses:food:groceries",
                amounts=[Amount(commodity="€", quantity=Decimal("40.80"), style=euro_style)],
            ),
            Posting(
                account="assets:bank:checking",
                amounts=[Amount(commodity="€", quantity=Decimal("-40.80"), style=euro_style)],
            ),
        ],
    )


@pytest.fixture
def new_transaction(euro_style: AmountStyle) -> Transaction:
    """A new transaction for append/create tests."""
    return Transaction(
        index=0,
        date="2026-02-01",
        description="Rent payment",
        status=TransactionStatus.UNMARKED,
        postings=[
            Posting(
                account="expenses:rent",
                amounts=[Amount(commodity="€", quantity=Decimal("800.00"), style=euro_style)],
            ),
            Posting(
                account="assets:bank:checking",
                amounts=[Amount(commodity="€", quantity=Decimal("-800.00"), style=euro_style)],
            ),
        ],
    )


def has_hledger() -> bool:
    """Check if hledger is available on the system."""
    return shutil.which("hledger") is not None


@pytest.fixture
def european_journal_path() -> Path:
    """Path to the European-format journal fixture (€1.000,00)."""
    return FIXTURES_DIR / "european.journal"


@pytest.fixture
def us_journal_path() -> Path:
    """Path to the US-format journal fixture ($1,000.00)."""
    return FIXTURES_DIR / "us.journal"


@pytest.fixture
def style_variants_journal_path() -> Path:
    """Path to the style-variants journal fixture (multiple amount styles)."""
    return FIXTURES_DIR / "style_variants.journal"


@pytest.fixture
def sample_budget_journal_path() -> Path:
    """Path to the sample budget journal fixture."""
    return FIXTURES_DIR / "sample_budget.journal"


@pytest.fixture
def tmp_budget_journal(tmp_path: Path, sample_budget_journal_path: Path) -> Path:
    """A temporary copy of the sample budget journal for mutation tests."""
    dest = tmp_path / "budget.journal"
    shutil.copy2(sample_budget_journal_path, dest)
    return dest


@pytest.fixture
def tmp_journal_with_budget(
    tmp_path: Path, sample_journal_path: Path, sample_budget_journal_path: Path
) -> Path:
    """A temporary journal with budget.journal and include directive."""
    journal_dest = tmp_path / "test.journal"
    budget_dest = tmp_path / "budget.journal"

    shutil.copy2(sample_journal_path, journal_dest)
    shutil.copy2(sample_budget_journal_path, budget_dest)

    # Add include directive to the journal
    content = journal_dest.read_text()
    journal_dest.write_text(f"include budget.journal\n\n{content}")

    return journal_dest


@pytest.fixture
def tmp_journal_with_includes(tmp_path: Path) -> Path:
    """A temporary multi-file journal setup with include directives."""
    src = FIXTURES_DIR / "includes"
    for f in src.iterdir():
        shutil.copy2(f, tmp_path / f.name)
    return tmp_path / "main.journal"


@pytest.fixture
def tmp_journal_with_glob_includes(tmp_path: Path) -> Path:
    """A temporary multi-file journal setup with glob-based include directives."""
    src = FIXTURES_DIR / "glob_includes"
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, tmp_path / f.name)
        elif f.is_dir():
            shutil.copytree(f, tmp_path / f.name)
    return tmp_path / "main.journal"


@pytest.fixture
def sample_budget_rule(euro_style: AmountStyle) -> BudgetRule:
    """A sample budget rule for testing."""
    return BudgetRule(
        account="Expenses:Groceries",
        amount=Amount(commodity="€", quantity=Decimal("800.00"), style=euro_style),
    )
