"""Tests for the PeriodSummaryCards widget."""

from __future__ import annotations

from decimal import Decimal


from textual.app import App, ComposeResult
from textual.widgets import Digits, Static

from hledger_textual.models import PeriodSummary
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
                commodity="\u20ac",
                investments=Decimal("500"),
            )
            cards.update_summary(summary)
            await pilot.pause()

            note = cards.query_one(".net-note", Static)
            assert "500" in note.renderable
            assert "invested" in note.renderable
