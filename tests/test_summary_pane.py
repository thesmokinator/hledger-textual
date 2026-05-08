"""Tests for the SummaryPane widget."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Digits, Static

from hledger_textual.widgets.formatting import (
    compute_saving_rate,
    fmt_amount,
)
from hledger_textual.widgets.summary_pane import (
    SummaryPane,
    _progress_bar,
)
from tests.conftest import has_hledger


class _SummaryApp(App):
    """Minimal app wrapping SummaryPane for isolated widget testing."""

    def __init__(self, journal_file: Path) -> None:
        """Initialize with a journal file path."""
        super().__init__()
        self._journal_file = journal_file

    def compose(self) -> ComposeResult:
        """Compose a single SummaryPane."""
        yield SummaryPane(self._journal_file)


@pytest.fixture
def summary_journal(tmp_path: Path) -> Path:
    """A minimal journal with current-month transactions."""
    today = date.today()
    d1 = today.replace(day=1)
    d2 = today.replace(day=2)
    content = (
        f"{d1.isoformat()} * Grocery shopping\n"
        "    expenses:food              €40.80\n"
        "    assets:bank:checking\n"
        "\n"
        f"{d2.isoformat()} Salary\n"
        "    assets:bank:checking     €3000.00\n"
        "    income:salary\n"
    )
    journal = tmp_path / "test.journal"
    journal.write_text(content)
    return journal


@pytest.fixture
def empty_summary_journal(tmp_path: Path) -> Path:
    """An empty journal for edge-case testing."""
    journal = tmp_path / "empty.journal"
    journal.write_text("")
    return journal


# ------------------------------------------------------------------
# Pure-function tests (no hledger needed)
# ------------------------------------------------------------------


class TestFmtAmount:
    """Tests for fmt_amount helper."""

    def test_left_symbol(self):
        """Left-side single-char commodity is prepended."""
        assert fmt_amount(Decimal("1234.56"), "€") == "€1,234.56"

    def test_right_code(self):
        """Multi-char commodity codes are appended with a space."""
        assert fmt_amount(Decimal("500.00"), "EUR") == "500.00 EUR"

    def test_no_commodity(self):
        """Without a commodity, only the number is returned."""
        assert fmt_amount(Decimal("42.00"), "") == "42.00"



class TestProgressBar:
    """Tests for _progress_bar helper."""

    def test_empty(self):
        """0% produces all empty blocks."""
        assert _progress_bar(0.0) == "░░░░░░░░"

    def test_full(self):
        """100%+ produces all filled blocks."""
        assert _progress_bar(100.0) == "████████"

    def test_half(self):
        """50% produces half filled, half empty."""
        assert _progress_bar(50.0) == "████░░░░"

    def test_custom_width(self):
        """Custom width is respected."""
        bar = _progress_bar(50.0, width=4)
        assert len(bar) == 4
        assert bar == "██░░"


class TestComputeSavingRate:
    """Tests for compute_saving_rate helper."""

    def test_positive_saving(self):
        """Saving rate for income > expenses is positive."""
        rate = compute_saving_rate(Decimal("3000"), Decimal("1200"))
        assert rate == pytest.approx(60.0)

    def test_zero_saving(self):
        """Saving rate is 0% when expenses equal income."""
        rate = compute_saving_rate(Decimal("1000"), Decimal("1000"))
        assert rate == pytest.approx(0.0)

    def test_negative_saving(self):
        """Saving rate is negative when expenses exceed income."""
        rate = compute_saving_rate(Decimal("1000"), Decimal("1500"))
        assert rate == pytest.approx(-50.0)

    def test_zero_income_returns_none(self):
        """Returns None when income is zero (division by zero guard)."""
        assert compute_saving_rate(Decimal("0"), Decimal("500")) is None

    def test_negative_income_returns_none(self):
        """Returns None when income is negative."""
        assert compute_saving_rate(Decimal("-100"), Decimal("50")) is None

    def test_no_expenses(self):
        """Saving rate is 100% when there are no expenses."""
        rate = compute_saving_rate(Decimal("2000"), Decimal("0"))
        assert rate == pytest.approx(100.0)


# ------------------------------------------------------------------
# Integration tests (require hledger)
# ------------------------------------------------------------------


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSummaryPaneMount:
    """Tests for SummaryPane initial render."""

    async def test_pane_mounts_without_error(self, summary_journal: Path):
        """SummaryPane mounts without raising exceptions."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(SummaryPane) is not None

    async def test_breakdown_table_exists(self, summary_journal: Path):
        """The breakdown DataTable is present in the widget tree."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#summary-breakdown-table")
            assert table is not None

    async def test_portfolio_table_exists(self, summary_journal: Path):
        """The portfolio DataTable is present in the widget tree."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#summary-portfolio-table")
            assert table is not None



@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSummaryPaneDataLoad:
    """Tests for background data loading in SummaryPane."""

    async def test_load_investments_error_does_not_crash(
        self, summary_journal: Path, monkeypatch
    ):
        """HledgerError during investment positions load is silently handled."""
        from hledger_textual.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("investments failed")

        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_investment_positions", _raise
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            assert app.query_one(SummaryPane) is not None

    async def test_load_investment_cost_error_does_not_crash(
        self, summary_journal: Path, monkeypatch
    ):
        """HledgerError during investment cost load is silently handled."""
        from hledger_textual.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("cost failed")

        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_investment_cost", _raise
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            assert app.query_one(SummaryPane) is not None

    async def test_load_period_error_does_not_crash(
        self, summary_journal: Path, monkeypatch
    ):
        """HledgerError during period summary load is silently handled."""
        from hledger_textual.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("period failed")

        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_period_summary", _raise
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            assert app.query_one(SummaryPane) is not None

    async def test_load_breakdown_error_does_not_crash(
        self, summary_journal: Path, monkeypatch
    ):
        """HledgerError during breakdown load is silently handled."""
        from hledger_textual.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("breakdown failed")

        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_expense_breakdown", _raise
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            assert app.query_one(SummaryPane) is not None


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSummaryPaneRefresh:
    """Tests for the refresh action."""

    async def test_r_key_triggers_refresh(self, summary_journal: Path):
        """Pressing r reloads data without crashing."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            await pilot.press("r")
            await pilot.pause(delay=0.5)
            assert app.query_one(SummaryPane) is not None


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSummaryPaneCards:
    """Tests for the Income / Expenses / Net cards after data load."""

    async def test_cards_show_income_after_load(self, summary_journal: Path):
        """After loading, the income card shows the expected amount."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            income_widget = app.query_one(".income-value", Digits)
            assert "3,000" in income_widget.value

    async def test_cards_show_expenses_after_load(self, summary_journal: Path):
        """After loading, the expenses card shows the expected amount."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            expenses_widget = app.query_one(".expenses-value", Digits)
            assert "40" in expenses_widget.value

    async def test_empty_journal_shows_zeros(self, empty_summary_journal: Path):
        """An empty journal shows zero amounts in all cards."""
        app = _SummaryApp(empty_summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            for widget_id in (
                ".income-value",
                ".expenses-value",
                ".net-value",
            ):
                widget = app.query_one(widget_id, Digits)
                assert "0.00" in widget.value

    async def test_period_error_shows_dashes(
        self, summary_journal: Path, monkeypatch
    ):
        """When load_period_summary raises HledgerError, cards show double-dashes."""
        from hledger_textual.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("period failed")

        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_period_summary", _raise
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            for widget_id in (
                ".income-value",
                ".expenses-value",
                ".net-value",
            ):
                widget = app.query_one(widget_id, Digits)
                assert widget.value == "--"

    async def test_saving_rate_displayed(self, summary_journal: Path):
        """After loading, the saving rate is shown in the Net card."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            rate_widget = app.query_one(".saving-rate", Static)
            assert "Saving rate:" in rate_widget.renderable
            assert "99%" in rate_widget.renderable

    async def test_saving_rate_cleared_on_error(
        self, summary_journal: Path, monkeypatch
    ):
        """When period summary fails, saving rate widget is empty."""
        from hledger_textual.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("period failed")

        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_period_summary", _raise
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            rate_widget = app.query_one(".saving-rate", Static)
            assert rate_widget.renderable == ""


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSummaryPaneDynamicTitles:
    """Tests for dynamic month-name section titles."""

    async def test_overview_title(self, summary_journal: Path):
        """The overview title is the static string 'Overview'."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            title = app.query_one("#summary-overview-title", Static)
            assert str(title.renderable) == "Overview"

    async def test_breakdown_title_contains_month(self, summary_journal: Path):
        """The breakdown title includes the current month name."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            title = app.query_one("#summary-breakdown-title", Static)
            month_name = date.today().strftime("%B %Y")
            assert month_name in str(title.renderable)


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSummaryPaneBreakdown:
    """Tests for the expense breakdown table."""

    async def test_breakdown_shows_expense_accounts(self, summary_journal: Path):
        """After loading, the breakdown table has at least one row."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            table = app.query_one("#summary-breakdown-table", DataTable)
            assert table.row_count > 0

    async def test_empty_breakdown_shows_message(self, empty_summary_journal: Path):
        """An empty journal shows the EmptyState widget instead of breakdown sections."""
        app = _SummaryApp(empty_summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            empty_state = app.query_one("#summary-empty-state")
            assert empty_state.display is True
            content = app.query_one("#summary-content")
            assert content.display is False


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSummaryPaneIncomeBreakdown:
    """Tests for the income breakdown table."""

    async def test_income_table_exists(self, summary_journal: Path):
        """The income breakdown DataTable is present in the widget tree."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#summary-income-table")
            assert table is not None

    async def test_income_breakdown_shows_accounts(self, summary_journal: Path):
        """After loading, the income table has at least one row."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            table = app.query_one("#summary-income-table", DataTable)
            assert table.row_count > 0

    async def test_empty_income_shows_message(self, empty_summary_journal: Path):
        """An empty journal hides the income table behind the EmptyState widget."""
        app = _SummaryApp(empty_summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            empty_state = app.query_one("#summary-empty-state")
            assert empty_state.display is True
            content = app.query_one("#summary-content")
            assert content.display is False


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestGroupPositionsByCommodity:
    """Tests for the _group_positions_by_commodity helper method."""

    async def test_groups_correctly(self, summary_journal: Path):
        """Positions are grouped by commodity name."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.query_one(SummaryPane)
            positions = [
                ("assets:invest:a", Decimal("10"), "VWCE"),
                ("assets:invest:b", Decimal("5"), "VWCE"),
                ("assets:invest:c", Decimal("20"), "AGGH"),
            ]
            result = pane._group_positions_by_commodity(positions)
            assert set(result.keys()) == {"VWCE", "AGGH"}
            assert len(result["VWCE"]) == 2
            assert len(result["AGGH"]) == 1
            # Verify individual entries
            assert ("assets:invest:a", Decimal("10")) in result["VWCE"]
            assert ("assets:invest:b", Decimal("5")) in result["VWCE"]
            assert ("assets:invest:c", Decimal("20")) in result["AGGH"]

    async def test_empty_positions(self, summary_journal: Path):
        """An empty positions list returns an empty dict."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.query_one(SummaryPane)
            result = pane._group_positions_by_commodity([])
            assert result == {}


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSummaryPaneLiabilities:
    """Tests for the liabilities section in SummaryPane."""

    @pytest.fixture
    def liabilities_journal(self, tmp_path: Path) -> Path:
        """A journal with liability accounts and current-month transactions."""
        today = date.today()
        d1 = today.replace(day=1)
        content = (
            "2026-01-01 Mortgage\n"
            "    liabilities:mortgage          €-200000.00\n"
            "    assets:bank:checking\n"
            "\n"
            f"{d1.isoformat()} * Grocery shopping\n"
            "    expenses:food              €40.80\n"
            "    assets:bank:checking\n"
            "\n"
            f"{d1.isoformat()} Salary\n"
            "    assets:bank:checking     €3000.00\n"
            "    income:salary\n"
        )
        journal = tmp_path / "test.journal"
        journal.write_text(content)
        return journal

    async def test_liabilities_table_exists(self, summary_journal: Path):
        """The liabilities DataTable is present in the widget tree."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#summary-liabilities-table")
            assert table is not None

    async def test_liabilities_hidden_when_empty(self, summary_journal: Path):
        """Liabilities section is hidden when no liability accounts exist."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            section = app.query_one("#summary-liabilities")
            assert section.display is False

    async def test_liabilities_shown_when_present(self, liabilities_journal: Path):
        """Liabilities section is visible when liability accounts exist."""
        app = _SummaryApp(liabilities_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            section = app.query_one("#summary-liabilities")
            assert section.display is True

    async def test_liabilities_table_has_rows(self, liabilities_journal: Path):
        """Liabilities table has rows when liabilities exist."""
        app = _SummaryApp(liabilities_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            table = app.query_one("#summary-liabilities-table", DataTable)
            assert table.row_count > 0

    async def test_liabilities_error_does_not_crash(
        self, summary_journal: Path, monkeypatch
    ):
        """HledgerError during liabilities load is silently handled."""
        from hledger_textual.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("liabilities failed")

        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_liabilities_breakdown", _raise
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            assert app.query_one(SummaryPane) is not None


