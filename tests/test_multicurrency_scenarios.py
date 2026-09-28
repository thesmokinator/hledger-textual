"""Multi-currency scenario contract (S1-S4).

These tests pin the end-to-end contract for balances over multi-currency
journals:

- S1: Accounts flat view, ``default_commodity`` unset -> original currencies.
- S2: Accounts flat view, ``default_commodity = "€"`` -> every account folded
  to a single EUR amount via ``hledger -X``.
- S3: Reports flat (non-stacked) view, conversion off -> multi-currency
  accounts are marked with MULTI_COMMODITY_MARKER.
- S4: Reports flat view with conversion on (single-currency cells) -> no
  account is marked.

S5 (regression: tree accounts view, stacked reports mode, single-currency
journals) is covered by the existing suites and the full `pytest` gate.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from textual.coordinate import Coordinate
from textual.widgets import DataTable

from hledger_textual.models import ReportData, ReportRow
from hledger_textual.widgets.reports_pane import (
    MULTI_COMMODITY_MARKER,
    ReportsPane,
)
from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _build_priced_journal(tmp_path: Path) -> Path:
    """Concatenate the multi-currency example journal with its price db."""
    base = (_REPO_ROOT / "examples" / "multicurrency.journal").read_text()
    prices = (_REPO_ROOT / "examples" / "multicurrency-prices.journal").read_text()
    # Strip include directives that reference files outside tmp_path.
    base_lines = [line for line in base.splitlines() if not line.startswith("include ")]
    journal = tmp_path / "multicurrency.journal"
    journal.write_text("\n".join(base_lines) + "\n\n" + prices)
    return journal


def _accounts_cell(app, account: str) -> str:
    """Return the balance cell text for an account row in the accounts table."""
    table = app.screen.query_one("#accounts-table", DataTable)
    for i in range(table.row_count):
        row = table.get_row_at(i)
        first = row[0]
        plain = first.plain if hasattr(first, "plain") else str(first)
        if plain == account:
            cell = row[1]
            return cell.plain if hasattr(cell, "plain") else str(cell)
    raise AssertionError(f"account row {account!r} not found")


async def test_s1_accounts_flat_shows_all_currencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """S1: neither journal directive nor config -> original currencies shown."""
    from hledger_textual.app import HledgerTuiApp

    monkeypatch.setattr(
        "hledger_textual.widgets.accounts_pane.load_accounts_view", lambda: "flat"
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.accounts_pane.save_accounts_view", lambda _m: None
    )
    # The example journal declares commodities (`commodity €…` first), so under
    # the new resolution order that alone would convert. S1 pins the no-conversion
    # path, which needs a journal with no `commodity` directives.
    directive_free = tmp_path / "mc.journal"
    base = (_REPO_ROOT / "examples" / "multicurrency.journal").read_text()
    include_free = [
        l
        for l in base.splitlines()
        if not l.lstrip().startswith("include ")
        and not l.startswith("commodity ")
    ]
    directive_free.write_text("\n".join(include_free) + "\n")
    # No stub — the resolver sees no directive and the config fixture (from
    # conftest) provides no default_commodity.

    app = HledgerTuiApp(journal_file=directive_free)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("6")
        await pilot.pause(delay=2.0)

        cell = _accounts_cell(app, "assets:bank:checking")
        table = app.screen.query_one("#accounts-table", DataTable)
        keys = {rk.value: rk for rk in table.rows.keys() if rk.value}
        height = table.get_row_height(keys["assets:bank:checking"])

    assert "£" in cell, f"GBP balance missing: {cell!r}"
    assert "€" in cell, f"EUR balance missing: {cell!r}"
    assert "\n" in cell, f"currencies should stack in the cell: {cell!r}"
    assert height >= 2, (
        f"multi-currency row renders at height {height}; stacked lines clipped"
    )


async def test_s2_accounts_convert_to_configured_commodity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """S2: default_commodity=€ -> -X conversion folds every account to EUR."""
    from hledger_textual.app import HledgerTuiApp

    journal = _build_priced_journal(tmp_path)
    monkeypatch.setattr(
        "hledger_textual.widgets.accounts_pane.load_accounts_view", lambda: "flat"
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.accounts_pane.save_accounts_view", lambda _m: None
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.accounts_pane.resolve_default_commodity",
        lambda _file: "€",
    )

    app = HledgerTuiApp(journal_file=journal)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("6")
        await pilot.pause(delay=2.0)

        cell = _accounts_cell(app, "assets:bank:checking")
        table = app.screen.query_one("#accounts-table", DataTable)
        keys = {rk.value: rk for rk in table.rows.keys() if rk.value}
        height = table.get_row_height(keys["assets:bank:checking"])

    assert "€" in cell, f"EUR balance missing: {cell!r}"
    assert "£" not in cell, f"unconverted GBP remains: {cell!r}"
    assert "$" not in cell, f"unconverted USD remains: {cell!r}"
    assert "\n" not in cell, f"converted cell should be single-line: {cell!r}"
    assert height == 1, f"converted row should render single-line, got {height}"


async def test_s3_reports_flat_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """S3: flat + unstacked + multi-currency row -> marker on account cell."""
    from tests.test_reports_pane import _ReportsApp

    journal = tmp_path / "j.journal"
    journal.write_text("; empty\n")
    data = ReportData(
        title="BS",
        period_headers=["Sep", "Oct"],
        rows=[
            ReportRow(
                account="assets:bank:checking",
                amounts=["£1400.00, €700.00", "£1500.00, €720.00"],
            ),
            ReportRow(
                account="assets:bank:savings",
                amounts=["$500.00", "$600.00"],
            ),
        ],
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.reports_pane.load_report",
        lambda *args, **kwargs: ReportData(title="", period_headers=[], rows=[]),
    )

    app = _ReportsApp(journal)
    async with app.run_test() as pilot:
        await pilot.pause(delay=0.5)
        pane = app.query_one(ReportsPane)
        pane._report_data = data
        pane._stacked_currency = False
        pane._apply_report()
        await pilot.pause()

        table = app.query_one("#reports-table", DataTable)
        texts = []
        for i in range(table.row_count):
            cell = table.get_cell_at(Coordinate(i, 0))
            texts.append(cell.plain if hasattr(cell, "plain") else str(cell))

        checking = next(t for t in texts if "checking" in t)
        savings = next(t for t in texts if "savings" in t)

    assert checking.startswith(MULTI_COMMODITY_MARKER), (
        f"multi-currency row must be marked: {checking!r}"
    )
    assert not savings.startswith(MULTI_COMMODITY_MARKER), (
        f"single-currency row must not be marked: {savings!r}"
    )


async def test_s4_reports_flat_converted_no_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """S4: conversion on -> single-currency cells, no markers anywhere."""
    from tests.test_reports_pane import _ReportsApp

    journal = tmp_path / "j.journal"
    journal.write_text("; empty\n")
    data = ReportData(
        title="BS",
        period_headers=["Sep", "Oct"],
        rows=[
            ReportRow(
                account="assets:bank:checking",
                amounts=["€2100.00", "€2220.00"],
            ),
            ReportRow(
                account="assets:bank:savings",
                amounts=["€460.00", "€552.00"],
            ),
        ],
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.reports_pane.load_report",
        lambda *args, **kwargs: ReportData(title="", period_headers=[], rows=[]),
    )

    app = _ReportsApp(journal)
    async with app.run_test() as pilot:
        await pilot.pause(delay=0.5)
        pane = app.query_one(ReportsPane)
        pane._report_data = data
        pane._stacked_currency = False
        pane._apply_report()
        await pilot.pause()

        table = app.query_one("#reports-table", DataTable)
        texts = []
        for i in range(table.row_count):
            cell = table.get_cell_at(Coordinate(i, 0))
            texts.append(cell.plain if hasattr(cell, "plain") else str(cell))

    assert texts, "no rows rendered"
    for text in texts:
        assert not text.startswith(MULTI_COMMODITY_MARKER), (
            f"converted report must have no markers: {text!r}"
        )


async def test_s7_summary_net_converted_to_default_commodity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """S7: default_commodity=€ -> the Net card big number is €-converted,
    and the marquee lists the journal's R/X currencies."""
    from hledger_textual.app import HledgerTuiApp

    journal = _build_priced_journal(tmp_path)
    monkeypatch.setattr(
        "hledger_textual.widgets.summary_pane.resolve_default_commodity",
        lambda _file: "€",
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.summary_pane.load_price_tickers", lambda: {}
    )

    from hledger_textual.hledger import load_period_net_by_commodity

    truth_nets = dict(load_period_net_by_commodity(journal))

    from hledger_textual.widgets.period_summary_cards import PeriodSummaryCards

    app = HledgerTuiApp(journal_file=journal)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause(delay=3.0)

        cards = app.screen.query_one("#summary-cards", PeriodSummaryCards)
        net_text = cards.query_one(".net-value").value
        marquee = cards.query_one(".summary-multicurrency")
        marquee_text = marquee._text
        marquee_display = marquee.display

    assert "€" in net_text, f"Net card not €-converted: {net_text!r}"
    assert "£" not in net_text and "$" not in net_text, (
        f"Net card shows unconverted currency: {net_text!r}"
    )
    assert marquee_display is True
    assert truth_nets.keys() == {"€", "£", "$"}
    for cur in ("€", "£", "$"):
        assert cur in marquee_text, (
            f"currency {cur} missing from marquee text: {marquee_text!r}"
        )


async def test_s8_summary_unconverted_when_no_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """S8: no default_commodity -> big numbers keep current (unconverted)
    behavior; marquee still lists every R/X currency."""
    from hledger_textual.app import HledgerTuiApp

    journal = _build_priced_journal(tmp_path)
    monkeypatch.setattr(
        "hledger_textual.widgets.summary_pane.resolve_default_commodity",
        lambda _file: None,
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.summary_pane.load_price_tickers", lambda: {}
    )

    from hledger_textual.widgets.period_summary_cards import PeriodSummaryCards

    app = HledgerTuiApp(journal_file=journal)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause(delay=3.0)

        cards = app.screen.query_one("#summary-cards", PeriodSummaryCards)
        marquee = cards.query_one(".summary-multicurrency")
        marquee_text = marquee._text
        marquee_display = marquee.display

    # Pin current unconverted big-number behavior: the marquee must still show
    # all R/X currencies even though the Digits are not -X converted.
    assert marquee_display is True
    for cur in ("€", "£", "$"):
        assert cur in marquee_text, (
            f"currency {cur} missing from marquee: {marquee_text!r}"
        )


async def test_s9_single_currency_hides_marquee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """S9: single-currency journals never show the marquee."""
    from hledger_textual.app import HledgerTuiApp

    today = date.today()
    d1 = today.replace(day=1)
    journal = tmp_path / "single.journal"
    journal.write_text(
        f"{d1.isoformat()} * Salary\n"
        f"    assets:bank  €3000.00\n"
        f"    income:salary\n"
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.summary_pane.resolve_default_commodity",
        lambda _file: None,
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.summary_pane.load_price_tickers", lambda: {}
    )

    from hledger_textual.widgets.period_summary_cards import PeriodSummaryCards

    app = HledgerTuiApp(journal_file=journal)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause(delay=2.0)

        cards = app.screen.query_one("#summary-cards", PeriodSummaryCards)
        marquee = cards.query_one(".summary-multicurrency")
        assert marquee.display is False
        assert marquee._text == ""


async def test_s11_journal_directive_drives_conversion_without_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """S11: a journal with `commodity €` declared first converts the Accounts
    view to € on its own — no default_commodity config needed — and a
    different first declaration would convert to that instead."""
    from hledger_textual.app import HledgerTuiApp

    journal = _build_priced_journal(tmp_path)
    # The priced journal's first `commodity` directive is €; no stub of
    # resolve_default_commodity — the resolver reads the journal itself.
    monkeypatch.setattr(
        "hledger_textual.widgets.accounts_pane.load_accounts_view", lambda: "flat"
    )
    monkeypatch.setattr(
        "hledger_textual.widgets.accounts_pane.save_accounts_view", lambda _m: None
    )

    app = HledgerTuiApp(journal_file=journal)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("6")
        await pilot.pause(delay=2.0)

        cell = _accounts_cell(app, "assets:bank:checking")

    assert "€" in cell and "£" not in cell and "$" not in cell, (
        f"journal directive should convert to EUR; got {cell!r}"
    )

    # Flip the first directive to $ and confirm the conversion target follows.
    text = journal.read_text()
    flipped = tmp_path / "flipped.journal"
    flipped.write_text(text.replace("commodity €1,000.00", "commodity $1,000.00", 1))
    app2 = HledgerTuiApp(journal_file=flipped)
    async with app2.run_test() as pilot:
        await pilot.pause()
        await pilot.press("6")
        await pilot.pause(delay=2.0)

        cell = _accounts_cell(app2, "assets:bank:checking")

    assert "$" in cell and "€" not in cell, (
        f"flipped first directive should convert to USD; got {cell!r}"
    )
