"""Tests for hledger CLI reader."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from hledger_textual.hledger import (
    HledgerError,
    _parse_budget_amount,
    _parse_report_csv,
    expand_search_query,
    load_accounts,
    load_descriptions,
    load_expense_breakdown,
    load_investment_cost,
    load_investment_eur_by_account,
    load_investment_positions,
    load_journal_stats,
    load_period_summary,
    load_report,
    load_transactions,
)
from hledger_textual.models import TransactionStatus

from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


class TestLoadTransactions:
    """Tests for load_transactions."""

    def test_loads_all_transactions(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        assert len(txns) == 3

    def test_first_transaction_fields(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        txn = txns[0]
        assert txn.date == "2026-01-15"
        assert txn.description == "Grocery shopping"
        assert txn.status == TransactionStatus.CLEARED
        assert txn.code == "INV-001"
        assert txn.comment == "weekly groceries"

    def test_postings_parsed(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        txn = txns[0]
        assert len(txn.postings) == 2
        assert txn.postings[0].account == "expenses:food:groceries"
        assert txn.postings[0].amounts[0].commodity == "€"
        assert txn.postings[0].amounts[0].quantity == Decimal("40.80")

    def test_amounts_use_decimal(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        amount = txns[1].postings[0].amounts[0]
        assert isinstance(amount.quantity, Decimal)
        assert amount.quantity == Decimal("3000.00")

    def test_source_positions(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        assert txns[0].source_pos is not None
        start, end = txns[0].source_pos
        assert start.source_line == 3
        assert end.source_line == 6

    def test_pending_status(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        assert txns[2].status == TransactionStatus.PENDING

    def test_unmarked_status(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        assert txns[1].status == TransactionStatus.UNMARKED

    def test_three_postings(self, sample_journal_path: Path):
        txns = load_transactions(sample_journal_path)
        assert len(txns[2].postings) == 3

    def test_invalid_file_raises(self, tmp_path: Path):
        bad_file = tmp_path / "bad.journal"
        bad_file.write_text("this is not valid journal content\n")
        with pytest.raises(HledgerError):
            load_transactions(bad_file)


class TestLoadAccounts:
    """Tests for load_accounts."""

    def test_loads_accounts(self, sample_journal_path: Path):
        accounts = load_accounts(sample_journal_path)
        assert "expenses:food:groceries" in accounts
        assert "assets:bank:checking" in accounts
        assert "income:salary" in accounts

    def test_account_count(self, sample_journal_path: Path):
        accounts = load_accounts(sample_journal_path)
        assert len(accounts) == 5


class TestLoadDescriptions:
    """Tests for load_descriptions."""

    def test_loads_descriptions(self, sample_journal_path: Path):
        descriptions = load_descriptions(sample_journal_path)
        assert "Grocery shopping" in descriptions
        assert "Salary" in descriptions
        assert "Office supplies" in descriptions

    def test_description_count(self, sample_journal_path: Path):
        descriptions = load_descriptions(sample_journal_path)
        assert len(descriptions) == 3


class TestParseBudgetAmount:
    """Tests for the _parse_budget_amount pure function."""

    def test_left_side_currency_symbol(self):
        """Euro symbol on the left: €500.00."""
        qty, commodity = _parse_budget_amount("€500.00")
        assert qty == pytest.approx(500.00, abs=1e-2)
        assert commodity == "€"

    def test_right_side_currency_code(self):
        """Currency code on the right: 500.00 EUR."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("500.00 EUR")
        assert qty == Decimal("500.00")
        assert commodity == "EUR"

    def test_plain_number(self):
        """Plain integer with no commodity."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("500")
        assert qty == Decimal("500")
        assert commodity == ""

    def test_empty_string(self):
        """Empty string returns zero with no commodity."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("")
        assert qty == Decimal("0")
        assert commodity == ""

    def test_zero_string(self):
        """The literal '0' returns zero with no commodity."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("0")
        assert qty == Decimal("0")
        assert commodity == ""

    def test_dollar_sign_left(self):
        """Dollar sign on the left: $1200.50."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("$1200.50")
        assert qty == Decimal("1200.50")
        assert commodity == "$"

    def test_number_with_comma_separator(self):
        """Numbers with comma thousand-separators are handled."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("1,500.00")
        assert qty == Decimal("1500.00")
        assert commodity == ""

    def test_left_currency_with_comma(self):
        """Left-side currency with comma-separated number."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("€1,200.00")
        assert qty == Decimal("1200.00")
        assert commodity == "€"

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("  €300.00  ")
        assert qty == Decimal("300.00")
        assert commodity == "€"

    def test_unparseable_returns_zero(self):
        """Garbage input returns zero with no commodity."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("not-a-number")
        assert qty == Decimal("0")
        assert commodity == ""


class TestLoadJournalStats:
    """Tests for load_journal_stats."""

    def test_transaction_count(self, sample_journal_path: Path):
        """The sample journal has exactly 3 transactions."""
        stats = load_journal_stats(sample_journal_path)
        assert stats.transaction_count == 3

    def test_account_count(self, sample_journal_path: Path):
        """The sample journal uses 5 distinct accounts."""
        stats = load_journal_stats(sample_journal_path)
        assert stats.account_count == 5

    def test_commodities(self, sample_journal_path: Path):
        """The sample journal uses a single commodity: Euro."""
        stats = load_journal_stats(sample_journal_path)
        assert stats.commodities == ["€"]


class TestLoadPeriodSummary:
    """Tests for load_period_summary."""

    @pytest.fixture
    def current_month_journal(self, tmp_path: Path) -> Path:
        """Create a journal with transactions in the current month."""
        today = date.today()
        d1 = today.replace(day=1)
        d2 = today.replace(day=2)
        content = (
            f"{d1.isoformat()} * Groceries\n"
            f"    expenses:food  €40.00\n"
            f"    assets:bank\n"
            f"\n"
            f"{d2.isoformat()} Salary\n"
            f"    assets:bank  €3000.00\n"
            f"    income:salary\n"
        )
        journal = tmp_path / "period.journal"
        journal.write_text(content)
        return journal

    def test_income(self, current_month_journal: Path):
        """Income should equal the salary amount."""
        period = date.today().strftime("%Y-%m")
        summary = load_period_summary(current_month_journal, period)
        assert summary.income == Decimal("3000.00")

    def test_expenses(self, current_month_journal: Path):
        """Expenses should equal the grocery amount."""
        period = date.today().strftime("%Y-%m")
        summary = load_period_summary(current_month_journal, period)
        assert summary.expenses == Decimal("40.00")

    def test_net(self, current_month_journal: Path):
        """Net should be income minus expenses."""
        period = date.today().strftime("%Y-%m")
        summary = load_period_summary(current_month_journal, period)
        assert summary.net == Decimal("2960.00")

    def test_commodity(self, current_month_journal: Path):
        """The detected commodity should be Euro."""
        period = date.today().strftime("%Y-%m")
        summary = load_period_summary(current_month_journal, period)
        assert summary.commodity == "€"

    def test_investments_zero_when_absent(self, current_month_journal: Path):
        """Without investment transactions, investments should be zero."""
        period = date.today().strftime("%Y-%m")
        summary = load_period_summary(current_month_journal, period)
        assert summary.investments == Decimal("0")

    def test_investments_included(self, tmp_path: Path):
        """Investment purchases at cost are included in the summary."""
        today = date.today()
        d1 = today.replace(day=1)
        d2 = today.replace(day=2)
        d3 = today.replace(day=3)
        content = (
            f"{d1.isoformat()} Salary\n"
            f"    assets:bank  €3000.00\n"
            f"    income:salary\n"
            f"\n"
            f"{d2.isoformat()} * Groceries\n"
            f"    expenses:food  €100.00\n"
            f"    assets:bank\n"
            f"\n"
            f"{d3.isoformat()} * Buy ETF\n"
            f"    assets:investments:XDWD  5 XDWD @ €120.00\n"
            f"    assets:bank  €-600.00\n"
        )
        journal = tmp_path / "invest.journal"
        journal.write_text(content)
        period = today.strftime("%Y-%m")
        summary = load_period_summary(journal, period)
        assert summary.income == Decimal("3000.00")
        assert summary.expenses == Decimal("100.00")
        assert summary.investments == Decimal("600.00")
        assert summary.net == Decimal("2300.00")


class TestLoadExpenseBreakdown:
    """Tests for load_expense_breakdown."""

    @pytest.fixture
    def expense_journal(self, tmp_path: Path) -> Path:
        """Create a journal with two expense accounts in the current month."""
        today = date.today()
        d1 = today.replace(day=1)
        d2 = today.replace(day=2)
        content = (
            f"{d1.isoformat()} * Groceries\n"
            f"    expenses:food  €120.00\n"
            f"    assets:bank\n"
            f"\n"
            f"{d2.isoformat()} * Electricity\n"
            f"    expenses:utilities  €80.00\n"
            f"    assets:bank\n"
        )
        journal = tmp_path / "expenses.journal"
        journal.write_text(content)
        return journal

    def test_returns_expense_accounts(self, expense_journal: Path):
        """Both expense accounts should be returned."""
        period = date.today().strftime("%Y-%m")
        breakdown = load_expense_breakdown(expense_journal, period)
        accounts = [row[0] for row in breakdown]
        assert "expenses:food" in accounts
        assert "expenses:utilities" in accounts

    def test_sorted_by_amount_descending(self, expense_journal: Path):
        """Results should be sorted by amount descending."""
        period = date.today().strftime("%Y-%m")
        breakdown = load_expense_breakdown(expense_journal, period)
        assert len(breakdown) == 2
        assert breakdown[0][1] >= breakdown[1][1]
        # food (€120) should come before utilities (€80)
        assert breakdown[0][0] == "expenses:food"
        assert breakdown[0][1] == Decimal("120.00")
        assert breakdown[1][0] == "expenses:utilities"
        assert breakdown[1][1] == Decimal("80.00")

    def test_empty_period_returns_empty(self, expense_journal: Path):
        """A period with no transactions should return an empty list."""
        breakdown = load_expense_breakdown(expense_journal, "1999-01")
        assert breakdown == []


class TestLoadInvestmentFunctions:
    """Tests for investment-related functions."""

    @pytest.fixture
    def empty_journal(self, tmp_path: Path) -> Path:
        """Create a minimal journal with no investment accounts."""
        journal = tmp_path / "empty.journal"
        today = date.today()
        content = (
            f"{today.isoformat()} * Coffee\n"
            f"    expenses:food  €5.00\n"
            f"    assets:bank\n"
        )
        journal.write_text(content)
        return journal

    def test_positions_empty_journal(self, empty_journal: Path):
        """A journal with no investments should return an empty list."""
        positions = load_investment_positions(empty_journal)
        assert positions == []

    def test_cost_empty_journal(self, empty_journal: Path):
        """A journal with no investments should return an empty dict."""
        cost = load_investment_cost(empty_journal)
        assert cost == {}

    def test_eur_with_empty_prices_file(self, empty_journal: Path, tmp_path: Path):
        """An empty prices file should yield an empty dict."""
        prices_file = tmp_path / "prices.journal"
        prices_file.write_text("; no price directives\n")
        result = load_investment_eur_by_account(empty_journal, prices_file)
        assert result == {}


# ------------------------------------------------------------------
# Pure-function tests for _parse_report_csv (no hledger needed)
# ------------------------------------------------------------------


class TestParseReportCsv:
    """Tests for the _parse_report_csv pure function."""

    _IS_CSV = (
        '"Monthly Income Statement 2025-09-01..2026-03-01","","","","","",""\n'
        '"Account","Sep","Oct","Nov","Dec","Jan","Feb"\n'
        '"Revenues","","","","","",""\n'
        '"income:salary","€3000.00","€3000.00","€3000.00","€3000.00","€3000.00","€3000.00"\n'
        '"Expenses","","","","","",""\n'
        '"expenses:food","€120.00","€130.00","€110.00","€150.00","€140.00","€125.00"\n'
        '"expenses:rent","€800.00","€800.00","€800.00","€800.00","€800.00","€800.00"\n'
        '"Net:","€2080.00","€2070.00","€2090.00","€2050.00","€2060.00","€2075.00"\n'
    )

    _BS_CSV = (
        '"Monthly Balance Sheet 2026-01-01..2026-03-01","",""\n'
        '"Account","Jan","Feb"\n'
        '"Assets","",""\n'
        '"assets:bank:checking","€5000.00","€7000.00"\n'
        '"Liabilities","",""\n'
        '"Total:","€5000.00","€7000.00"\n'
    )

    def test_is_title(self):
        """The title row is parsed correctly for IS."""
        data = _parse_report_csv(self._IS_CSV)
        assert "Income Statement" in data.title

    def test_is_period_headers(self):
        """Period headers are extracted from the header row."""
        data = _parse_report_csv(self._IS_CSV)
        assert data.period_headers == ["Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]

    def test_is_row_count(self):
        """All data rows are parsed."""
        data = _parse_report_csv(self._IS_CSV)
        assert len(data.rows) == 6

    def test_is_section_headers(self):
        """Section header rows (Revenues, Expenses) are detected."""
        data = _parse_report_csv(self._IS_CSV)
        headers = [r for r in data.rows if r.is_section_header]
        header_names = [h.account for h in headers]
        assert "Revenues" in header_names
        assert "Expenses" in header_names

    def test_is_total_row(self):
        """Net: row is detected as a total."""
        data = _parse_report_csv(self._IS_CSV)
        totals = [r for r in data.rows if r.is_total]
        assert len(totals) == 1
        assert totals[0].account == "Net:"

    def test_is_data_row_amounts(self):
        """Account rows carry the correct period amounts."""
        data = _parse_report_csv(self._IS_CSV)
        salary_rows = [r for r in data.rows if "salary" in r.account]
        assert len(salary_rows) == 1
        assert salary_rows[0].amounts[0] == "€3000.00"

    def test_bs_title(self):
        """Balance sheet title is parsed."""
        data = _parse_report_csv(self._BS_CSV)
        assert "Balance Sheet" in data.title

    def test_bs_total(self):
        """Total: row detected in BS output."""
        data = _parse_report_csv(self._BS_CSV)
        totals = [r for r in data.rows if r.is_total]
        assert len(totals) == 1
        assert totals[0].account == "Total:"

    def test_bs_section_headers(self):
        """Assets and Liabilities detected as section headers."""
        data = _parse_report_csv(self._BS_CSV)
        headers = [r.account for r in data.rows if r.is_section_header]
        assert "Assets" in headers
        assert "Liabilities" in headers

    def test_empty_output(self):
        """Empty string produces empty ReportData."""
        data = _parse_report_csv("")
        assert data.title == ""
        assert data.period_headers == []
        assert data.rows == []

    def test_single_row_output(self):
        """A single CSV line (no header row) produces empty data."""
        data = _parse_report_csv('"title","",""\n')
        assert data.title == ""
        assert data.rows == []


class TestLoadReport:
    """Tests for load_report using monkeypatched run_hledger."""

    _SAMPLE_CSV = (
        '"Monthly Cash Flow 2026-01-01..2026-03-01","",""\n'
        '"Account","Jan","Feb"\n'
        '"assets:bank:checking","€2000.00","€3000.00"\n'
        '"Total:","€2000.00","€3000.00"\n'
    )

    def test_load_report_parses_output(self, monkeypatch, tmp_path: Path):
        """load_report delegates to run_hledger and parses the CSV."""
        monkeypatch.setattr(
            "hledger_textual.hledger.run_hledger",
            lambda *args, **kwargs: self._SAMPLE_CSV,
        )
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        data = load_report(journal, "cf", period_begin="2026-01-01", period_end="2026-03-01")
        assert "Cash Flow" in data.title
        assert data.period_headers == ["Jan", "Feb"]
        assert len(data.rows) == 2

    def test_load_report_empty_output(self, monkeypatch, tmp_path: Path):
        """Empty hledger output produces empty ReportData."""
        monkeypatch.setattr(
            "hledger_textual.hledger.run_hledger",
            lambda *args, **kwargs: "",
        )
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        data = load_report(journal, "is")
        assert data.title == ""
        assert data.rows == []

    def test_load_report_hledger_error(self, monkeypatch, tmp_path: Path):
        """HledgerError is raised when hledger fails."""
        def _raise(*args, **kwargs):
            raise HledgerError("command failed")

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _raise)
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        with pytest.raises(HledgerError):
            load_report(journal, "bs")


@pytest.mark.skipif(False, reason="pure function, no hledger needed")
class TestExpandSearchQuery:
    """Tests for expand_search_query alias expansion."""

    def test_empty_string(self):
        """Empty input is returned unchanged."""
        assert expand_search_query("") == ""

    def test_no_aliases(self):
        """Queries without aliases pass through unchanged."""
        assert expand_search_query("desc:grocery") == "desc:grocery"

    def test_d_alias(self):
        """d: expands to desc:."""
        assert expand_search_query("d:grocery") == "desc:grocery"

    def test_ac_alias(self):
        """ac: expands to acct:."""
        assert expand_search_query("ac:food") == "acct:food"

    def test_am_alias(self):
        """am: expands to amt:."""
        assert expand_search_query("am:>100") == "amt:>100"

    def test_multiple_aliases(self):
        """Multiple aliases in one query are all expanded."""
        result = expand_search_query("d:grocery ac:food")
        assert result == "desc:grocery acct:food"

    def test_alias_mid_word_not_expanded(self):
        """Aliases that appear as part of a longer prefix are not expanded."""
        # "bad:" should not have "d:" expanded
        assert expand_search_query("bad:thing") == "bad:thing"

    def test_plain_text_unchanged(self):
        """Plain text without colons is returned unchanged."""
        assert expand_search_query("grocery shopping") == "grocery shopping"
