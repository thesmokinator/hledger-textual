"""Tests for the SummaryPane widget."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Digits, Static

from hledger_tui.widgets.summary_pane import (
    SummaryPane,
    _fmt_amount,
    _fmt_digits,
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
    """Tests for _fmt_amount helper."""

    def test_left_symbol(self):
        """Left-side single-char commodity is prepended."""
        assert _fmt_amount(Decimal("1234.56"), "€") == "€1,234.56"

    def test_right_code(self):
        """Multi-char commodity codes are appended with a space."""
        assert _fmt_amount(Decimal("500.00"), "EUR") == "500.00 EUR"

    def test_no_commodity(self):
        """Without a commodity, only the number is returned."""
        assert _fmt_amount(Decimal("42.00"), "") == "42.00"


class TestFmtDigits:
    """Tests for _fmt_digits helper (Digits-compatible formatting)."""

    def test_removes_commas(self):
        """Commas are removed for Digits widget compatibility."""
        assert _fmt_digits(Decimal("1234.56"), "€") == "€1234.56"

    def test_no_comma_passthrough(self):
        """Small amounts without commas pass through unchanged."""
        assert _fmt_digits(Decimal("42.00"), "€") == "€42.00"

    def test_right_code(self):
        """Multi-char commodity codes work correctly."""
        assert _fmt_digits(Decimal("1000.00"), "EUR") == "1000.00 EUR"

    def test_no_commodity(self):
        """Without a commodity, only the number is returned."""
        assert _fmt_digits(Decimal("1234.00"), "") == "1234.00"


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
        from hledger_tui.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("investments failed")

        monkeypatch.setattr(
            "hledger_tui.widgets.summary_pane.load_investment_positions", _raise
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            assert app.query_one(SummaryPane) is not None

    async def test_load_investment_cost_error_does_not_crash(
        self, summary_journal: Path, monkeypatch
    ):
        """HledgerError during investment cost load is silently handled."""
        from hledger_tui.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("cost failed")

        monkeypatch.setattr(
            "hledger_tui.widgets.summary_pane.load_investment_cost", _raise
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            assert app.query_one(SummaryPane) is not None

    async def test_load_period_error_does_not_crash(
        self, summary_journal: Path, monkeypatch
    ):
        """HledgerError during period summary load is silently handled."""
        from hledger_tui.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("period failed")

        monkeypatch.setattr(
            "hledger_tui.widgets.summary_pane.load_period_summary", _raise
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            assert app.query_one(SummaryPane) is not None

    async def test_load_breakdown_error_does_not_crash(
        self, summary_journal: Path, monkeypatch
    ):
        """HledgerError during breakdown load is silently handled."""
        from hledger_tui.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("breakdown failed")

        monkeypatch.setattr(
            "hledger_tui.widgets.summary_pane.load_expense_breakdown", _raise
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
            income_widget = app.query_one("#card-income-value", Digits)
            assert "3000" in income_widget.value

    async def test_cards_show_expenses_after_load(self, summary_journal: Path):
        """After loading, the expenses card shows the expected amount."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            expenses_widget = app.query_one("#card-expenses-value", Digits)
            assert "40" in expenses_widget.value

    async def test_empty_journal_shows_zeros(self, empty_summary_journal: Path):
        """An empty journal shows zero amounts in all cards."""
        app = _SummaryApp(empty_summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            for widget_id in (
                "#card-income-value",
                "#card-expenses-value",
                "#card-net-value",
            ):
                widget = app.query_one(widget_id, Digits)
                assert "0.00" in widget.value

    async def test_period_error_shows_dashes(
        self, summary_journal: Path, monkeypatch
    ):
        """When load_period_summary raises HledgerError, cards show double-dashes."""
        from hledger_tui.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("period failed")

        monkeypatch.setattr(
            "hledger_tui.widgets.summary_pane.load_period_summary", _raise
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            for widget_id in (
                "#card-income-value",
                "#card-expenses-value",
                "#card-net-value",
            ):
                widget = app.query_one(widget_id, Digits)
                assert widget.value == "--"


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


