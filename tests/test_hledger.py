"""Tests for hledger CLI reader."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from hledger_textual.hledger import (
    HledgerError,
    _parse_budget_amount,
    _parse_report_csv,
    escape_for_hledger,
    expand_search_query,
    get_hledger_version,
    load_account_balances,
    load_accounts,
    load_descriptions,
    load_expense_breakdown,
    load_income_breakdown,
    load_investment_cost,
    load_investment_eur_by_account,
    load_investment_positions,
    load_investment_report,
    load_journal_stats,
    load_liabilities_breakdown,
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

    # --- European format (comma as decimal, dot as thousands) ---

    def test_european_no_thousands(self):
        """European decimal comma without thousands separator: €100,00 → 100.00."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("€100,00")
        assert qty == Decimal("100.00")
        assert commodity == "€"

    def test_european_with_thousands(self):
        """European with dot thousands separator: €1.000,00 → 1000.00."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("€1.000,00")
        assert qty == Decimal("1000.00")
        assert commodity == "€"

    def test_european_salary(self):
        """European salary amount matching the fixture: €3.000,00 → 3000.00."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("€3.000,00")
        assert qty == Decimal("3000.00")
        assert commodity == "€"

    def test_european_right_side(self):
        """European format with right-side commodity code."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("1.000,00 EUR")
        assert qty == Decimal("1000.00")
        assert commodity == "EUR"

    def test_european_plain_number_decimal_comma(self):
        """Plain European decimal number (no commodity): 100,00 → 100.00."""
        from decimal import Decimal
        qty, commodity = _parse_budget_amount("100,00")
        assert qty == Decimal("100.00")
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


class TestLoadPeriodSummaryEuropeanFormat:
    """Integration tests for load_period_summary with European-format journals.

    These tests guard against the regression reported in issue #105 where amounts
    like €100,00 (European decimal comma) were parsed as 10000 instead of 100.00,
    producing 100x inflated totals in the Summary section.
    """

    def test_european_income(self, european_journal_path: Path):
        """Income parsed from European format journal should be 3000, not 300000."""
        summary = load_period_summary(european_journal_path, "2026-01")
        assert summary.income == Decimal("3000.00")

    def test_european_expenses(self, european_journal_path: Path):
        """Expenses from European format journal: food €150,00 + transport €50,00 = 200."""
        summary = load_period_summary(european_journal_path, "2026-01")
        assert summary.expenses == Decimal("200.00")

    def test_european_net(self, european_journal_path: Path):
        """Net from European format journal: 3000 - 200 = 2800."""
        summary = load_period_summary(european_journal_path, "2026-01")
        assert summary.net == Decimal("2800.00")

    def test_european_commodity(self, european_journal_path: Path):
        """Commodity detected from European format journal should be €."""
        summary = load_period_summary(european_journal_path, "2026-01")
        assert summary.commodity == "€"

    def test_us_income(self, us_journal_path: Path):
        """Income parsed from US format journal should be 3000."""
        summary = load_period_summary(us_journal_path, "2026-01")
        assert summary.income == Decimal("3000.00")

    def test_us_expenses(self, us_journal_path: Path):
        """Expenses from US format journal: food $150.00 + transport $50.00 = 200."""
        summary = load_period_summary(us_journal_path, "2026-01")
        assert summary.expenses == Decimal("200.00")

    def test_us_commodity(self, us_journal_path: Path):
        """Commodity detected from US format journal should be $."""
        summary = load_period_summary(us_journal_path, "2026-01")
        assert summary.commodity == "$"


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


class TestLoadReportTreeDepth:
    """Tests for tree-mode depth detection via real hledger."""

    def test_tree_depth_reflects_account_hierarchy(self, sample_journal_path: Path):
        """In tree mode, nested accounts have increasing depth."""
        data = load_report(sample_journal_path, "is", mode="tree")
        by_account = {r.account: r for r in data.rows}

        # sample.journal has expenses → food → groceries (depth 0 → 1 → 2)
        assert by_account["expenses"].depth == 0
        assert by_account["food"].depth == 1
        assert by_account["groceries"].depth == 2

    def test_tree_depth_account_name_stripped(self, sample_journal_path: Path):
        """Tree-mode account names no longer carry leading indentation."""
        data = load_report(sample_journal_path, "is", mode="tree")
        accounts = [r.account for r in data.rows]
        assert "groceries" in accounts
        assert not any(a.startswith(" ") for a in accounts)

    def test_tree_section_headers_and_totals_have_zero_depth(
        self, sample_journal_path: Path
    ):
        """Section headers and totals stay at depth 0 in tree mode."""
        data = load_report(sample_journal_path, "is", mode="tree")
        for row in data.rows:
            if row.is_section_header or row.is_total:
                assert row.depth == 0

    def test_flat_mode_all_rows_zero_depth(self, sample_journal_path: Path):
        """In flat mode every row has depth 0."""
        data = load_report(sample_journal_path, "is", mode="flat")
        for row in data.rows:
            assert row.depth == 0


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

    def test_load_report_passes_commodity_flag(self, monkeypatch, tmp_path: Path):
        """load_report passes -X <commodity> to hledger when commodity is set."""
        captured_args: list[str] = []

        def _capture(*args, **kwargs):
            captured_args.extend(args)
            return self._SAMPLE_CSV

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _capture)
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        load_report(journal, "cf", commodity="EUR")
        assert "-X" in captured_args
        idx = captured_args.index("-X")
        assert captured_args[idx + 1] == "EUR"

    def test_load_report_no_commodity_flag(self, monkeypatch, tmp_path: Path):
        """load_report does not pass -X when commodity is None."""
        captured_args: list[str] = []

        def _capture(*args, **kwargs):
            captured_args.extend(args)
            return self._SAMPLE_CSV

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _capture)
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        load_report(journal, "cf")
        assert "-X" not in captured_args

    def test_load_report_hledger_error(self, monkeypatch, tmp_path: Path):
        """HledgerError is raised when hledger fails."""
        def _raise(*args, **kwargs):
            raise HledgerError("command failed")

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _raise)
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        with pytest.raises(HledgerError):
            load_report(journal, "bs")

    def test_load_report_default_mode_is_flat(self, monkeypatch, tmp_path: Path):
        """load_report passes --flat to hledger by default."""
        captured_args: list[str] = []

        def _capture(*args, **kwargs):
            captured_args.extend(args)
            return self._SAMPLE_CSV

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _capture)
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        load_report(journal, "cf")
        assert "--flat" in captured_args
        assert "--tree" not in captured_args

    def test_load_report_tree_mode_passes_tree_flag(self, monkeypatch, tmp_path: Path):
        """load_report passes --tree when mode='tree'."""
        captured_args: list[str] = []

        def _capture(*args, **kwargs):
            captured_args.extend(args)
            return self._SAMPLE_CSV

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _capture)
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        load_report(journal, "cf", mode="tree")
        assert "--tree" in captured_args
        assert "--flat" not in captured_args

    def test_load_report_cache_key_distinguishes_modes(self, monkeypatch, tmp_path: Path):
        """Tree and flat results are cached under distinct keys."""
        from hledger_textual.cache import HledgerCache

        call_count = 0

        def _capture(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return self._SAMPLE_CSV

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _capture)
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        cache = HledgerCache()

        load_report(journal, "cf", cache=cache, mode="flat")
        load_report(journal, "cf", cache=cache, mode="flat")
        assert call_count == 1

        load_report(journal, "cf", cache=cache, mode="tree")
        assert call_count == 2

    def test_load_report_sort_amount_flag(self, monkeypatch, tmp_path: Path):
        """load_report passes --sort-amount only when sort_amount=True."""
        captured_args: list[str] = []

        def _capture(*args, **kwargs):
            captured_args.extend(args)
            return self._SAMPLE_CSV

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _capture)
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")

        load_report(journal, "cf")
        assert "--sort-amount" not in captured_args

        captured_args.clear()
        load_report(journal, "cf", sort_amount=True)
        assert "--sort-amount" in captured_args

    def test_load_report_cache_key_distinguishes_sort_amount(self, monkeypatch, tmp_path: Path):
        """Sorted and unsorted results are cached under distinct keys."""
        from hledger_textual.cache import HledgerCache

        call_count = 0

        def _capture(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return self._SAMPLE_CSV

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _capture)
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        cache = HledgerCache()

        load_report(journal, "cf", cache=cache, sort_amount=False)
        load_report(journal, "cf", cache=cache, sort_amount=False)
        assert call_count == 1

        load_report(journal, "cf", cache=cache, sort_amount=True)
        assert call_count == 2


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

    def test_t_alias(self):
        """t: expands to tag:."""
        assert expand_search_query("t:rule-id") == "tag:rule-id"

    def test_st_alias(self):
        """st: expands to status:."""
        assert expand_search_query("st:*") == "status:*"

    def test_t_alias_with_other_aliases(self):
        """t: and other aliases expand correctly in the same query."""
        result = expand_search_query("d:salary t:payroll")
        assert result == "desc:salary tag:payroll"


class TestEscapeForHledger:
    """Tests for escape_for_hledger helper."""

    def test_plain_account_unchanged(self):
        """Simple account names pass through unchanged."""
        assert escape_for_hledger("expenses:food") == "expenses:food"

    def test_spaces_not_escaped(self):
        """Spaces must NOT be escaped (hledger splits queries on spaces)."""
        assert escape_for_hledger("revenues:Cash Flow") == "revenues:Cash Flow"

    def test_dot_escaped(self):
        """Dots are regex metacharacters and must be escaped."""
        assert escape_for_hledger("expenses:v2.0") == r"expenses:v2\.0"

    def test_parentheses_escaped(self):
        """Parentheses are escaped."""
        assert escape_for_hledger("expenses:food (personal)") == r"expenses:food \(personal\)"

    def test_brackets_escaped(self):
        """Square brackets are escaped."""
        assert escape_for_hledger("assets:bank[1]") == r"assets:bank\[1\]"

    def test_backslash_escaped(self):
        """Backslashes are escaped."""
        assert escape_for_hledger(r"a\b") == r"a\\b"

    def test_dollar_and_caret_escaped(self):
        """Anchors in account names are escaped."""
        assert escape_for_hledger("price$mart") == r"price\$mart"
        assert escape_for_hledger("^special") == r"\^special"

    def test_pipe_and_star_escaped(self):
        """Other metacharacters are escaped."""
        assert escape_for_hledger("a|b") == r"a\|b"
        assert escape_for_hledger("a*b") == r"a\*b"

    def test_empty_string(self):
        """Empty input returns empty string."""
        assert escape_for_hledger("") == ""


class TestLoadInvestmentReport:
    """Tests for load_investment_report using monkeypatched run_hledger."""

    _SAMPLE_INV_CSV = (
        '"Monthly Balance Changes 2026-01-01..2026-03-01","",""\n'
        '"Account","Jan","Feb"\n'
        '"assets:investments:XDWD","€100.00","€200.00"\n'
        '"assets:investments:XEON","€8450.00","€0"\n'
        '"Total:","€8550.00","€200.00"\n'
    )

    def test_parses_investment_csv(self, monkeypatch, tmp_path: Path):
        """load_investment_report parses CSV output correctly."""
        monkeypatch.setattr(
            "hledger_textual.hledger.run_hledger",
            lambda *args, **kwargs: self._SAMPLE_INV_CSV,
        )
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        data = load_investment_report(journal)
        assert len(data.rows) == 3
        assert data.period_headers == ["Jan", "Feb"]
        assert data.rows[0].account == "assets:investments:XDWD"
        assert data.rows[2].is_total

    def test_empty_output_returns_empty(self, monkeypatch, tmp_path: Path):
        """Empty hledger output produces empty ReportData."""
        monkeypatch.setattr(
            "hledger_textual.hledger.run_hledger",
            lambda *args, **kwargs: "",
        )
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        data = load_investment_report(journal)
        assert data.title == ""
        assert data.rows == []

    def test_passes_commodity_flag(self, monkeypatch, tmp_path: Path):
        """load_investment_report passes -X <commodity> when set."""
        captured_args: list[str] = []

        def _capture(*args, **kwargs):
            captured_args.extend(args)
            return self._SAMPLE_INV_CSV

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _capture)
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        load_investment_report(journal, commodity="EUR")
        assert "-X" in captured_args
        assert captured_args[captured_args.index("-X") + 1] == "EUR"

    def test_passes_period_flags(self, monkeypatch, tmp_path: Path):
        """load_investment_report passes -b and -e flags when set."""
        captured_args: list[str] = []

        def _capture(*args, **kwargs):
            captured_args.extend(args)
            return self._SAMPLE_INV_CSV

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _capture)
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        load_investment_report(
            journal, period_begin="2026-01-01", period_end="2026-03-01"
        )
        assert "-b" in captured_args
        assert captured_args[captured_args.index("-b") + 1] == "2026-01-01"
        assert "-e" in captured_args
        assert captured_args[captured_args.index("-e") + 1] == "2026-03-01"

    def test_uses_bal_command(self, monkeypatch, tmp_path: Path):
        """load_investment_report uses 'bal' with 'assets:investments'."""
        captured_args: list[str] = []

        def _capture(*args, **kwargs):
            captured_args.extend(args)
            return self._SAMPLE_INV_CSV

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _capture)
        journal = tmp_path / "test.journal"
        journal.write_text("; empty\n")
        load_investment_report(journal)
        assert "bal" in captured_args
        assert "assets:investments" in captured_args


# ------------------------------------------------------------------
# Tests for get_hledger_version (monkeypatched, no hledger needed)
# ------------------------------------------------------------------


class TestGetHledgerVersion:
    """Tests for get_hledger_version."""

    def test_strips_program_prefix(self, monkeypatch):
        """The 'hledger ' prefix is stripped from the version string."""
        monkeypatch.setattr(
            "hledger_textual.hledger.run_hledger",
            lambda *args, **kwargs: "hledger 1.40.1, linux-x86_64\n",
        )
        assert get_hledger_version() == "1.40.1, linux-x86_64"

    def test_returns_raw_when_no_prefix(self, monkeypatch):
        """When output has no 'hledger ' prefix, the raw string is returned."""
        monkeypatch.setattr(
            "hledger_textual.hledger.run_hledger",
            lambda *args, **kwargs: "1.40.1\n",
        )
        assert get_hledger_version() == "1.40.1"

    def test_returns_question_mark_on_error(self, monkeypatch):
        """Returns '?' when hledger is not available."""
        def _raise(*args, **kwargs):
            raise HledgerError("not found")

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _raise)
        assert get_hledger_version() == "?"


# ------------------------------------------------------------------
# Tests for load_account_balances (require hledger)
# ------------------------------------------------------------------


class TestLoadAccountBalances:
    """Tests for load_account_balances."""

    def test_returns_account_balance_pairs(self, sample_journal_path: Path):
        """All accounts with balances are returned as (account, balance) tuples."""
        balances = load_account_balances(sample_journal_path)
        accounts = [row[0] for row in balances]
        assert "assets:bank:checking" in accounts

    def test_balances_are_non_empty_strings(self, sample_journal_path: Path):
        """Each balance value is a non-empty string."""
        balances = load_account_balances(sample_journal_path)
        assert all(bal for _, bal in balances)

    def test_empty_journal_returns_empty(self, tmp_path: Path):
        """An empty journal produces no balances."""
        journal = tmp_path / "empty.journal"
        journal.write_text("")
        balances = load_account_balances(journal)
        assert balances == []

    def test_multi_commodity_no_duplicate_accounts(self, tmp_path: Path):
        """Multi-commodity accounts produce one row, not one per commodity.

        Regression test for #89: with --layout=bare in hledger.conf, the
        same account appeared multiple times, causing DuplicateKey errors.
        """
        journal = tmp_path / "multi.journal"
        journal.write_text(
            "2021-07-27 give dollars, get euros\n"
            "    assets:cash      USD -10.00 @@ EUR 8.50\n"
            "    assets:cash      EUR   8.50\n"
        )
        balances = load_account_balances(journal)
        accounts = [row[0] for row in balances]
        assert accounts.count("assets:cash") == 1


class TestRunHledgerOverrides:
    """Tests for run_hledger command-line overrides."""

    def test_no_conf_always_present(self, monkeypatch):
        """run_hledger always passes --no-conf to ignore hledger.conf.

        Regression test for #93: hledger.conf with -f caused double counting.
        """
        import subprocess

        captured_cmd = []
        original_run = subprocess.run

        def _capture(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", _capture)
        from hledger_textual.hledger import run_hledger

        try:
            run_hledger("print", "-O", "json")
        except Exception:
            pass
        assert "--no-conf" in captured_cmd

    def test_balance_command_includes_layout_wide(self, monkeypatch):
        """run_hledger appends --layout=wide to balance commands."""
        import subprocess

        captured_cmd = []
        original_run = subprocess.run

        def _capture(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", _capture)
        from hledger_textual.hledger import run_hledger

        try:
            run_hledger("balance", "--flat", "-O", "csv")
        except Exception:
            pass
        assert "--layout=wide" in captured_cmd

    def test_non_balance_command_no_layout_flag(self, monkeypatch):
        """run_hledger does not add --layout to non-balance commands."""
        import subprocess

        captured_cmd = []
        original_run = subprocess.run

        def _capture(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", _capture)
        from hledger_textual.hledger import run_hledger

        try:
            run_hledger("print", "-O", "json")
        except Exception:
            pass
        assert "--layout=wide" not in captured_cmd


# ------------------------------------------------------------------
# Tests for load_income_breakdown (require hledger)
# ------------------------------------------------------------------


class TestLoadIncomeBreakdown:
    """Tests for load_income_breakdown."""

    @pytest.fixture
    def income_journal(self, tmp_path: Path) -> Path:
        """Create a journal with two income sources in the current month."""
        today = date.today()
        d1 = today.replace(day=1)
        d2 = today.replace(day=2)
        content = (
            f"{d1.isoformat()} Salary\n"
            f"    assets:bank  €3000.00\n"
            f"    income:salary\n"
            f"\n"
            f"{d2.isoformat()} Freelance\n"
            f"    assets:bank  €500.00\n"
            f"    income:freelance\n"
        )
        journal = tmp_path / "income.journal"
        journal.write_text(content)
        return journal

    def test_returns_income_accounts(self, income_journal: Path):
        """Both income accounts should be returned."""
        period = date.today().strftime("%Y-%m")
        breakdown = load_income_breakdown(income_journal, period)
        accounts = [row[0] for row in breakdown]
        assert "income:salary" in accounts
        assert "income:freelance" in accounts

    def test_sorted_by_amount_descending(self, income_journal: Path):
        """Results should be sorted by amount descending."""
        period = date.today().strftime("%Y-%m")
        breakdown = load_income_breakdown(income_journal, period)
        assert len(breakdown) == 2
        assert breakdown[0][1] >= breakdown[1][1]
        assert breakdown[0][0] == "income:salary"
        assert breakdown[0][1] == Decimal("3000.00")

    def test_empty_period_returns_empty(self, income_journal: Path):
        """A period with no transactions should return an empty list."""
        breakdown = load_income_breakdown(income_journal, "1999-01")
        assert breakdown == []


# ---------------------------------------------------------------------------
#  Account type query tests (issue #18)
#  Verify that type:R / type:X queries work with all naming conventions.
# ---------------------------------------------------------------------------

ACCOUNT_TYPE_FIXTURES = Path(__file__).parent / "fixtures" / "account_types"

_ACCOUNT_TYPE_JOURNALS = [
    pytest.param("standard.journal", id="standard"),
    pytest.param("type_tagged_revenues.journal", id="type-tagged-revenues"),
    pytest.param("mixed.journal", id="mixed"),
    pytest.param("custom_italian.journal", id="custom-italian"),
]


class TestAccountTypeQueries:
    """Ensure income/expense queries work regardless of account naming.

    All four fixture journals contain the same monetary totals
    (income €3500, expenses €200) but use different account names
    and type tag configurations.
    """

    PERIOD = "2026-03"

    @pytest.mark.parametrize("journal_name", _ACCOUNT_TYPE_JOURNALS)
    def test_period_summary_income(self, journal_name: str):
        """load_period_summary returns correct income for all naming styles."""
        summary = load_period_summary(
            ACCOUNT_TYPE_FIXTURES / journal_name, self.PERIOD,
        )
        assert summary.income == Decimal("3500.00")

    @pytest.mark.parametrize("journal_name", _ACCOUNT_TYPE_JOURNALS)
    def test_period_summary_expenses(self, journal_name: str):
        """load_period_summary returns correct expenses for all naming styles."""
        summary = load_period_summary(
            ACCOUNT_TYPE_FIXTURES / journal_name, self.PERIOD,
        )
        assert summary.expenses == Decimal("200.00")

    @pytest.mark.parametrize("journal_name", _ACCOUNT_TYPE_JOURNALS)
    def test_period_summary_net(self, journal_name: str):
        """load_period_summary returns correct net for all naming styles."""
        summary = load_period_summary(
            ACCOUNT_TYPE_FIXTURES / journal_name, self.PERIOD,
        )
        assert summary.net == Decimal("3300.00")

    @pytest.mark.parametrize("journal_name", _ACCOUNT_TYPE_JOURNALS)
    def test_period_summary_commodity(self, journal_name: str):
        """load_period_summary detects commodity for all naming styles."""
        summary = load_period_summary(
            ACCOUNT_TYPE_FIXTURES / journal_name, self.PERIOD,
        )
        assert summary.commodity == "€"

    @pytest.mark.parametrize("journal_name", _ACCOUNT_TYPE_JOURNALS)
    def test_income_breakdown_count(self, journal_name: str):
        """load_income_breakdown returns two accounts for all naming styles."""
        breakdown = load_income_breakdown(
            ACCOUNT_TYPE_FIXTURES / journal_name, self.PERIOD,
        )
        assert len(breakdown) == 2

    @pytest.mark.parametrize("journal_name", _ACCOUNT_TYPE_JOURNALS)
    def test_income_breakdown_amounts(self, journal_name: str):
        """load_income_breakdown returns correct amounts for all naming styles."""
        breakdown = load_income_breakdown(
            ACCOUNT_TYPE_FIXTURES / journal_name, self.PERIOD,
        )
        amounts = sorted([row[1] for row in breakdown], reverse=True)
        assert amounts == [Decimal("3000.00"), Decimal("500.00")]

    @pytest.mark.parametrize("journal_name", _ACCOUNT_TYPE_JOURNALS)
    def test_expense_breakdown_count(self, journal_name: str):
        """load_expense_breakdown returns two accounts for all naming styles."""
        breakdown = load_expense_breakdown(
            ACCOUNT_TYPE_FIXTURES / journal_name, self.PERIOD,
        )
        assert len(breakdown) == 2

    @pytest.mark.parametrize("journal_name", _ACCOUNT_TYPE_JOURNALS)
    def test_expense_breakdown_amounts(self, journal_name: str):
        """load_expense_breakdown returns correct amounts for all naming styles."""
        breakdown = load_expense_breakdown(
            ACCOUNT_TYPE_FIXTURES / journal_name, self.PERIOD,
        )
        amounts = sorted([row[1] for row in breakdown], reverse=True)
        assert amounts == [Decimal("120.00"), Decimal("80.00")]


# ------------------------------------------------------------------
# Tests for load_liabilities_breakdown (require hledger)
# ------------------------------------------------------------------


class TestLoadLiabilitiesBreakdown:
    """Tests for load_liabilities_breakdown."""

    @pytest.fixture
    def liabilities_journal(self, tmp_path: Path) -> Path:
        """Create a journal with liability accounts."""
        content = (
            "2026-01-01 Mortgage\n"
            "    liabilities:mortgage          €-200000.00\n"
            "    assets:bank:checking\n"
            "\n"
            "2026-01-15 Credit card bill\n"
            "    liabilities:credit-card       €-1500.00\n"
            "    expenses:shopping              €1500.00\n"
        )
        journal = tmp_path / "liabilities.journal"
        journal.write_text(content)
        return journal

    def test_returns_liability_accounts(self, liabilities_journal: Path):
        """Both liability accounts should be returned."""
        breakdown = load_liabilities_breakdown(liabilities_journal)
        accounts = [row[0] for row in breakdown]
        assert "liabilities:mortgage" in accounts
        assert "liabilities:credit-card" in accounts

    def test_sorted_by_amount_descending(self, liabilities_journal: Path):
        """Results should be sorted by amount descending."""
        breakdown = load_liabilities_breakdown(liabilities_journal)
        assert len(breakdown) == 2
        assert breakdown[0][1] >= breakdown[1][1]
        assert breakdown[0][0] == "liabilities:mortgage"

    def test_amounts_are_absolute(self, liabilities_journal: Path):
        """Amounts should be positive (absolute values)."""
        breakdown = load_liabilities_breakdown(liabilities_journal)
        for _, qty, _ in breakdown:
            assert qty > 0

    def test_empty_journal_returns_empty(self, tmp_path: Path):
        """An empty journal produces no liabilities."""
        journal = tmp_path / "empty.journal"
        journal.write_text("")
        breakdown = load_liabilities_breakdown(journal)
        assert breakdown == []

    def test_no_liabilities_returns_empty(self, sample_journal_path: Path):
        """A journal without liabilities returns an empty list."""
        breakdown = load_liabilities_breakdown(sample_journal_path)
        assert breakdown == []
