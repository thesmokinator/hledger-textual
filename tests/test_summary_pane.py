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
    _conversion_note,
    _portfolio_rows,
    _progress_bar,
    _share_cell,
    _share_pct,
    _totals_by_commodity,
)
from tests.conftest import has_hledger, wait_until


def _cards_applied(app) -> bool:
    """True once the summary cards show a numeric net (worker has finished)."""
    try:
        value = app.query_one(".net-value", Digits).value
    except Exception:
        return False
    return value not in ("", "--")


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



class TestPortfolioRows:
    """Tests for the per-commodity portfolio computation."""

    def test_gain_row(self) -> None:
        """Avg cost, P/L and share are computed when all data is known."""
        rows = _portfolio_rows(
            {"BTC": [("assets:crypto:wallet", Decimal("0.01"))]},
            {"assets:crypto:wallet": (Decimal("500"), "€")},
            {"BTC": "BTC-USD"},
            {"assets:crypto:wallet": (Decimal("600"), "€")},
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.quantity == Decimal("0.01")
        assert row.avg_cost == Decimal("50000")
        assert row.unrealised_pl == Decimal("100")
        assert row.portfolio_pct == pytest.approx(100.0)

    def test_loss_and_shares_split(self) -> None:
        """Two commodities split the portfolio by market value."""
        rows = _portfolio_rows(
            {
                "BTC": [("assets:crypto:btc", Decimal("0.01"))],
                "ETH": [("assets:crypto:eth", Decimal("1"))],
            },
            {
                "assets:crypto:btc": (Decimal("500"), "€"),
                "assets:crypto:eth": (Decimal("200"), "€"),
            },
            {"BTC": "BTC-USD", "ETH": "ETH-USD"},
            {
                "assets:crypto:btc": (Decimal("400"), "€"),
                "assets:crypto:eth": (Decimal("200"), "€"),
            },
        )
        by_com = {row.commodity: row for row in rows}
        assert by_com["BTC"].unrealised_pl == Decimal("-100")
        assert by_com["ETH"].unrealised_pl == Decimal("0")
        assert by_com["BTC"].portfolio_pct == pytest.approx(400 / 600 * 100)
        assert by_com["ETH"].portfolio_pct == pytest.approx(200 / 600 * 100)

    def test_missing_market_gives_dashes(self) -> None:
        """Without prices, market, P/L and share are all unknown."""
        (row,) = _portfolio_rows(
            {"BTC": [("assets:crypto:wallet", Decimal("0.01"))]},
            {"assets:crypto:wallet": (Decimal("500"), "€")},
            {},
            None,
        )
        assert row.market_total is None
        assert row.avg_cost == Decimal("50000")
        assert row.unrealised_pl is None
        assert row.portfolio_pct is None

    def test_unconvertible_market_is_ignored(self) -> None:
        """hledger echoing the original commodity means 'no price'."""
        (row,) = _portfolio_rows(
            {"BTC": [("assets:crypto:wallet", Decimal("0.01"))]},
            {"assets:crypto:wallet": (Decimal("500"), "€")},
            {"BTC": "BTC-USD"},
            {"assets:crypto:wallet": (Decimal("0.01"), "BTC")},
        )
        assert row.market_total is None
        assert row.unrealised_pl is None
        assert row.portfolio_pct is None

    def test_mixed_cost_currency_skips_pl(self) -> None:
        """P/L needs book and market in the same commodity."""
        (row,) = _portfolio_rows(
            {"BTC": [("assets:crypto:wallet", Decimal("0.01"))]},
            {"assets:crypto:wallet": (Decimal("550"), "USD")},
            {"BTC": "BTC-USD"},
            {"assets:crypto:wallet": (Decimal("600"), "€")},
        )
        assert row.unrealised_pl is None

    def test_zero_quantity_has_no_avg_cost(self) -> None:
        """A zero balance cannot produce an average cost."""
        (row,) = _portfolio_rows(
            {"BTC": [("assets:crypto:wallet", Decimal("0"))]},
            {"assets:crypto:wallet": (Decimal("0"), "€")},
            {},
            None,
        )
        assert row.avg_cost is None


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


class TestShareHelpers:
    """Tests for the percentage-share helpers used by the breakdowns."""

    def test_totals_by_commodity(self):
        """Amounts are summed per commodity."""
        rows = [
            ("income:salary", Decimal("3500"), "€"),
            ("income:freelance", Decimal("1740"), "€"),
            ("income:gifts", Decimal("0.01"), "BTC"),
        ]
        assert _totals_by_commodity(rows) == {
            "€": Decimal("5240"),
            "BTC": Decimal("0.01"),
        }

    def test_share_in_target_commodity(self):
        """Rows in the target commodity are divided by the target total."""
        totals = {"€": Decimal("5240"), "BTC": Decimal("0.01")}
        assert _share_pct(Decimal("3500"), "€", totals, "€") == pytest.approx(
            66.7939, rel=1e-3
        )

    def test_share_of_unconverted_row_is_none(self):
        """A row left in another commodity has no comparable denominator."""
        totals = {"€": Decimal("5240"), "BTC": Decimal("0.01")}
        assert _share_pct(Decimal("0.01"), "BTC", totals, "€") is None

    def test_single_currency_without_target(self):
        """Single-currency journals keep their percentages without -X."""
        totals = {"€": Decimal("1000")}
        assert _share_pct(Decimal("250"), "€", totals, None) == pytest.approx(25.0)

    def test_mixed_currencies_without_target_is_none(self):
        """Mixing currencies without a target must not produce a fake share."""
        totals = {"€": Decimal("1000"), "£": Decimal("500")}
        assert _share_pct(Decimal("500"), "£", totals, None) is None

    def test_zero_total_is_none(self):
        """A zero denominator yields no percentage."""
        assert _share_pct(Decimal("0"), "€", {"€": Decimal("0")}, "€") is None

    def test_share_cell_without_share(self):
        """Unknown shares render as an em dash."""
        assert _share_cell(None) == "\u2014"

    def test_share_cell_with_share(self):
        """Known shares render a bar plus a rounded percentage."""
        assert _share_cell(50.0, width=4) == "██░░ 50%"

    def test_note_for_unconverted_commodity(self):
        """The note names the commodities excluded from percentages."""
        note = _conversion_note({"€": Decimal("1000"), "BTC": Decimal("0.01")}, "€")
        assert "BTC" in note

    def test_no_note_when_everything_converted(self):
        """No note when all rows share the target commodity."""
        assert _conversion_note({"€": Decimal("1000")}, "€") == ""

    def test_note_for_mixed_currencies_without_target(self):
        """Without a default commodity the note suggests setting one."""
        note = _conversion_note({"€": Decimal("1000"), "£": Decimal("500")}, None)
        assert "default_commodity" in note


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


def _foldable_journal(tmp_path: Path) -> Path:
    """A journal with visible liabilities and investment sections."""
    today = date.today()
    d1 = today.replace(day=1).isoformat()
    journal = tmp_path / "fold.journal"
    journal.write_text(
        "commodity €1,000.00\n"
        "commodity 0.00000000 BTC\n"
        "\n"
        f"{d1} * Salary\n"
        "    assets:bank:checking   €3500.00\n"
        "    income:salary\n"
        "\n"
        f"{d1} * Credit card\n"
        "    liabilities:credit-card   €-200.00\n"
        "    expenses:food\n"
        "\n"
        f"{d1} * Gift\n"
        "    assets:investments:crypto   0.01000000 BTC\n"
        "    income:gifts\n"
    )
    return journal


def _investment_journal(tmp_path: Path) -> Path:
    """A journal with a 0.01 BTC holding bought with euros."""
    today = date.today()
    d1 = today.replace(day=1).isoformat()
    journal = tmp_path / "invest.journal"
    journal.write_text(
        "commodity €1,000.00\n"
        "commodity 0.00000000 BTC\n"
        "\n"
        f"{d1} * Gift\n"
        "    assets:investments:crypto   0.01000000 BTC\n"
        "    income:gifts\n"
    )
    return journal


def _mock_market(monkeypatch, tmp_path: Path, market: Decimal) -> None:
    """Pretend pricehist is configured with a fixed BTC market value."""
    prices = tmp_path / "prices.db"
    prices.write_text("")
    monkeypatch.setattr(
        "hledger_textual.widgets.summary_pane.resolve_default_commodity",
        lambda _file: "€",
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.summary_pane.has_pricehist", lambda: True
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.summary_pane.load_price_tickers",
        lambda: {"BTC": "BTC-USD"},
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.summary_pane.get_prices_file",
        lambda _tickers: prices,
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.summary_pane.load_investment_cost",
        lambda _file: {"assets:investments:crypto": (Decimal("500"), "€")},
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.summary_pane.load_investment_eur_by_account",
        lambda _file, _prices: {
            "assets:investments:crypto": (market, "€")
        },
    )


def _portfolio_market(app) -> str:
    """Return the first portfolio row's market value, or "" while loading."""
    try:
        rows = _table_rows(app, "#summary-portfolio-table")
    except Exception:
        return ""
    if not rows or len(rows[0]) < 4:
        return ""
    return rows[0][3]


class TestCollapsibleSections:
    """Pilot tests for the i/l section folding (issue #165)."""

    async def test_liabilities_fold(self, tmp_path: Path):
        """Pressing l hides the liabilities table, pressing again restores it."""
        app = _SummaryApp(_foldable_journal(tmp_path))
        async with app.run_test() as pilot:
            await wait_until(
                pilot,
                lambda: _table_row_count(app, "#summary-liabilities-table") >= 1,
            )
            table = app.query_one("#summary-liabilities-table", DataTable)
            title = app.query_one("#summary-liabilities-title", Static)
            assert table.display is True

            await pilot.press("l")
            await pilot.pause()
            assert table.display is False
            assert str(title.content) == "▸ Liabilities"

            await pilot.press("l")
            await pilot.pause()
            assert table.display is True
            assert str(title.content) == "Liabilities"

    async def test_investments_fold(self, tmp_path: Path):
        """Pressing i hides the investments table, pressing again restores it."""
        app = _SummaryApp(_foldable_journal(tmp_path))
        async with app.run_test() as pilot:
            await wait_until(
                pilot,
                lambda: _table_row_count(app, "#summary-portfolio-table") >= 1,
            )
            table = app.query_one("#summary-portfolio-table", DataTable)
            title = app.query_one("#summary-portfolio-title", Static)

            await pilot.press("i")
            await pilot.pause()
            assert table.display is False
            assert str(title.content) == "▸ Investments"

            await pilot.press("i")
            await pilot.pause()
            assert table.display is True
            assert str(title.content) == "Investments"


class TestInvestmentPane:
    """Pilot tests for the portfolio table (issue #164)."""

    async def test_portfolio_has_six_columns(
        self, tmp_path: Path, monkeypatch
    ):
        """The portfolio table shows the symbol/cost/value/P/L layout."""
        _mock_market(monkeypatch, tmp_path, Decimal("600"))
        app = _SummaryApp(_investment_journal(tmp_path))
        async with app.run_test() as pilot:
            await wait_until(
                pilot,
                lambda: _portfolio_market(app) == "€600.00",
            )
            table = app.query_one("#summary-portfolio-table", DataTable)
            labels = [str(col.label) for col in table.columns.values()]
            assert labels == [
                "Symbol",
                "Quantity",
                "Avg Cost",
                "Market Value",
                "Unrealised P/L",
                "% of Portfolio",
            ]
            rows = _table_rows(app, "#summary-portfolio-table")
            assert rows[0][0] == "BTC"
            assert rows[0][2] == "€50,000.00"
            assert rows[0][3] == "€600.00"

    async def test_gain_row_is_green(self, tmp_path: Path, monkeypatch):
        """A market value above cost highlights the P/L cell green."""
        _mock_market(monkeypatch, tmp_path, Decimal("600"))
        app = _SummaryApp(_investment_journal(tmp_path))
        async with app.run_test() as pilot:
            await wait_until(
                pilot,
                lambda: _portfolio_market(app) == "€600.00",
            )
            table = app.query_one("#summary-portfolio-table", DataTable)
            pl_cell = table.get_row_at(0)[4]
            assert "[green]" in str(pl_cell)
            assert "100.00" in str(pl_cell)

    async def test_loss_row_is_red(self, tmp_path: Path, monkeypatch):
        """A market value below cost highlights the P/L cell red."""
        _mock_market(monkeypatch, tmp_path, Decimal("400"))
        app = _SummaryApp(_investment_journal(tmp_path))
        async with app.run_test() as pilot:
            await wait_until(
                pilot,
                lambda: _portfolio_market(app) == "€400.00",
            )
            table = app.query_one("#summary-portfolio-table", DataTable)
            pl_cell = table.get_row_at(0)[4]
            assert "[red]" in str(pl_cell)
            assert "100.00" in str(pl_cell)

    async def test_row_drill_down_opens_commodity_transactions(
        self, tmp_path: Path, monkeypatch
    ):
        """Enter on a portfolio row opens that commodity's transactions."""
        from hledger_textual.screens.account_transactions import (
            AccountTransactionsScreen,
        )

        _mock_market(monkeypatch, tmp_path, Decimal("600"))
        app = _SummaryApp(_investment_journal(tmp_path))
        async with app.run_test() as pilot:
            await wait_until(
                pilot,
                lambda: _portfolio_market(app) == "€600.00",
            )
            table = app.query_one("#summary-portfolio-table", DataTable)
            table.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, AccountTransactionsScreen)
            assert screen.commodity == "BTC"



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
            assert "Saving rate:" in rate_widget.content
            assert "99%" in rate_widget.content

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
            assert rate_widget.content == ""


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSummaryPaneDynamicTitles:
    """Tests for dynamic month-name section titles."""

    async def test_overview_title(self, summary_journal: Path):
        """The overview title is the static string 'Overview'."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            title = app.query_one("#summary-overview-title", Static)
            assert str(title.content) == "Overview"

    async def test_breakdown_title_contains_month(self, summary_journal: Path):
        """The breakdown title includes the current month name."""
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            title = app.query_one("#summary-breakdown-title", Static)
            month_name = date.today().strftime("%B %Y")
            assert month_name in str(title.content)


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


class TestSummaryPaneMulticurrency:
    """Currency conversion + per-currency line wiring in SummaryPane."""

    async def test_configured_commodity_passed_to_summary_loader(
        self, summary_journal: Path, monkeypatch
    ):
        """load_period_summary receives commodity from config; marquee populated."""
        from hledger_textual.models import PeriodSummary
        from hledger_textual.widgets.currency_marquee import CurrencyMarquee

        captured: dict = {}

        def _fake_summary(file, period=None, cache=None, commodity=None):
            captured["commodity"] = commodity
            return PeriodSummary(
                income=Decimal("100"), expenses=Decimal("40"), commodity="€"
            )

        def _fake_net(file, period=None, cache=None):
            captured["net_called"] = True
            return [("€", Decimal("50")), ("£", Decimal("10"))]

        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_period_summary", _fake_summary
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_period_net_by_commodity",
            _fake_net,
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.resolve_default_commodity",
            lambda _file: "€",
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_price_tickers", lambda: {}
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: _cards_applied(app))
            assert captured["commodity"] == "€"
            assert captured["net_called"] is True
            marquee = app.query_one(".summary-multicurrency", CurrencyMarquee)
            assert marquee.display is True
            assert "€" in marquee._text and "£" in marquee._text

    async def test_unconfigured_commodity_passes_none(
        self, summary_journal: Path, monkeypatch
    ):
        """Without a configured default, no -X conversion happens."""
        from hledger_textual.models import PeriodSummary

        captured: dict = {}

        def _fake_summary(file, period=None, cache=None, commodity=None):
            captured["commodity"] = commodity
            return PeriodSummary(
                income=Decimal("100"), expenses=Decimal("40"), commodity="€"
            )

        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_period_summary", _fake_summary
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_period_net_by_commodity",
            lambda *a, **k: [],
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.resolve_default_commodity",
            lambda _file: None,
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_price_tickers", lambda: {}
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: _cards_applied(app))
            assert captured["commodity"] is None

    async def test_net_by_commodity_error_falls_back_to_empty(
        self, summary_journal: Path, monkeypatch
    ):
        """HledgerError from the per-commodity loader leaves the marquee hidden."""
        from hledger_textual.hledger import HledgerError
        from hledger_textual.models import PeriodSummary
        from hledger_textual.widgets.currency_marquee import CurrencyMarquee

        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_period_summary",
            lambda *a, **k: PeriodSummary(
                income=Decimal("100"), expenses=Decimal("40"), commodity="€"
            ),
        )

        def _raise(*args, **kwargs):
            raise HledgerError("net by commodity failed")

        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_period_net_by_commodity",
            _raise,
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.resolve_default_commodity",
            lambda _file: None,
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_price_tickers", lambda: {}
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: _cards_applied(app))
            marquee = app.query_one(".summary-multicurrency", CurrencyMarquee)
            assert marquee.display is False
            marquee_text = marquee._text
            assert marquee_text == ""

    async def test_income_expenses_lists_threaded_to_cards(
        self, summary_journal: Path, monkeypatch
    ):
        """Per-side loaders feed income/expenses marquees on the real pane."""
        from hledger_textual.models import PeriodSummary
        from hledger_textual.widgets.currency_marquee import CurrencyMarquee

        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_period_summary",
            lambda *a, **k: PeriodSummary(
                income=Decimal("30000"),
                expenses=Decimal("10000"),
                commodity="€",
            ),
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.resolve_default_commodity",
            lambda _file: "€",
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_period_net_by_commodity",
            lambda *a, **k: [("€", Decimal("15000")), ("$", Decimal("5000"))],
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_period_income_by_commodity",
            lambda *a, **k: [("€", Decimal("25000")), ("$", Decimal("5000"))],
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_period_expenses_by_commodity",
            lambda *a, **k: [("€", Decimal("9000")), ("£", Decimal("1000"))],
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.load_price_tickers", lambda: {}
        )
        app = _SummaryApp(summary_journal)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: _cards_applied(app))
            from textual.css.query import NoMatches
            try:
                inc = app.query_one(".income-multicurrency", CurrencyMarquee)
                exp = app.query_one(".expenses-multicurrency", CurrencyMarquee)
                net = app.query_one(".summary-multicurrency", CurrencyMarquee)
            except NoMatches as exc:
                raise AssertionError(f"marquee missing: {exc}")
            assert inc.display is True and "€" in inc._text and "$" in inc._text
            assert exp.display is True and "€" in exp._text and "£" in exp._text
            assert net.display is True




def _table_row_count(app, selector: str) -> int:
    """Return a table's row count, or 0 while it is not mounted/loaded yet."""
    try:
        return app.query_one(selector, DataTable).row_count
    except Exception:
        return 0


def _table_rows(app, selector: str) -> list[tuple[str, ...]]:
    """Return a table's cells as plain strings, one tuple per row."""
    table = app.query_one(selector, DataTable)
    rows: list[tuple[str, ...]] = []
    for index in range(table.row_count):
        rows.append(
            tuple(
                cell.plain if hasattr(cell, "plain") else str(cell)
                for cell in table.get_row_at(index)
            )
        )
    return rows


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSummaryPaneMulticurrencyBreakdowns:
    """Breakdown percentages must use converted amounts (issue #217)."""

    @pytest.fixture
    def fx_journal(self, tmp_path: Path) -> Path:
        """A three-currency journal with explicit price directives."""
        today = date.today()
        d1 = today.replace(day=1).isoformat()
        d2 = today.replace(day=2).isoformat()
        d3 = today.replace(day=3).isoformat()
        journal = tmp_path / "fx.journal"
        journal.write_text(
            "commodity €1,000.00\n"
            "commodity £1,000.00\n"
            "commodity $1,000.00\n"
            "\n"
            f"P {d1} € £0.50\n"
            f"P {d1} € $2.00\n"
            "\n"
            f"{d1} * Salary\n"
            "    assets:bank:checking   €3500.00\n"
            "    income:salary\n"
            "\n"
            f"{d2} * Freelance\n"
            "    assets:bank:checking   £1500.00\n"
            "    income:freelance\n"
            "\n"
            f"{d2} * Subscriptions\n"
            "    expenses:subscriptions   €14.99\n"
            "    expenses:subscriptions    £8.99\n"
            "    assets:bank:checking\n"
            "\n"
            f"{d3} * Credit card\n"
            "    liabilities:credit-card   $-200.00\n"
            "    assets:bank:savings        $200.00\n"
            "    liabilities:credit-card    €-50.00\n"
            "    assets:bank:checking       €50.00\n"
        )
        return journal

    async def test_income_percentages_use_converted_totals(
        self, fx_journal: Path, monkeypatch
    ):
        """£1500 becomes €3000, so the shares are 54% / 46%, not 70% / 30%."""
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.resolve_default_commodity",
            lambda _file: "€",
        )
        app = _SummaryApp(fx_journal)
        async with app.run_test() as pilot:
            await wait_until(
                pilot, lambda: _table_row_count(app, "#summary-income-table") >= 2
            )
            rows = {row[0]: row for row in _table_rows(app, "#summary-income-table")}
            assert rows["income:salary"][1] == "€3,500.00"
            assert rows["income:freelance"][1] == "€3,000.00"
            assert rows["income:salary"][2].endswith("54%")
            assert rows["income:freelance"][2].endswith("46%")
            note = app.query_one("#summary-income-note", Static)
            assert note.display is False

    async def test_multi_commodity_expense_row_is_shown(
        self, fx_journal: Path, monkeypatch
    ):
        """The ``£8.99, €14.99`` cell is converted, not silently dropped."""
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.resolve_default_commodity",
            lambda _file: "€",
        )
        app = _SummaryApp(fx_journal)
        async with app.run_test() as pilot:
            await wait_until(
                pilot, lambda: _table_row_count(app, "#summary-breakdown-table") >= 1
            )
            rows = _table_rows(app, "#summary-breakdown-table")
            assert rows == [
                ("expenses:subscriptions", "€32.97", "████████████ 100%")
            ]

    async def test_multi_currency_liability_row_is_shown(
        self, fx_journal: Path, monkeypatch
    ):
        """The ``$-200.00, €-50.00`` liability row is converted and visible."""
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.resolve_default_commodity",
            lambda _file: "€",
        )
        app = _SummaryApp(fx_journal)
        async with app.run_test() as pilot:
            await wait_until(
                pilot, lambda: _table_row_count(app, "#summary-liabilities-table") >= 1
            )
            assert _table_rows(app, "#summary-liabilities-table") == [
                ("liabilities:credit-card", "€150.00", "████████████ 100%")
            ]

    async def test_unconverted_commodity_shows_dash_and_note(
        self, tmp_path: Path, monkeypatch
    ):
        """A commodity without a price keeps its amount and gets no percentage."""
        today = date.today()
        d1 = today.replace(day=1).isoformat()
        journal = tmp_path / "btc.journal"
        journal.write_text(
            "commodity €1,000.00\n"
            "commodity 0.00000000 BTC\n"
            "\n"
            f"{d1} * Salary\n"
            "    assets:bank:checking   €1000.00\n"
            "    income:salary\n"
            "\n"
            f"{d1} * Gift\n"
            "    assets:crypto:wallet   0.01000000 BTC\n"
            "    income:gifts\n"
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.resolve_default_commodity",
            lambda _file: "€",
        )
        app = _SummaryApp(journal)
        async with app.run_test() as pilot:
            await wait_until(
                pilot, lambda: _table_row_count(app, "#summary-income-table") >= 2
            )
            rows = {row[0]: row for row in _table_rows(app, "#summary-income-table")}
            assert rows["income:salary"][2].endswith("100%")
            assert rows["income:gifts"][2] == "\u2014"
            note = app.query_one("#summary-income-note", Static)
            assert note.display is True
            assert "BTC" in str(note.content)

    async def test_mixed_currencies_without_default_hide_percentages(
        self, tmp_path: Path, monkeypatch
    ):
        """No resolvable default commodity means no comparable denominator."""
        today = date.today()
        d1 = today.replace(day=1).isoformat()
        journal = tmp_path / "mixed.journal"
        journal.write_text(
            f"{d1} * Salary\n"
            "    assets:bank:checking   €1000.00\n"
            "    income:salary\n"
            "\n"
            f"{d1} * Freelance\n"
            "    assets:bank:savings    £500.00\n"
            "    income:freelance\n"
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.resolve_default_commodity",
            lambda _file: None,
        )
        app = _SummaryApp(journal)
        async with app.run_test() as pilot:
            await wait_until(
                pilot, lambda: _table_row_count(app, "#summary-income-table") >= 2
            )
            rows = _table_rows(app, "#summary-income-table")
            assert {row[2] for row in rows} == {"\u2014"}
            note = app.query_one("#summary-income-note", Static)
            assert note.display is True
            assert "default_commodity" in str(note.content)


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestSummaryPaneCardTotals:
    """Card totals only cover the converted commodity (issue #218)."""

    async def test_cards_exclude_unconverted_commodities(
        self, tmp_path: Path, monkeypatch
    ):
        """Card totals only cover the default commodity (issue #218)."""
        from hledger_textual.widgets.currency_marquee import CurrencyMarquee

        today = date.today()
        d1 = today.replace(day=1).isoformat()
        journal = tmp_path / "btc_card.journal"
        journal.write_text(
            "commodity €1,000.00\n"
            "commodity 0.00000000 BTC\n"
            "\n"
            f"{d1} * Salary\n"
            "    assets:bank:checking   €1000.00\n"
            "    income:salary\n"
            "\n"
            f"{d1} * Gift\n"
            "    assets:crypto:wallet   0.01000000 BTC\n"
            "    income:gifts\n"
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.summary_pane.resolve_default_commodity",
            lambda _file: "€",
        )
        app = _SummaryApp(journal)
        async with app.run_test() as pilot:
            await wait_until(pilot, lambda: _cards_applied(app))
            assert app.query_one(".income-value", Digits).value == "€1,000.00"
            assert app.query_one(".net-value", Digits).value == "€1,000.00"
            marquee = app.query_one(".income-multicurrency", CurrencyMarquee)
            assert marquee.display is True
            assert "BTC" in marquee._text
