"""Summary pane widget showing financial overview with cards and breakdowns."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from rich.text import Text
from textual.widgets import DataTable, Static

from hledger_textual.cache import HledgerCache
from hledger_textual.config import load_price_tickers
from hledger_textual.formatter import normalize_commodity
from hledger_textual.widgets import distribute_column_widths
from hledger_textual.widgets.formatting import (
    fmt_amount,
)
from hledger_textual.widgets.period_summary_cards import PeriodSummaryCards
from hledger_textual.hledger import (
    HledgerError,
    load_expense_breakdown,
    load_income_breakdown,
    load_investment_cost,
    load_investment_eur_by_account,
    load_investment_positions,
    load_liabilities_breakdown,
    load_period_summary,
)
from hledger_textual.prices import PriceError, get_prices_file, has_pricehist


class _DisplayTable(DataTable):
    """Read-only DataTable that never receives keyboard focus."""

    ALLOW_FOCUS = False
    can_focus = False


def _progress_bar(pct: float, width: int = 8) -> str:
    """Render a text progress bar using block characters.

    Args:
        pct: Percentage value (0–100+).
        width: Number of character cells for the bar.

    Returns:
        A string of filled/empty block characters, e.g. '████░░░░'.
    """
    filled = min(int(round(pct / 100 * width)), width)
    return "█" * filled + "░" * (width - filled)


class SummaryPane(Widget):
    """Widget showing journal statistics and a monthly financial overview.

    The Income / Expenses / Net cards and expense breakdown all show the
    current calendar month.
    """

    BINDINGS = [
        Binding("r", "refresh", "Refresh", show=True, priority=True),
    ]

    def __init__(
        self,
        journal_file: Path,
        cache: HledgerCache | None = None,
        **kwargs,
    ) -> None:
        """Initialize the summary pane.

        Args:
            journal_file: Path to the hledger journal file.
            cache: Optional cache for hledger results.
        """
        super().__init__(**kwargs)
        self.journal_file = journal_file
        self._cache = cache
        self._current_month: date = date.today().replace(day=1)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Create the summary pane layout."""
        yield Static(
            "Overview",
            id="summary-overview-title",
            classes="summary-section-title",
        )
        yield PeriodSummaryCards(id="summary-cards")

        # Liabilities section (total outstanding balance)
        with Vertical(id="summary-liabilities"):
            yield Static(
                "Liabilities",
                id="summary-liabilities-title",
                classes="summary-section-title",
            )
            yield _DisplayTable(id="summary-liabilities-table", show_cursor=False)

        # Investments section
        with Vertical(id="summary-portfolio"):
            yield Static(
                "Investments",
                id="summary-portfolio-title",
                classes="summary-section-title",
            )
            yield _DisplayTable(id="summary-portfolio-table", show_cursor=False)
            yield Static("", id="summary-portfolio-loading", classes="summary-portfolio-loading-line")

        # Income breakdown — current month
        with Vertical(id="summary-income-breakdown"):
            yield Static(
                "Income",
                id="summary-income-title",
                classes="summary-section-title",
            )
            yield DataTable(id="summary-income-table")

        # Expense breakdown — current month only
        with Vertical(id="summary-breakdown"):
            yield Static(
                "Expenses",
                id="summary-breakdown-title",
                classes="summary-section-title",
            )
            yield DataTable(id="summary-breakdown-table")

    # Column index → fixed width for portfolio table (col 0 = flex)
    _PORTFOLIO_FIXED = {1: 12, 2: 18, 3: 18}
    # Column index → fixed width for breakdown table (col 0 = flex)
    _BREAKDOWN_FIXED = {1: 14, 2: 24}

    def on_mount(self) -> None:
        """Set up data tables and start loading data."""
        portfolio_table = self.query_one("#summary-portfolio-table", _DisplayTable)
        portfolio_table.cursor_type = "none"
        portfolio_table.add_column("Asset", width=12)
        portfolio_table.add_column("Quantity", width=self._PORTFOLIO_FIXED[1])
        portfolio_table.add_column("Balance", width=self._PORTFOLIO_FIXED[2])
        portfolio_table.add_column("Market Value", width=self._PORTFOLIO_FIXED[3])

        liabilities_table = self.query_one("#summary-liabilities-table", _DisplayTable)
        liabilities_table.cursor_type = "none"
        liabilities_table.add_column("Account", width=20)
        liabilities_table.add_column("Amount", width=self._BREAKDOWN_FIXED[1])
        liabilities_table.add_column("% of total", width=self._BREAKDOWN_FIXED[2])

        income_table = self.query_one("#summary-income-table", DataTable)
        income_table.cursor_type = "none"
        income_table.show_cursor = False
        income_table.add_column("Account", width=20)
        income_table.add_column("Amount", width=self._BREAKDOWN_FIXED[1])
        income_table.add_column("% of total", width=self._BREAKDOWN_FIXED[2])

        breakdown_table = self.query_one("#summary-breakdown-table", DataTable)
        breakdown_table.cursor_type = "none"
        breakdown_table.show_cursor = False
        breakdown_table.add_column("Account", width=20)
        breakdown_table.add_column("Amount", width=self._BREAKDOWN_FIXED[1])
        breakdown_table.add_column("% of total", width=self._BREAKDOWN_FIXED[2])

        self._load_static_data()
        self._load_breakdown_data()

    def on_resize(self) -> None:
        """Recalculate flex column widths for all tables."""
        ptable = self.query_one("#summary-portfolio-table", _DisplayTable)
        distribute_column_widths(ptable, self._PORTFOLIO_FIXED)
        ltable = self.query_one("#summary-liabilities-table", _DisplayTable)
        distribute_column_widths(ltable, self._BREAKDOWN_FIXED)
        itable = self.query_one("#summary-income-table", DataTable)
        distribute_column_widths(itable, self._BREAKDOWN_FIXED)
        btable = self.query_one("#summary-breakdown-table", DataTable)
        distribute_column_widths(btable, self._BREAKDOWN_FIXED)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _period_str(self) -> str:
        """Return the hledger period query string for the current month."""
        return self._current_month.strftime("%Y-%m")

    def _group_positions_by_commodity(
        self, positions: list[tuple[str, Decimal, str]]
    ) -> dict[str, list[tuple[str, Decimal]]]:
        """Group investment positions by commodity name.

        Args:
            positions: List of (account, qty, commodity) tuples.

        Returns:
            Dict mapping commodity → list of (account, qty) pairs.
        """
        result: dict[str, list[tuple[str, Decimal]]] = {}
        for acc, qty, com in positions:
            result.setdefault(com, []).append((acc, qty))
        return result

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        """Reload all summary data."""
        self._load_static_data()
        self._load_breakdown_data()

    # ------------------------------------------------------------------
    # Background workers
    # ------------------------------------------------------------------

    @work(thread=True, exclusive=True, group="summary-static")
    def _load_static_data(self) -> None:
        """Load current-month cards and portfolio data.

        The cards (Income / Expenses / Net) always show the current calendar
        month and are not affected by the breakdown period navigation.
        """
        # --- All-time period summary for cards ---
        try:
            summary = load_period_summary(self.journal_file, cache=self._cache)
        except HledgerError:
            summary = None

        # --- Liabilities: total outstanding balance ---
        try:
            liabilities = load_liabilities_breakdown(self.journal_file)
        except HledgerError:
            liabilities = []

        # --- Investments: positions + cost (fast hledger) ---
        try:
            positions = load_investment_positions(self.journal_file)
        except HledgerError:
            positions = []

        try:
            cost_by_account = load_investment_cost(self.journal_file)
        except HledgerError:
            cost_by_account = {}

        tickers = load_price_tickers()
        pricehist_ok = has_pricehist()
        will_fetch = bool(tickers) and pricehist_ok

        # Determine which commodities lack ticker mappings
        by_commodity = self._group_positions_by_commodity(positions)
        unconfigured = sorted(set(by_commodity.keys()) - set(tickers.keys()))

        # Determine loading indicator message for the first UI update
        if will_fetch:
            loading_msg = "[dim]\u23f3 Fetching market prices\u2026[/dim]"
        elif pricehist_ok and unconfigured:
            missing = ", ".join(unconfigured)
            loading_msg = (
                f"[yellow]\u26a0 No ticker configured for: {missing}. "
                "Add entries to \\[prices] in config.toml to see market values.[/yellow]"
            )
        else:
            loading_msg = ""

        # First UI update: cards + basic investments + liabilities
        self.app.call_from_thread(
            self._apply_static_data,
            summary,
            positions, cost_by_account,
            tickers, loading_msg,
            liabilities,
        )

        if not will_fetch:
            return

        # --- Investments: EUR market values via pricehist (slow: network I/O) ---
        eur_by_account: dict[str, tuple[Decimal, str]] = {}
        try:
            prices_file = get_prices_file(tickers)
            if prices_file is not None:
                eur_by_account = load_investment_eur_by_account(
                    self.journal_file, prices_file
                )
        except (HledgerError, PriceError):
            pass

        # Build post-fetch warning for unconfigured commodities
        if unconfigured and pricehist_ok:
            missing = ", ".join(unconfigured)
            post_msg = (
                f"[yellow]\u26a0 No ticker configured for: {missing}. "
                "Add entries to \\[prices] in config.toml to see market values.[/yellow]"
            )
        else:
            post_msg = ""

        # Second UI update: rebuild investments table with Value (€) column
        self.app.call_from_thread(
            self._apply_portfolio_eur,
            positions, cost_by_account,
            tickers, eur_by_account,
            post_msg,
        )

    def _apply_static_data(
        self,
        summary,
        positions: list[tuple[str, Decimal, str]],
        cost_by_account: dict[str, tuple[Decimal, str]],
        tickers: dict[str, str],
        loading_msg: str,
        liabilities: list[tuple[str, Decimal, str]] | None = None,
    ) -> None:
        """Apply card values, basic investments, and liabilities."""
        if not self.is_attached:
            return
        # Guard against the widget being unmounted between the is_attached check
        # and the DOM query (can happen when a background worker completes after
        # the app has started tearing down during tests).
        try:
            self.query_one("#summary-overview-title", Static).update("Overview")
        except NoMatches:
            return

        # Income / Expenses / Net cards — delegated to PeriodSummaryCards
        self.query_one(PeriodSummaryCards).update_summary(summary)

        # Investments table — columns are fixed; clear rows only
        ptable = self.query_one("#summary-portfolio-table", _DisplayTable)
        ptable.clear()

        by_commodity = self._group_positions_by_commodity(positions)
        portfolio_section = self.query_one("#summary-portfolio")

        if not by_commodity:
            portfolio_section.display = False
        else:
            portfolio_section.display = True
            self._fill_portfolio_rows(ptable, by_commodity, cost_by_account, tickers)
            self.call_after_refresh(
                distribute_column_widths, ptable, self._PORTFOLIO_FIXED
            )

        # Loading / hint message
        self.query_one("#summary-portfolio-loading", Static).update(loading_msg)

        # Liabilities table
        if liabilities is not None:
            ltable = self.query_one("#summary-liabilities-table", _DisplayTable)
            ltable.clear()
            liabilities_section = self.query_one("#summary-liabilities")

            if not liabilities:
                liabilities_section.display = False
            else:
                liabilities_section.display = True
                total_liab = sum(qty for _, qty, _ in liabilities)
                for account, qty, commodity in liabilities:
                    pct = float(qty / total_liab * 100) if total_liab else 0.0
                    bar = _progress_bar(pct, width=12)
                    ltable.add_row(
                        Text(account),
                        fmt_amount(qty, commodity),
                        f"{bar} {pct:.0f}%",
                    )
                self.call_after_refresh(
                    distribute_column_widths, ltable, self._BREAKDOWN_FIXED
                )

    def _apply_portfolio_eur(
        self,
        positions: list[tuple[str, Decimal, str]],
        cost_by_account: dict[str, tuple[Decimal, str]],
        tickers: dict[str, str],
        eur_by_account: dict[str, tuple[Decimal, str]],
        post_msg: str,
    ) -> None:
        """Rebuild the investments table with actual Value (€) data from pricehist."""
        if not self.is_attached:
            return
        ptable = self.query_one("#summary-portfolio-table", _DisplayTable)
        ptable.clear()

        by_commodity = self._group_positions_by_commodity(positions)
        self._fill_portfolio_rows(
            ptable, by_commodity, cost_by_account, tickers, eur_by_account
        )
        self.call_after_refresh(
            distribute_column_widths, ptable, self._PORTFOLIO_FIXED
        )

        # Show warning for unconfigured commodities, or clear loading indicator
        self.query_one("#summary-portfolio-loading", Static).update(post_msg)

    def _fill_portfolio_rows(
        self,
        ptable: DataTable,
        by_commodity: dict[str, list[tuple[str, Decimal]]],
        cost_by_account: dict[str, tuple[Decimal, str]],
        tickers: dict[str, str],
        eur_by_account: dict[str, tuple[Decimal, str]] | None = None,
    ) -> None:
        """Fill investments DataTable rows.

        Always emits 4 columns (Asset, Qty, Balance, Market Value).
        The Market Value column shows '—' when:
        - eur_by_account is None (prices not fetched yet)
        - the commodity has no ticker configured
        - hledger couldn't convert to EUR (returned the original commodity)

        Args:
            ptable: The DataTable to populate.
            by_commodity: Investment positions grouped by commodity name.
            cost_by_account: Book value per account (from load_investment_cost).
            tickers: Commodity-to-ticker mappings from config.
            eur_by_account: EUR market value per account, or None if loading/unavailable.
        """
        # Investment rows (one per commodity, sorted alphabetically)
        for com in sorted(by_commodity.keys()):
            accs = by_commodity[com]
            total_qty = sum(q for _, q in accs)

            # Book value: sum purchase cost across all accounts for this commodity
            book_total = sum(
                cost_by_account.get(acc, (Decimal("0"), ""))[0] for acc, _ in accs
            )
            book_com = next(
                (cost_by_account[acc][1] for acc, _ in accs if acc in cost_by_account),
                "",
            )
            book_str = fmt_amount(book_total, book_com) if book_com else fmt_amount(book_total, "")

            if eur_by_account is not None and com in tickers:
                # EUR market value: sum across all accounts for this commodity
                eur_total = sum(
                    eur_by_account.get(acc, (Decimal("0"), ""))[0] for acc, _ in accs
                )
                eur_com = next(
                    (eur_by_account[acc][1] for acc, _ in accs if acc in eur_by_account),
                    "",
                )
                eur_com = normalize_commodity(eur_com)
                # If hledger couldn't convert (returned original commodity), show —
                if eur_com == com:
                    ptable.add_row(com, f"{total_qty:g}", book_str, "\u2014")
                    continue
                eur_str = fmt_amount(eur_total, eur_com) if eur_com else fmt_amount(eur_total, "")
                # Color: green if market value exceeds book value (gain), red if loss
                if book_com and eur_total > book_total:
                    eur_str = f"[green]{eur_str}[/green]"
                elif book_com and eur_total < book_total:
                    eur_str = f"[red]{eur_str}[/red]"
                ptable.add_row(com, f"{total_qty:g}", book_str, eur_str)
            else:
                ptable.add_row(com, f"{total_qty:g}", book_str, "\u2014")

    @work(thread=True, exclusive=True, group="summary-breakdown")
    def _load_breakdown_data(self) -> None:
        """Load income and expense breakdowns for the selected month."""
        period = self._period_str()

        try:
            income_breakdown = load_income_breakdown(self.journal_file, period)
        except HledgerError:
            income_breakdown = []

        try:
            breakdown = load_expense_breakdown(self.journal_file, period)
        except HledgerError:
            breakdown = []

        self.app.call_from_thread(
            self._apply_breakdown_data, income_breakdown, breakdown
        )

    def _apply_breakdown_data(
        self, income_breakdown: list, breakdown: list
    ) -> None:
        """Apply loaded income and expense breakdowns to their tables."""
        if not self.is_attached:
            return

        month_name = self._current_month.strftime("%B %Y")

        # --- Income breakdown ---
        self.query_one("#summary-income-title", Static).update(
            f"{month_name} Income"
        )

        itable = self.query_one("#summary-income-table", DataTable)
        itable.clear()

        if not income_breakdown:
            itable.add_row("[dim]No income recorded this month[/dim]", "", "")
        else:
            total_inc = sum(qty for _, qty, _ in income_breakdown)
            for account, qty, commodity in income_breakdown:
                pct = float(qty / total_inc * 100) if total_inc else 0.0
                bar = _progress_bar(pct, width=12)
                itable.add_row(
                    Text(account),
                    fmt_amount(qty, commodity),
                    f"{bar} {pct:.0f}%",
                )
            self.call_after_refresh(
                distribute_column_widths, itable, self._BREAKDOWN_FIXED
            )

        # --- Expense breakdown ---
        self.query_one("#summary-breakdown-title", Static).update(
            f"{month_name} Expenses"
        )

        table = self.query_one("#summary-breakdown-table", DataTable)
        table.clear()

        if not breakdown:
            table.add_row("[dim]No expenses recorded this month[/dim]", "", "")
            return

        total_exp = sum(qty for _, qty, _ in breakdown)
        for account, qty, commodity in breakdown:
            pct = float(qty / total_exp * 100) if total_exp else 0.0
            bar = _progress_bar(pct, width=12)
            table.add_row(
                Text(account),
                fmt_amount(qty, commodity),
                f"{bar} {pct:.0f}%",
            )

        self.call_after_refresh(
            distribute_column_widths, table, self._BREAKDOWN_FIXED
        )
