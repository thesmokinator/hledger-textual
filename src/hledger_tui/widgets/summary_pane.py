"""Summary pane widget showing financial overview with cards and breakdowns."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import DataTable, Digits, Static

from hledger_tui.config import load_price_tickers
from hledger_tui.formatter import normalize_commodity
from hledger_tui.widgets import distribute_column_widths
from hledger_tui.hledger import (
    HledgerError,
    load_expense_breakdown,
    load_investment_cost,
    load_investment_eur_by_account,
    load_investment_positions,
    load_period_summary,
)
from hledger_tui.prices import PriceError, get_prices_file, has_pricehist


class _DisplayTable(DataTable):
    """Read-only DataTable that never receives keyboard focus."""

    ALLOW_FOCUS = False
    can_focus = False


def _fmt_amount(qty: Decimal, commodity: str) -> str:
    """Format a decimal amount with its commodity symbol.

    Args:
        qty: The numeric quantity.
        commodity: The commodity symbol (e.g. '€', 'EUR').

    Returns:
        A formatted string like '€1,234.56' or '0.00' if no commodity.
    """
    if not commodity:
        return f"{qty:,.2f}"
    # Left-side single-char commodities (symbols like €, $, £)
    if len(commodity) == 1:
        return f"{commodity}{qty:,.2f}"
    return f"{qty:,.2f} {commodity}"


def _fmt_digits(qty: Decimal, commodity: str) -> str:
    """Format a decimal amount for the Digits widget.

    Like _fmt_amount but uses spaces as thousands separator instead of commas,
    since the Digits widget does not support comma characters.

    Args:
        qty: The numeric quantity.
        commodity: The commodity symbol (e.g. '€', 'EUR').

    Returns:
        A formatted string like '€1 234.56' or '0.00' if no commodity.
    """
    return _fmt_amount(qty, commodity).replace(",", "")


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

    def __init__(self, journal_file: Path, **kwargs) -> None:
        """Initialize the summary pane.

        Args:
            journal_file: Path to the hledger journal file.
        """
        super().__init__(**kwargs)
        self.journal_file = journal_file
        self._current_month: date = date.today().replace(day=1)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Create the summary pane layout."""
        with Horizontal(id="summary-cards"):
            with Vertical(classes="summary-card", id="card-income"):
                yield Static("Income", classes="summary-card-title")
                yield Digits("--", id="card-income-value", classes="summary-card-value")
            with Vertical(classes="summary-card", id="card-expenses"):
                yield Static("Expenses", classes="summary-card-title")
                yield Digits("--", id="card-expenses-value", classes="summary-card-value")
            with Vertical(classes="summary-card", id="card-net"):
                yield Static("Net", classes="summary-card-title")
                yield Digits("--", id="card-net-value", classes="summary-card-value")
                yield Static("", id="card-net-note")

        # Investments section
        with Vertical(id="summary-portfolio"):
            yield Static(
                "Investments",
                id="summary-portfolio-title",
                classes="summary-section-title",
            )
            yield _DisplayTable(id="summary-portfolio-table", show_cursor=False)
            yield Static("", id="summary-portfolio-loading", classes="summary-portfolio-loading-line")

        # Expense breakdown — current month only
        with Vertical(id="summary-breakdown"):
            yield Static(
                "This Month's Expenses",
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
        # --- Current-month period summary for cards ---
        thismonth = date.today().strftime("%Y-%m")
        try:
            summary = load_period_summary(self.journal_file, thismonth)
        except HledgerError:
            summary = None

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

        # First UI update: cards + basic investments
        self.app.call_from_thread(
            self._apply_static_data,
            summary,
            positions, cost_by_account,
            tickers, loading_msg,
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
    ) -> None:
        """Apply card values and basic investments (no EUR market prices)."""
        # Income / Expenses / Net cards
        if summary is not None:
            com = summary.commodity
            income_text = _fmt_digits(summary.income, com)
            expense_text = _fmt_digits(summary.expenses, com)
            net = summary.net
            net_text = _fmt_digits(abs(net), com)

            self.query_one("#card-income-value", Digits).update(income_text)
            self.query_one("#card-expenses-value", Digits).update(expense_text)

            net_widget = self.query_one("#card-net-value", Digits)
            if net >= 0:
                net_widget.update(net_text)
                net_widget.remove_class("net-negative")
                net_widget.add_class("net-positive")
            else:
                net_widget.update(f"-{net_text}")
                net_widget.remove_class("net-positive")
                net_widget.add_class("net-negative")

            note = self.query_one("#card-net-note", Static)
            if summary.investments > 0:
                inv_text = _fmt_amount(summary.investments, com)
                note.update(f"incl. {inv_text} invested")
            else:
                note.update("")
        else:
            for widget_id in (
                "#card-income-value",
                "#card-expenses-value",
                "#card-net-value",
            ):
                self.query_one(widget_id, Digits).update("--")
            self.query_one("#card-net-note", Static).update("")

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

    def _apply_portfolio_eur(
        self,
        positions: list[tuple[str, Decimal, str]],
        cost_by_account: dict[str, tuple[Decimal, str]],
        tickers: dict[str, str],
        eur_by_account: dict[str, tuple[Decimal, str]],
        post_msg: str,
    ) -> None:
        """Rebuild the investments table with actual Value (€) data from pricehist."""
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
            book_str = _fmt_amount(book_total, book_com) if book_com else f"{book_total:,.2f}"

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
                eur_str = _fmt_amount(eur_total, eur_com) if eur_com else f"{eur_total:,.2f}"
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
        """Load expense breakdown for the selected month in a background thread."""
        period = self._period_str()

        try:
            breakdown = load_expense_breakdown(self.journal_file, period)
        except HledgerError:
            breakdown = []

        self.app.call_from_thread(self._apply_breakdown_data, breakdown)

    def _apply_breakdown_data(self, breakdown: list) -> None:
        """Apply loaded expense breakdown to the table."""
        table = self.query_one("#summary-breakdown-table", DataTable)
        table.clear()

        if not breakdown:
            return

        total_exp = sum(qty for _, qty, _ in breakdown)
        for account, qty, commodity in breakdown:
            pct = float(qty / total_exp * 100) if total_exp else 0.0
            bar = _progress_bar(pct, width=12)
            table.add_row(
                account,
                _fmt_amount(qty, commodity),
                f"{bar} {pct:.0f}%",
            )

        self.call_after_refresh(
            distribute_column_widths, table, self._BREAKDOWN_FIXED
        )
