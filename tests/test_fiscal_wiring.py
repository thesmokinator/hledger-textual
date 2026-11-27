"""Fiscal year wiring in app YTD paths (issue #279)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.period import month_selection, parse_period
from hledger_textual.widgets.reports_pane import ReportsPane


@pytest.fixture
def fy_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at a temp path with fiscal_year_start = 4."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("fiscal_year_start = 4\n", encoding="utf-8")
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    return config_file


@pytest.fixture
def empty_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at an empty temp path."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    return config_file


def _ytd_pane(month: date) -> ReportsPane:
    """ReportsPane with a YTD window anchored at *month* (no app needed)."""
    pane = ReportsPane.__new__(ReportsPane)
    pane._period_months = 0
    pane._period_fallback = month_selection(month)
    pane._comparison = "off"
    pane._comparison_years = []
    return pane


class TestReportsYtdWindow:
    """The YTD report window starts at the fiscal start month."""

    def test_ytd_window_april_start(self, fy_config: Path) -> None:
        pane = _ytd_pane(date(2024, 6, 15))
        assert pane._period_range() == ("2024-04-01", "2024-07-01")

    def test_ytd_window_defaults_to_january(
        self, empty_config: Path
    ) -> None:
        pane = _ytd_pane(date(2024, 6, 15))
        assert pane._period_range() == ("2024-01-01", "2024-07-01")

    def test_ytd_display_range_april_start(self, fy_config: Path) -> None:
        pane = _ytd_pane(date(2024, 6, 15))
        assert pane._window_display_range() == "2024-04 → 2024-06"

    def test_ytd_window_before_fiscal_start(self, fy_config: Path) -> None:
        """February with an April start belongs to the prior fiscal year."""
        pane = _ytd_pane(date(2024, 2, 10))
        assert pane._period_range() == ("2023-04-01", "2024-03-01")


class TestCliSemanticsStayCalendar:
    """parse_period never reads config: CLI -p keeps hledger semantics."""

    def test_ytd_ignores_fiscal_config(self, fy_config: Path) -> None:
        sel = parse_period("ytd", today=date(2024, 6, 15))
        assert sel is not None
        assert (sel.begin, sel.end) == (date(2024, 1, 1), date(2024, 6, 16))

    def test_this_year_ignores_fiscal_config(self, fy_config: Path) -> None:
        sel = parse_period("this year", today=date(2024, 6, 15))
        assert sel is not None
        assert (sel.begin, sel.end) == (date(2024, 1, 1), date(2025, 1, 1))
