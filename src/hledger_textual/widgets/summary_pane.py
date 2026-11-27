"""Summary pane widget showing financial overview with cards and breakdowns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.widget import Widget
from rich.text import Text
from textual.widgets import DataTable, Static

from hledger_textual.cache import HledgerCache
from hledger_textual.config import load_price_tickers, resolve_default_commodity
from hledger_textual.formatter import normalize_commodity
from hledger_textual.widgets import distribute_column_widths
from hledger_textual.widgets.click_select_datatable import ClickSelectDataTable
from hledger_textual.widgets.empty_state import EmptyState
from hledger_textual.widgets.formatting import (
    fmt_amount,
)
from hledger_textual.widgets.loading import hide_loading_overlay, show_loading_overlay
from hledger_textual.widgets.pane_mixin import DataTablePaneMixin, get_global_query, get_period, set_period
from hledger_textual.widgets.period_summary_cards import PeriodSummaryCards
from hledger_textual.hledger import (
    HledgerError,
    load_expense_breakdown,
    load_income_breakdown,
    load_investment_eur_by_account,
    load_investment_portfolio,
    load_journal_stats,
    load_liabilities_breakdown,
    load_period_expenses_by_commodity,
    load_period_income_by_commodity,
    load_period_net_by_commodity,
    load_period_summary,
)
from hledger_textual.parallel import gather_loads
from hledger_textual.period import current_month_selection, month_selection, shift_months
from hledger_textual.prices import PriceError, get_prices_file, has_pricehist
from hledger_textual.models import JournalStats


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


def _totals_by_commodity(
    rows: list[tuple[str, Decimal, str]],
) -> dict[str, Decimal]:
    """Sum breakdown amounts per commodity.

    Args:
        rows: ``(account, amount, commodity)`` breakdown rows.

    Returns:
        A dict mapping commodity to the sum of its row amounts.
    """
    totals: dict[str, Decimal] = {}
    for _, amount, com in rows:
        totals[com] = totals.get(com, Decimal("0")) + amount
    return totals


def _share_pct(
    amount: Decimal,
    commodity: str,
    totals: dict[str, Decimal],
    target: str | None,
) -> float | None:
    """Return a row's percentage share of the comparable report total.

    Amounts in different commodities are not comparable, so a share is only
    computed when there is a common denominator:

    - with a resolved default commodity, only rows already in it are counted
      (hledger leaves commodities without a price unconverted);
    - without one, the journal must be single-currency.

    Args:
        amount: The row amount.
        commodity: The row commodity.
        totals: Per-commodity totals for the whole report.
        target: The resolved default commodity, or None.

    Returns:
        The percentage share, or None when the share is not comparable.
    """
    if target is None:
        if len(totals) != 1:
            return None
        total = next(iter(totals.values()))
    elif commodity == target:
        total = totals.get(target, Decimal("0"))
    else:
        return None
    if not total:
        return None
    return float(amount / total * 100)


def _share_cell(pct: float | None, width: int = 12) -> str:
    """Render a percentage cell as a progress bar, or an em dash if unknown."""
    if pct is None:
        return "\u2014"
    return f"{_progress_bar(pct, width=width)} {pct:.0f}%"


def _load_result(value, default):
    """Return *value* unless the concurrent load raised, then *default*."""
    return default if isinstance(value, Exception) else value


@dataclass
class PortfolioRow:
    """Per-commodity portfolio figures for one table row.

    ``market_total`` is ``None`` when no market price is available;
    ``avg_cost``, ``unrealised_pl`` and ``portfolio_pct`` are ``None`` when
    their inputs are missing or not comparable.
    """

    commodity: str
    quantity: Decimal
    book_total: Decimal
    book_commodity: str
    market_total: Decimal | None
    market_commodity: str
    avg_cost: Decimal | None
    unrealised_pl: Decimal | None
    portfolio_pct: float | None


def _portfolio_rows(
    by_commodity: dict[str, list[tuple[str, Decimal]]],
    cost_by_account: dict[str, tuple[Decimal, str]],
    tickers: dict[str, str],
    eur_by_account: dict[str, tuple[Decimal, str]] | None = None,
) -> list[PortfolioRow]:
    """Compute per-commodity portfolio figures from raw loader output.

    Args:
        by_commodity: Commodity → list of ``(account, quantity)`` pairs.
        cost_by_account: Book value per account from ``load_investment_cost``.
        tickers: Commodity-to-ticker mappings from config.
        eur_by_account: Market value per account, or None when prices are
            unavailable.

    Returns:
        One :class:`PortfolioRow` per commodity, sorted alphabetically.
    """
    rows: list[PortfolioRow] = []
    market_totals: dict[str, Decimal] = {}
    for com in sorted(by_commodity.keys()):
        accs = by_commodity[com]
        total_qty = sum(q for _, q in accs)
        book_total = sum(
            cost_by_account.get(acc, (Decimal("0"), ""))[0] for acc, _ in accs
        )
        book_com = next(
            (cost_by_account[acc][1] for acc, _ in accs if acc in cost_by_account),
            "",
        )
        market_total: Decimal | None = None
        market_com = ""
        if eur_by_account is not None and com in tickers:
            market_total = sum(
                eur_by_account.get(acc, (Decimal("0"), ""))[0] for acc, _ in accs
            )
            market_com = next(
                (eur_by_account[acc][1] for acc, _ in accs if acc in eur_by_account),
                "",
            )
            market_com = normalize_commodity(market_com)
            # hledger returns the original commodity when it cannot convert.
            if market_com == com:
                market_total = None
                market_com = ""
        if market_total is not None:
            market_totals[com] = market_total
        avg_cost = book_total / total_qty if book_com and total_qty else None
        unrealised_pl = None
        if (
            market_total is not None
            and book_com
            and normalize_commodity(book_com) == normalize_commodity(market_com)
        ):
            unrealised_pl = market_total - book_total
        rows.append(
            PortfolioRow(
                commodity=com,
                quantity=total_qty,
                book_total=book_total,
                book_commodity=book_com,
                market_total=market_total,
                market_commodity=market_com,
                avg_cost=avg_cost,
                unrealised_pl=unrealised_pl,
                portfolio_pct=None,
            )
        )
    grand_total = sum(market_totals.values(), Decimal("0"))
    if grand_total:
        for row in rows:
            if row.market_total is not None:
                row.portfolio_pct = float(row.market_total / grand_total * 100)
    return rows


def _conversion_note(totals: dict[str, Decimal], target: str | None) -> str:
    """Explain why some percentages are hidden, or return an empty string."""
    if target is None:
        if len(totals) > 1:
            return (
                "[yellow]\u26a0 Multiple currencies: set default_commodity "
                "in config.toml to compare amounts.[/yellow]"
            )
        return ""
    missing = sorted(com for com in totals if com and com != target and totals[com])
    if not missing:
        return ""
    return (
        f"[yellow]\u26a0 No price for {', '.join(missing)}: "
        "excluded from percentages.[/yellow]"
    )


class SummaryPane(DataTablePaneMixin, Widget):
    """Widget showing journal statistics and a monthly financial overview.

    The Income / Expenses / Net cards and expense breakdown all show the
    current calendar month.
    """

    class Loaded(Message):
        """Posted once the Summary's static and breakdown sections have loaded."""

    class StatsLoaded(Message):
        """Posted when journal statistics (including the date span) are available."""

        def __init__(self, stats: JournalStats) -> None:
            """Initialise the message.

            Args:
                stats: The loaded journal statistics.
            """
            super().__init__()
            self.stats = stats

    BINDINGS = [
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("x", "export", "Export", show=False, priority=True),
        Binding("i", "toggle_investments", "Fold investments", show=True, priority=True),
        Binding("l", "toggle_liabilities", "Fold liabilities", show=True, priority=True),
        # Period navigation (issue #265): arrows move the shared anchor;
        # l keeps its fold-liabilities meaning.
        Binding("left", "prev_month", "Prev month", show=False, priority=True),
        Binding("right", "next_month", "Next month", show=False, priority=True),
        Binding("shift+left", "prev_year", "Prev year", show=False, priority=True),
        Binding("shift+right", "next_year", "Next year", show=False, priority=True),
        Binding("t", "today_month", "Today", show=False, priority=True),
        Binding("J", "jump_to_latest", "Jump to latest activity", show=False, priority=True),
        Binding("g", "go_to_period", "Go to period", show=True, priority=True),
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
        self._static_loaded = False
        self._breakdown_loaded = False
        self._investments_loaded = False
        self._has_static_sections = False
        self._has_breakdown_sections = False
        self._summary_export_rows: list[list[str]] = []
        self._collapsed_sections: set[str] = set()
        self._loaded_posted = False
        #: Journal statistics loaded with the static data (issue #267).
        self.journal_stats: JournalStats | None = None

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Create the summary pane layout."""
        yield EmptyState(
            "No data yet",
            "Add transactions to see your summary.",
            icon="📭",
            id="summary-empty-state",
        )
        with Vertical(id="summary-content"):
            yield Static(
                "Overview",
                id="summary-overview-title",
                classes="summary-section-title",
            )
            yield PeriodSummaryCards(id="summary-cards")
            yield Static("", id="summary-month-hint", classes="summary-note")

            # Liabilities section (total outstanding balance)
            with Vertical(id="summary-liabilities"):
                yield Static(
                    "Liabilities",
                    id="summary-liabilities-title",
                    classes="summary-section-title",
                )
                yield _DisplayTable(id="summary-liabilities-table", show_cursor=False)
                yield Static("", id="summary-liabilities-note", classes="summary-note")

            # Investments section
            with Vertical(id="summary-portfolio"):
                yield Static(
                    "Investments",
                    id="summary-portfolio-title",
                    classes="summary-section-title",
                )
                yield ClickSelectDataTable(
                    id="summary-portfolio-table",
                    cursor_type="row",
                )
                yield Static("", id="summary-portfolio-loading", classes="summary-portfolio-loading-line")

            # Income breakdown — current month
            with Vertical(id="summary-income-breakdown"):
                yield Static(
                    "Income",
                    id="summary-income-title",
                    classes="summary-section-title",
                )
                yield DataTable(id="summary-income-table")
                yield Static("", id="summary-income-note", classes="summary-note")

            # Expense breakdown — selected month only
            with Vertical(id="summary-breakdown"):
                yield Static(
                    "Expenses",
                    id="summary-breakdown-title",
                    classes="summary-section-title",
                )
                yield DataTable(id="summary-breakdown-table")
                yield Static("", id="summary-breakdown-note", classes="summary-note")

    # Column index → fixed width for portfolio table (col 0 = flex)
    _PORTFOLIO_FIXED = {1: 12, 2: 14, 3: 16, 4: 16, 5: 14}
    # Column index → fixed width for breakdown table (col 0 = flex)
    _BREAKDOWN_FIXED = {1: 14, 2: 24}

    # DataTablePaneMixin configuration: the income table is primary, the
    # other tables only get resize handling (all summary tables are
    # read-only, so the pane must not steal focus on show).
    _main_table_id = "summary-income-table"
    _fixed_column_widths = _BREAKDOWN_FIXED
    _additional_tables = {
        "summary-portfolio-table": _PORTFOLIO_FIXED,
        "summary-liabilities-table": _BREAKDOWN_FIXED,
        "summary-breakdown-table": _BREAKDOWN_FIXED,
    }
    _focus_on_show = False
    # The pane itself can hold focus when its tables hide (empty month),
    # so period-navigation bindings keep working (issue #265).
    can_focus = True

    def on_mount(self) -> None:
        """Set up data tables and start loading data."""
        portfolio_table = self.query_one("#summary-portfolio-table", DataTable)
        portfolio_table.cursor_type = "row"
        portfolio_table.add_column("Symbol", width=12)
        portfolio_table.add_column("Quantity", width=self._PORTFOLIO_FIXED[1])
        portfolio_table.add_column("Avg Cost", width=self._PORTFOLIO_FIXED[2])
        portfolio_table.add_column("Market Value", width=self._PORTFOLIO_FIXED[3])
        portfolio_table.add_column("Unrealised P/L", width=self._PORTFOLIO_FIXED[4])
        portfolio_table.add_column("% of Portfolio", width=self._PORTFOLIO_FIXED[5])

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

        # Conversion notes stay hidden until a breakdown reports mixed
        # currencies or commodities without a price.
        for selector in (
            "#summary-liabilities-note",
            "#summary-income-note",
            "#summary-breakdown-note",
        ):
            self._set_note(selector, "")

        self._set_empty_state_visible(False)
        self._load_static_data()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _period_str(self) -> str:
        """Return the hledger period expression for the shared selection.

        For a month selection this is ``YYYY-MM``; ranges and years use
        their compact hledger form (``2024-01..2024-06``, ``2024``); the
        ``all`` selection returns ``""`` (all time).
        """
        return get_period(self).period_expr

    @property
    def _current_month(self) -> date:
        """Return the first day of the anchor month of the shared period."""
        period = get_period(self)
        if period.begin is not None:
            return period.begin.replace(day=1)
        return date.today().replace(day=1)

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

    def action_toggle_investments(self) -> None:
        """Collapse or expand the Investments section."""
        self._toggle_section("portfolio")

    def action_toggle_liabilities(self) -> None:
        """Collapse or expand the Liabilities section."""
        self._toggle_section("liabilities")

    _COLLAPSE_TABLES = {
        "portfolio": "#summary-portfolio-table",
        "liabilities": "#summary-liabilities-table",
    }

    def _toggle_section(self, section: str) -> None:
        """Flip the collapsed state of a section and redraw it.

        Args:
            section: ``"portfolio"`` or ``"liabilities"``.
        """
        if section in self._collapsed_sections:
            self._collapsed_sections.discard(section)
        else:
            self._collapsed_sections.add(section)
            # Hiding the focused table would strand focus outside the pane
            # (and its bindings), so park it on the income table first.
            try:
                table = self.query_one(
                    self._COLLAPSE_TABLES[section], DataTable
                )
                if table.has_focus:
                    self.query_one("#summary-income-table", DataTable).focus()
            except Exception:
                pass
        self._apply_collapsed()

    def _apply_collapsed(self) -> None:
        """Hide collapsed section bodies and mark their titles.

        Only the table (and note/loading line) is hidden so the title
        stays visible as the expand affordance; the section container
        itself is left alone so empty sections stay hidden.
        """
        configs = (
            (
                "portfolio",
                "Investments",
                "#summary-portfolio-table",
                ("#summary-portfolio-loading",),
                "#summary-portfolio-title",
            ),
            (
                "liabilities",
                "Liabilities",
                "#summary-liabilities-table",
                ("#summary-liabilities-note",),
                "#summary-liabilities-title",
            ),
        )
        for section, title, table_id, extra_ids, title_id in configs:
            collapsed = section in self._collapsed_sections
            try:
                self.query_one(table_id, DataTable).display = not collapsed
                for extra_id in extra_ids:
                    self.query_one(extra_id, Static).display = not collapsed
                # Expanded sections keep their plain title; collapsed ones
                # get an expand marker so the title stays an affordance.
                label = f"▸ {title}" if collapsed else title
                self.query_one(title_id, Static).update(label)
            except Exception:
                continue

    @on(DataTable.RowSelected, "#summary-portfolio-table")
    def _on_portfolio_row_selected(self, event: DataTable.RowSelected) -> None:
        """Drill down to every transaction touching the selected commodity.

        Args:
            event: The row selection event carrying the commodity row key.
        """
        commodity = str(event.row_key.value or "")
        if not commodity:
            return
        from hledger_textual.screens.account_transactions import (
            AccountTransactionsScreen,
        )

        self.app.push_screen(
            AccountTransactionsScreen(
                "", journal_file=self.journal_file, commodity=commodity
            )
        )

    # ------------------------------------------------------------------
    # Background workers
    # ------------------------------------------------------------------

    @work(thread=True, exclusive=True, group="summary-static")
    def _load_static_data(self) -> None:
        """Load the selected month's cards and the all-time liabilities.

        The cards (Income / Expenses / Net) follow the shared period anchor
        (issue #265).  The investment portfolio loads in its own worker so the
        first figures do not wait for its two extra queries.
        """
        self.app.call_from_thread(show_loading_overlay, self, "Loading summary…")
        # The cards, marquee values and liabilities are independent: run them
        # concurrently and keep the per-loader fallbacks so one failing query
        # never blanks the whole pane.
        commodity = resolve_default_commodity(self.journal_file)
        period = self._period_str()

        (
            summary_result,
            net_result,
            liabilities_result,
            stats_result,
        ) = gather_loads(
            [
                lambda: load_period_summary(
                    self.journal_file, period, cache=self._cache, commodity=commodity,
                    query=get_global_query(self),
                ),
                lambda: load_period_net_by_commodity(
                    self.journal_file, period, cache=self._cache,
                    query=get_global_query(self),
                ),
                lambda: load_liabilities_breakdown(
                    self.journal_file, commodity=commodity, cache=self._cache,
                    query=get_global_query(self),
                ),
                # Stats also carry the transaction date span used for the
                # startup landing heuristic (issue #267); loaded once here so
                # period navigation never pays for it again.
                lambda: load_journal_stats(self.journal_file),
            ]
        )

        summary = _load_result(summary_result, None)
        # Per-currency values for the marquee lines under each card.  These are
        # passed alongside the summary rather than attached to it: the summary
        # comes from a cache and must not be mutated.
        net_by_commodity = _load_result(net_result, [])
        liabilities = _load_result(liabilities_result, [])
        stats = _load_result(stats_result, None)

        # The per-side views reuse the raw R/X queries cached by the net
        # loader, so these calls normally do not start a subprocess.
        try:
            income_by_commodity = load_period_income_by_commodity(
                self.journal_file, period, cache=self._cache,
                query=get_global_query(self),
            )
        except HledgerError:
            income_by_commodity = []
        try:
            expenses_by_commodity = load_period_expenses_by_commodity(
                self.journal_file, period, cache=self._cache,
                query=get_global_query(self),
            )
        except HledgerError:
            expenses_by_commodity = []

        self.app.call_from_thread(
            self._apply_static_data,
            summary,
            liabilities,
            income_by_commodity,
            expenses_by_commodity,
            net_by_commodity,
            commodity,
            stats,
        )

    @work(thread=True, exclusive=True, group="summary-investments")
    def _load_investment_data(self) -> None:
        """Load investment positions and their book value in the background."""
        self.app.call_from_thread(self._set_portfolio_loading)
        try:
            positions, cost_by_account = load_investment_portfolio(
                self.journal_file, cache=self._cache
            )
        except HledgerError:
            positions, cost_by_account = [], {}

        tickers = load_price_tickers()
        pricehist_ok = has_pricehist()
        will_fetch = bool(tickers) and pricehist_ok

        # Determine which commodities lack ticker mappings
        by_commodity = self._group_positions_by_commodity(positions)
        unconfigured = sorted(set(by_commodity.keys()) - set(tickers.keys()))

        # Determine loading indicator message for the first portfolio update
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

        self.app.call_from_thread(
            self._apply_investment_data,
            positions,
            cost_by_account,
            tickers,
            loading_msg,
        )

        if not will_fetch:
            return

        # --- Investments: EUR market values via pricehist (slow: network I/O) ---
        eur_by_account: dict[str, tuple[Decimal, str]] = {}
        try:
            prices_file = get_prices_file(tickers)
            if prices_file is not None:
                eur_by_account = load_investment_eur_by_account(
                    self.journal_file, prices_file, cache=self._cache
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
        liabilities: list[tuple[str, Decimal, str]] | None = None,
        income_by_commodity: list[tuple[str, Decimal]] | None = None,
        expenses_by_commodity: list[tuple[str, Decimal]] | None = None,
        net_by_commodity: list[tuple[str, Decimal]] | None = None,
        commodity: str | None = None,
        stats: JournalStats | None = None,
    ) -> None:
        """Apply card values and liabilities."""
        hide_loading_overlay(self)
        if not self.is_attached:
            return
        if stats is not None:
            self.journal_stats = stats
            self.post_message(self.StatsLoaded(stats))
        # Guard against the widget being unmounted between the is_attached check
        # and the DOM query (can happen when a background worker completes after
        # the app has started tearing down during tests).
        try:
            self.query_one("#summary-overview-title", Static).update("Overview")
        except NoMatches:
            return

        # Income / Expenses / Net cards — delegated to PeriodSummaryCards
        self._apply_cards(summary, income_by_commodity, expenses_by_commodity, net_by_commodity)
        self._has_static_sections = bool(
            (
                summary is not None
                and (summary.income or summary.expenses or summary.investments)
            )
            or liabilities
        )

        # Liabilities table
        if liabilities is not None:
            ltable = self.query_one("#summary-liabilities-table", _DisplayTable)
            ltable.clear()
            liabilities_section = self.query_one("#summary-liabilities")

            if not liabilities:
                liabilities_section.display = False
                self._set_note("#summary-liabilities-note", "")
            else:
                liabilities_section.display = True
                totals = _totals_by_commodity(liabilities)
                for account, qty, com in liabilities:
                    share = _share_pct(qty, com, totals, commodity)
                    ltable.add_row(
                        Text(account),
                        fmt_amount(qty, com),
                        _share_cell(share),
                    )
                self._set_note(
                    "#summary-liabilities-note",
                    _conversion_note(totals, commodity),
                )
                self.call_after_refresh(
                    distribute_column_widths, ltable, self._BREAKDOWN_FIXED
                )
        self._apply_collapsed()
        self._sync_empty_state()
        # Secondary sections load only once the cards are on screen, so the
        # first figures never queue behind the portfolio and breakdown
        # queries.  Refreshes re-enter here and reload them too.
        self._load_breakdown_data()
        self._load_investment_data()

    def _apply_cards(
        self,
        summary,
        income_by_commodity: list[tuple[str, Decimal]] | None = None,
        expenses_by_commodity: list[tuple[str, Decimal]] | None = None,
        net_by_commodity: list[tuple[str, Decimal]] | None = None,
    ) -> None:
        """Update the Income / Expenses / Net cards for the selected month.

        Shared by the full static load and the month-only reload so period
        navigation never rebuilds the all-time sections (issue #265).
        """
        self.query_one(PeriodSummaryCards).update_summary(
            summary,
            income_by_commodity=income_by_commodity,
            expenses_by_commodity=expenses_by_commodity,
            net_by_commodity=net_by_commodity,
        )
        self._static_loaded = True
        # Sticky: a month-only reload must not clear the flag while
        # liabilities or other all-time sections still have content.
        self._has_static_sections = self._has_static_sections or bool(
            summary is not None
            and (summary.income or summary.expenses or summary.investments)
        )

    # ------------------------------------------------------------------
    # Month-only reload and period navigation (issue #265)
    # ------------------------------------------------------------------

    def reload_month(self) -> None:
        """Reload only the month-dependent sections (cards and breakdown)."""
        self._load_month_data()

    @work(thread=True, exclusive=True, group="summary-month")
    def _load_month_data(self) -> None:
        """Load cards and breakdown for the shared period anchor.

        All-time sections (liabilities, portfolio) are untouched, so a month
        step costs only the month-scoped queries.
        """
        commodity = resolve_default_commodity(self.journal_file)
        period = self._period_str()

        summary_result, net_result = gather_loads(
            [
                lambda: load_period_summary(
                    self.journal_file, period, cache=self._cache, commodity=commodity,
                    query=get_global_query(self),
                ),
                lambda: load_period_net_by_commodity(
                    self.journal_file, period, cache=self._cache,
                    query=get_global_query(self),
                ),
            ]
        )
        summary = _load_result(summary_result, None)
        net_by_commodity = _load_result(net_result, [])
        try:
            income_by_commodity = load_period_income_by_commodity(
                self.journal_file, period, cache=self._cache,
                query=get_global_query(self),
            )
        except HledgerError:
            income_by_commodity = []
        try:
            expenses_by_commodity = load_period_expenses_by_commodity(
                self.journal_file, period, cache=self._cache,
                query=get_global_query(self),
            )
        except HledgerError:
            expenses_by_commodity = []

        self.app.call_from_thread(
            self._apply_month_data,
            summary,
            income_by_commodity,
            expenses_by_commodity,
            net_by_commodity,
        )

    def _apply_month_data(
        self,
        summary,
        income_by_commodity: list[tuple[str, Decimal]],
        expenses_by_commodity: list[tuple[str, Decimal]],
        net_by_commodity: list[tuple[str, Decimal]],
    ) -> None:
        """Apply the month-scoped cards and reload the breakdown."""
        hide_loading_overlay(self)
        if not self.is_attached or not self.query("#summary-overview-title"):
            return
        self._apply_cards(summary, income_by_commodity, expenses_by_commodity, net_by_commodity)
        self._load_breakdown_data()

    def _navigate_month(self, months: int) -> None:
        """Move the shared period anchor by *months* and reload the month sections.

        Args:
            months: Number of months to shift (negative = backwards).
        """
        if not set_period(self, shift_months(get_period(self), months)):
            # Standalone widget without shared state: refresh locally.
            self.reload_month()

    def action_prev_month(self) -> None:
        """Navigate to the previous month."""
        self._navigate_month(-1)

    def action_next_month(self) -> None:
        """Navigate to the next month."""
        self._navigate_month(1)

    def action_prev_year(self) -> None:
        """Navigate to the previous year."""
        self._navigate_month(-12)

    def action_next_year(self) -> None:
        """Navigate to the next year."""
        self._navigate_month(12)

    def action_today_month(self) -> None:
        """Jump back to the current calendar month."""
        if not set_period(self, current_month_selection()):
            self.reload_month()

    def action_jump_to_latest(self) -> None:
        """Jump to the month of the journal's latest transaction."""
        stats = self.journal_stats or getattr(self.app, "journal_stats", None)
        if stats is None or stats.last_date is None:
            self.notify("No activity to jump to", severity="warning", timeout=3)
            return
        if not set_period(self, month_selection(stats.last_date)):
            self.reload_month()

    def action_go_to_period(self) -> None:
        """Open the period picker and jump to the chosen selection."""
        from hledger_textual.screens.period_picker import PeriodPickerModal

        stats = self.journal_stats or getattr(self.app, "journal_stats", None)

        def on_result(selection) -> None:
            if selection is not None:
                if not set_period(self, selection):
                    self.reload_month()

        self.app.push_screen(
            PeriodPickerModal(journal_stats=stats, current=get_period(self)),
            callback=on_result,
        )

    def on_click(self, event) -> None:
        """Handle a click on the empty-month hint."""
        if getattr(event.widget, "id", None) == "summary-month-hint":
            self.action_jump_to_latest()

    def _set_portfolio_loading(self) -> None:
        """Show a hint while the investment positions are being loaded."""
        try:
            self.query_one("#summary-portfolio-loading", Static).update(
                "[dim]Loading investments…[/dim]"
            )
        except NoMatches:
            return

    def _apply_investment_data(
        self,
        positions: list[tuple[str, Decimal, str]],
        cost_by_account: dict[str, tuple[Decimal, str]],
        tickers: dict[str, str],
        loading_msg: str,
    ) -> None:
        """Apply the basic investment portfolio (without market prices)."""
        if (
            not self.is_attached
            or not self.query("#summary-portfolio-table")
            or not self.query("#summary-portfolio-loading")
        ):
            self._investments_loaded = True
            self._sync_empty_state()
            return
        ptable = self.query_one("#summary-portfolio-table", DataTable)
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
        self._has_static_sections = self._has_static_sections or bool(positions)
        self._investments_loaded = True
        self._apply_collapsed()
        self._sync_empty_state()

    def _apply_portfolio_eur(
        self,
        positions: list[tuple[str, Decimal, str]],
        cost_by_account: dict[str, tuple[Decimal, str]],
        tickers: dict[str, str],
        eur_by_account: dict[str, tuple[Decimal, str]],
        post_msg: str,
    ) -> None:
        """Rebuild the investments table with actual Value (€) data from pricehist."""
        if (
            not self.is_attached
            or not self.query("#summary-portfolio-table")
            or not self.query("#summary-portfolio-loading")
        ):
            return
        ptable = self.query_one("#summary-portfolio-table", DataTable)
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
        self._apply_collapsed()

    def _fill_portfolio_rows(
        self,
        ptable: DataTable,
        by_commodity: dict[str, list[tuple[str, Decimal]]],
        cost_by_account: dict[str, tuple[Decimal, str]],
        tickers: dict[str, str],
        eur_by_account: dict[str, tuple[Decimal, str]] | None = None,
    ) -> None:
        """Fill investments DataTable rows.

        Always emits 6 columns (Symbol, Quantity, Avg Cost, Market Value,
        Unrealised P/L, % of Portfolio).  Columns without data show '—'.

        Args:
            ptable: The DataTable to populate.
            by_commodity: Investment positions grouped by commodity name.
            cost_by_account: Book value per account (from load_investment_cost).
            tickers: Commodity-to-ticker mappings from config.
            eur_by_account: EUR market value per account, or None if loading/unavailable.
        """
        for row in _portfolio_rows(
            by_commodity, cost_by_account, tickers, eur_by_account
        ):
            avg_str = (
                fmt_amount(row.avg_cost, row.book_commodity)
                if row.avg_cost is not None
                else "\u2014"
            )
            market_str = (
                fmt_amount(row.market_total, row.market_commodity)
                if row.market_total is not None
                else "\u2014"
            )
            if row.unrealised_pl is None:
                pl_str = "\u2014"
            else:
                pl_str = fmt_amount(row.unrealised_pl, row.market_commodity)
                if row.unrealised_pl > 0:
                    pl_str = f"[green]{pl_str}[/green]"
                elif row.unrealised_pl < 0:
                    pl_str = f"[red]{pl_str}[/red]"
            ptable.add_row(
                row.commodity,
                f"{row.quantity:g}",
                avg_str,
                market_str,
                pl_str,
                _share_cell(row.portfolio_pct),
                key=row.commodity,
            )

    @work(thread=True, exclusive=True, group="summary-breakdown")
    def _load_breakdown_data(self) -> None:
        """Load income and expense breakdowns for the selected month."""
        self.app.call_from_thread(show_loading_overlay, self, "Loading breakdown…")
        period = self._period_str()
        # Convert both sides to the default commodity so that percentages are
        # computed on comparable amounts (mirrors the cards and Accounts view).
        commodity = resolve_default_commodity(self.journal_file)

        income_result, expense_result = gather_loads(
            [
                lambda: load_income_breakdown(
                    self.journal_file, period, commodity=commodity, cache=self._cache,
                    query=get_global_query(self),
                ),
                lambda: load_expense_breakdown(
                    self.journal_file, period, commodity=commodity, cache=self._cache,
                    query=get_global_query(self),
                ),
            ]
        )
        income_breakdown = _load_result(income_result, [])
        breakdown = _load_result(expense_result, [])

        self.app.call_from_thread(
            self._apply_breakdown_data, income_breakdown, breakdown, commodity
        )

    def _apply_breakdown_data(
        self,
        income_breakdown: list,
        breakdown: list,
        commodity: str | None = None,
    ) -> None:
        """Apply loaded income and expense breakdowns to their tables."""
        hide_loading_overlay(self)
        # Guard against teardown: is_attached can still be True for a moment
        # while the child widgets have already been removed.
        if not self.is_attached or not self.query("#summary-income-title"):
            return

        month_name = get_period(self).label

        # --- Income breakdown ---
        self.query_one("#summary-income-title", Static).update(
            f"{month_name} Income"
        )

        self._summary_export_rows = []
        income_section = self.query_one("#summary-income-breakdown")
        itable = self.query_one("#summary-income-table", DataTable)
        itable.clear()

        if not income_breakdown:
            income_section.display = False
            self._set_note("#summary-income-note", "")
        else:
            income_section.display = True
            totals = _totals_by_commodity(income_breakdown)
            for account, qty, com in income_breakdown:
                share = _share_pct(qty, com, totals, commodity)
                itable.add_row(
                    Text(account),
                    fmt_amount(qty, com),
                    _share_cell(share),
                )
                self._summary_export_rows.append(
                    ["Income", account, fmt_amount(qty, com), _share_cell(share)]
                )
            self._set_note(
                "#summary-income-note", _conversion_note(totals, commodity)
            )
            self.call_after_refresh(
                distribute_column_widths, itable, self._BREAKDOWN_FIXED
            )

        # --- Expense breakdown ---
        self.query_one("#summary-breakdown-title", Static).update(
            f"{month_name} Expenses"
        )

        expense_section = self.query_one("#summary-breakdown")
        table = self.query_one("#summary-breakdown-table", DataTable)
        table.clear()

        self._breakdown_loaded = True
        self._has_breakdown_sections = bool(income_breakdown or breakdown)
        self._update_month_hint(income_breakdown, breakdown)

        if not breakdown:
            expense_section.display = False
            self._set_note("#summary-breakdown-note", "")
            self._ensure_focus()
            self._sync_empty_state()
            return

        expense_section.display = True
        totals = _totals_by_commodity(breakdown)
        for account, qty, com in breakdown:
            share = _share_pct(qty, com, totals, commodity)
            table.add_row(
                Text(account),
                fmt_amount(qty, com),
                _share_cell(share),
            )
            self._summary_export_rows.append(
                ["Expenses", account, fmt_amount(qty, com), _share_cell(share)]
            )
        self._set_note("#summary-breakdown-note", _conversion_note(totals, commodity))

        self.call_after_refresh(
            distribute_column_widths, table, self._BREAKDOWN_FIXED
        )
        self._ensure_focus()
        self._sync_empty_state()

    def _ensure_focus(self) -> None:
        """Keep focus inside the pane when a section hides under it.

        Hiding the focused breakdown table on an empty month would strand
        focus outside the pane and disable its navigation bindings.  The
        check walks the focused widget's ancestors because Textual may blur
        a hidden widget asynchronously.
        """
        if not self.display:
            return
        focused = self.app.focused
        if focused is None:
            self.focus()
            return
        node = focused
        while node is not None and node is not self:
            if not node.display:
                self.focus()
                return
            node = node.parent

    def _update_month_hint(self, income_breakdown: list, breakdown: list) -> None:
        """Show the empty-month hint with a jump-to-latest action when needed.

        Instead of silent zeros, an empty month offers a one-click jump to the
        journal's latest activity (issue #265).  Fully empty journals show the
        global empty state instead, so no hint is offered there.
        """
        # Tolerate teardown: a pending breakdown worker can apply after the
        # pane's children have started being removed.
        hints = self.query("#summary-month-hint")
        if not hints:
            return
        hint = hints.first()
        stats = self.journal_stats
        period = get_period(self)
        if income_breakdown or breakdown or stats is None or stats.last_date is None:
            hint.update("")
            hint.display = False
            return
        hint.update(
            f"[dim]No transactions in {period.label}. [/dim]"
            "[bold]Jump to latest activity[/bold][dim] (click or press J)[/dim]"
        )
        hint.display = True

    def get_export_data(self):
        """Return an ExportData with the income/expense breakdown rows."""
        from hledger_textual.export import ExportData

        return ExportData.from_rows(
            "Summary",
            ["Section", "Account", "Amount", "% of total"],
            self._summary_export_rows,
            "summary",
        )

    def _set_note(self, selector: str, text: str) -> None:
        """Update a conversion note below a breakdown table."""
        note = self.query_one(selector, Static)
        note.update(text)
        note.display = bool(text)

    def _sync_empty_state(self) -> None:
        """Show the summary empty state once all summary sections have loaded."""
        if not (self._static_loaded and self._breakdown_loaded):
            return
        if not self._loaded_posted:
            self._loaded_posted = True
            self.post_message(self.Loaded())
        if not self._investments_loaded:
            return
        self._set_empty_state_visible(
            not (self._has_static_sections or self._has_breakdown_sections)
        )

    def _set_empty_state_visible(self, visible: bool) -> None:
        """Toggle the summary empty state and mounted content."""
        try:
            self.query_one("#summary-empty-state", EmptyState).display = visible
            self.query_one("#summary-content").display = not visible
        except NoMatches:
            return
