"""Tests for the PeriodSummaryCards widget."""

from __future__ import annotations

from decimal import Decimal


from textual.app import App, ComposeResult
from textual.widgets import Digits, Static

from hledger_textual.models import PeriodSummary
from hledger_textual.widgets.currency_marquee import CurrencyMarquee
from hledger_textual.widgets.period_summary_cards import PeriodSummaryCards


class _CardsApp(App):
    """Minimal app wrapping PeriodSummaryCards for isolated testing."""

    def __init__(self, compact: bool = False) -> None:
        """Initialize with optional compact mode."""
        super().__init__()
        self._compact = compact

    def compose(self) -> ComposeResult:
        """Compose a single PeriodSummaryCards widget."""
        yield PeriodSummaryCards(compact=self._compact, id="test-cards")


class TestPeriodSummaryCardsCompose:
    """Tests for widget composition."""

    async def test_compose_yields_three_digits(self):
        """The widget contains exactly three Digits widgets."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            displays = cards.query(Digits)
            assert len(displays) == 3

    async def test_compose_has_expected_classes(self):
        """The three Digits widgets have the expected CSS classes."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            assert cards.query_one(".income-value", Digits) is not None
            assert cards.query_one(".expenses-value", Digits) is not None
            assert cards.query_one(".net-value", Digits) is not None

    async def test_compact_class_applied(self):
        """When compact=True, the container has the compact-cards class."""
        app = _CardsApp(compact=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            container = cards.query_one(".period-summary-cards")
            assert container.has_class("compact-cards")

    async def test_non_compact_no_class(self):
        """When compact=False, the container does not have the compact-cards class."""
        app = _CardsApp(compact=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            container = cards.query_one(".period-summary-cards")
            assert not container.has_class("compact-cards")


class TestPeriodSummaryCardsUpdate:
    """Tests for the update_summary method."""

    async def test_update_summary_positive_net(self):
        """Positive net shows correct values and net-positive class."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            summary = PeriodSummary(
                income=Decimal("3000"),
                expenses=Decimal("1200"),
                commodity="\u20ac",
            )
            cards.update_summary(summary)
            await pilot.pause()

            income = cards.query_one(".income-value", Digits)
            assert "3,000" in income.value

            expenses = cards.query_one(".expenses-value", Digits)
            assert "1,200" in expenses.value

            net = cards.query_one(".net-value", Digits)
            assert "1,800" in net.value
            assert net.has_class("net-positive")
            assert not net.has_class("net-negative")

    async def test_update_summary_negative_net(self):
        """Negative net shows negative marker and net-negative class."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            summary = PeriodSummary(
                income=Decimal("500"),
                expenses=Decimal("800"),
                commodity="\u20ac",
            )
            cards.update_summary(summary)
            await pilot.pause()

            net = cards.query_one(".net-value", Digits)
            assert "-" in net.value
            assert net.has_class("net-negative")
            assert not net.has_class("net-positive")

    async def test_update_summary_none_resets(self):
        """Passing None resets all values to dashes."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)

            # First set values
            summary = PeriodSummary(
                income=Decimal("1000"),
                expenses=Decimal("500"),
                commodity="\u20ac",
            )
            cards.update_summary(summary)
            await pilot.pause()

            # Then reset
            cards.update_summary(None)
            await pilot.pause()

            for cls in (".income-value", ".expenses-value", ".net-value"):
                widget = cards.query_one(cls, Digits)
                assert widget.value == "--"

            note = cards.query_one(".net-note", Static)
            assert note.renderable == ""

            rate = cards.query_one(".saving-rate", Static)
            assert rate.renderable == ""

    async def test_saving_rate_shown(self):
        """Saving rate is displayed when income is positive."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            summary = PeriodSummary(
                income=Decimal("2000"),
                expenses=Decimal("800"),
                commodity="\u20ac",
            )
            cards.update_summary(summary)
            await pilot.pause()

            rate = cards.query_one(".saving-rate", Static)
            assert "Saving rate:" in rate.renderable
            assert "60%" in rate.renderable

    async def test_investment_note_shown(self):
        """Investment note is shown when investments > 0."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            summary = PeriodSummary(
                income=Decimal("3000"),
                expenses=Decimal("1000"),
                commodity="€",
                investments=Decimal("500"),
            )
            cards.update_summary(summary)
            await pilot.pause()

            note = cards.query_one(".net-note", Static)
            assert "500" in note.renderable
            assert "invested" in note.renderable


class TestPeriodSummaryCardsMarquee:
    """Tests for the per-currency marquee line under the Net card."""

    async def test_marquee_hidden_when_single_currency(self):
        """One commodity in net_by_commodity leaves the marquee hidden."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            summary = PeriodSummary(
                income=Decimal("3000"),
                expenses=Decimal("1000"),
                commodity="€",
                net_by_commodity=[("€", Decimal("2000"))],
            )
            cards.update_summary(summary)
            await pilot.pause()

            marquee = cards.query_one(".summary-multicurrency", CurrencyMarquee)
            assert marquee.display is False
            assert marquee._text == ""

    async def test_marquee_hidden_when_empty(self):
        """An empty net_by_commodity leaves the marquee hidden."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            summary = PeriodSummary(
                income=Decimal("3000"),
                expenses=Decimal("1000"),
                commodity="€",
            )
            cards.update_summary(summary)
            await pilot.pause()

            marquee = cards.query_one(".summary-multicurrency", CurrencyMarquee)
            assert marquee.display is False

    async def test_marquee_shows_joined_text_when_multi_currency(self):
        """Multiple commodities show the marquee with the joined balances."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            summary = PeriodSummary(
                income=Decimal("3000"),
                expenses=Decimal("1000"),
                commodity="€",
                net_by_commodity=[
                    ("€", Decimal("1500")),
                    ("£", Decimal("420")),
                    ("$", Decimal("-80")),
                ],
            )
            cards.update_summary(summary)
            await pilot.pause()

            marquee = cards.query_one(".summary-multicurrency", CurrencyMarquee)
            assert marquee.display is True
            assert "€" in marquee._text
            assert "£" in marquee._text
            assert "$" in marquee._text
            assert ", " in marquee._text

    async def test_marquee_resets_on_none_summary(self):
        """update_summary(None) hides and clears the marquee."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            cards.update_summary(
                PeriodSummary(
                    income=Decimal("3000"),
                    expenses=Decimal("1000"),
                    commodity="€",
                    net_by_commodity=[("€", Decimal("1")), ("£", Decimal("2"))],
                )
            )
            await pilot.pause()
            cards.update_summary(None)
            await pilot.pause()

            marquee = cards.query_one(".summary-multicurrency", CurrencyMarquee)
            assert marquee.display is False
            assert marquee._text == ""

    async def test_s6_marquee_rotates_when_overflowing_narrow_card(self):
        """S6: in a narrow card the overflowing currency list scrolls."""
        app = _CardsApp()
        async with app.run_test(size=(36, 8)) as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            summary = PeriodSummary(
                income=Decimal("20000"),
                expenses=Decimal("1000"),
                commodity="€",
                net_by_commodity=[
                    ("€", Decimal("8000.00")),
                    ("£", Decimal("5000.00")),
                    ("$", Decimal("3500.00")),
                    ("BTC", Decimal("2500.00")),
                ],
            )
            cards.update_summary(summary)
            await pilot.pause()

            marquee = cards.query_one(".summary-multicurrency", CurrencyMarquee)
            assert marquee.display is True
            assert marquee._is_scrolling, (
                f"marquee should scroll (text {len(marquee._text)}ch, "
                f"width {marquee.size.width})"
            )
            start = marquee._offset
            await pilot.pause(delay=0.3)
            assert marquee._offset != start


class TestPeriodSummaryCardsPerSideMarquee:
    """Per-currency lines under the Income and Expenses cards (S10)."""

    async def test_income_card_shows_marquee_when_multi_currency(self):
        """Income card surfaces its own currencies when > 1 side commodity."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            cards.update_summary(
                PeriodSummary(
                    income=Decimal("30000"),
                    expenses=Decimal("1000"),
                    commodity="€",
                    net_by_commodity=[("€", Decimal("100")), ("$", Decimal("200"))],
                    income_by_commodity=[
                        ("€", Decimal("2500")),
                        ("$", Decimal("5300")),
                    ],
                )
            )
            await pilot.pause()
            income_marquee = cards.query_one(
                ".income-multicurrency", CurrencyMarquee
            )
            assert income_marquee.display is True
            assert "€" in income_marquee._text
            assert "$" in income_marquee._text

    async def test_expenses_card_shows_marquee_when_multi_currency(self):
        """Expenses card surfaces its own currencies when > 1 side commodity."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            cards.update_summary(
                PeriodSummary(
                    income=Decimal("30000"),
                    expenses=Decimal("9000"),
                    commodity="€",
                    net_by_commodity=[("€", Decimal("100")), ("$", Decimal("200"))],
                    expenses_by_commodity=[
                        ("€", Decimal("5700")),
                        ("£", Decimal("54")),
                    ],
                )
            )
            await pilot.pause()
            expenses_marquee = cards.query_one(
                ".expenses-multicurrency", CurrencyMarquee
            )
            assert expenses_marquee.display is True
            assert "€" in expenses_marquee._text
            assert "£" in expenses_marquee._text

    async def test_side_marquees_hidden_when_single_currency(self):
        """Income/Expenses marquees stay hidden for single-currency sides."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            cards.update_summary(
                PeriodSummary(
                    income=Decimal("3000"),
                    expenses=Decimal("1000"),
                    commodity="€",
                    net_by_commodity=[("€", Decimal("2000"))],
                    income_by_commodity=[("€", Decimal("3000"))],
                    expenses_by_commodity=[("€", Decimal("1000"))],
                )
            )
            await pilot.pause()
            assert (
                cards.query_one(
                    ".income-multicurrency", CurrencyMarquee
                ).display
                is False
            )
            assert (
                cards.query_one(
                    ".expenses-multicurrency", CurrencyMarquee
                ).display
                is False
            )

    async def test_side_marquees_reset_on_none(self):
        """update_summary(None) hides all three per-currency lines."""
        app = _CardsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            cards = app.query_one(PeriodSummaryCards)
            cards.update_summary(
                PeriodSummary(
                    income=Decimal("30000"),
                    expenses=Decimal("9000"),
                    commodity="€",
                    net_by_commodity=[("€", Decimal("100")), ("$", Decimal("1"))],
                    income_by_commodity=[("€", Decimal("2500")), ("$", Decimal("5300"))],
                    expenses_by_commodity=[("€", Decimal("5700")), ("£", Decimal("54"))],
                )
            )
            await pilot.pause()
            cards.update_summary(None)
            await pilot.pause()
            for cls in (
                ".income-multicurrency",
                ".expenses-multicurrency",
                ".summary-multicurrency",
            ):
                w = cards.query_one(cls, CurrencyMarquee)
                assert w.display is False, f"{cls} should hide"
                assert w._text == ""
