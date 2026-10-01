"""Reusable Income / Expenses / Net summary cards widget."""

from __future__ import annotations

from decimal import Decimal

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Digits, Static

from hledger_textual.models import PeriodSummary
from hledger_textual.widgets.currency_marquee import CurrencyMarquee
from hledger_textual.widgets.formatting import (
    compute_saving_rate,
    fmt_amount,
)


class PeriodSummaryCards(Widget):
    """Three side-by-side cards showing Income, Expenses, and Net for a period.

    Args:
        compact: When True, applies the ``compact-cards`` CSS class which hides
            auxiliary text (net note, saving rate) for use in tighter layouts.
    """

    def __init__(self, compact: bool = False, **kwargs) -> None:
        """Initialize the cards widget.

        Args:
            compact: Whether to use the compact layout variant.
        """
        super().__init__(**kwargs)
        self._compact = compact

    def compose(self) -> ComposeResult:
        """Yield three summary cards inside a horizontal container."""
        classes = "period-summary-cards"
        if self._compact:
            classes += " compact-cards"
        with Horizontal(classes=classes):
            with Vertical(classes="summary-card"):
                yield Static("Income", classes="summary-card-title")
                yield Digits("--", classes="summary-card-value income-value")
                yield CurrencyMarquee("", classes="income-multicurrency")
            with Vertical(classes="summary-card"):
                yield Static("Expenses", classes="summary-card-title")
                yield Digits("--", classes="summary-card-value expenses-value")
                yield CurrencyMarquee("", classes="expenses-multicurrency")
            with Vertical(classes="summary-card"):
                yield Static("Net", classes="summary-card-title")
                yield Digits("--", classes="summary-card-value net-value")
                yield Static("", classes="net-note")
                yield Static("", classes="saving-rate")
                yield CurrencyMarquee("", classes="summary-multicurrency net-multicurrency")

    def update_summary(
        self,
        summary: PeriodSummary | None,
        *,
        income_by_commodity: list[tuple[str, Decimal]] | None = None,
        expenses_by_commodity: list[tuple[str, Decimal]] | None = None,
        net_by_commodity: list[tuple[str, Decimal]] | None = None,
    ) -> None:
        """Update all card values from a PeriodSummary.

        Args:
            summary: The period data to display, or None to reset to dashes.
            income_by_commodity: Per-currency income totals for the marquee line.
            expenses_by_commodity: Per-currency expense totals for the marquee line.
            net_by_commodity: Per-currency net totals for the marquee line.
        """
        if summary is not None:
            com = summary.commodity
            net = summary.net

            self.query_one(".income-value", Digits).update(
                fmt_amount(summary.income, com)
            )
            self.query_one(".expenses-value", Digits).update(
                fmt_amount(summary.expenses, com)
            )

            net_widget = self.query_one(".net-value", Digits)
            if net >= 0:
                net_widget.update(fmt_amount(net, com))
                net_widget.remove_class("net-negative")
                net_widget.add_class("net-positive")
            else:
                net_widget.update(fmt_amount(net, com))
                net_widget.remove_class("net-positive")
                net_widget.add_class("net-negative")

            note = self.query_one(".net-note", Static)
            if summary.investments > 0:
                note.update(f"incl. {fmt_amount(summary.investments, com)} invested")
                note.display = True
            else:
                note.update("")
                note.display = False

            rate_widget = self.query_one(".saving-rate", Static)
            rate = compute_saving_rate(summary.income, summary.expenses)
            if rate is not None:
                rate_widget.update(f"Saving rate: {rate:.0f}%")
            else:
                rate_widget.update("")

            net_items = (
                summary.net_by_commodity
                if net_by_commodity is None
                else net_by_commodity
            )
            income_items = (
                summary.income_by_commodity
                if income_by_commodity is None
                else income_by_commodity
            )
            expense_items = (
                summary.expenses_by_commodity
                if expenses_by_commodity is None
                else expenses_by_commodity
            )
            self._update_marquee(".net-multicurrency", net_items)
            self._update_marquee(".income-multicurrency", income_items)
            self._update_marquee(".expenses-multicurrency", expense_items)
        else:
            for cls in (".income-value", ".expenses-value", ".net-value"):
                self.query_one(cls, Digits).update("--")
            self.query_one(".net-note", Static).update("")
            self.query_one(".net-note", Static).display = False
            self.query_one(".saving-rate", Static).update("")
            for cls in (
                ".income-multicurrency",
                ".expenses-multicurrency",
                ".net-multicurrency",
            ):
                self._update_marquee(cls, [])

    def _update_marquee(
        self, selector: str, items: list[tuple[str, Decimal]]
    ) -> None:
        """Show a per-commodity marquee for ``selector``, hiding it below 2 items."""
        marquee = self.query_one(selector, CurrencyMarquee)
        if len(items) > 1:
            marquee.set_content(
                ", ".join(fmt_amount(amount, cur) for cur, amount in items)
            )
            marquee.display = True
        else:
            marquee.set_content("")
            marquee.display = False
