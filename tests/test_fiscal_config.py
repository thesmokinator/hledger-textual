"""fiscal_year_start config and fiscal year selection (issue #279)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at an empty temp path."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    return config_file


class TestLoadFiscalYearStart:
    """load_fiscal_year_start reads 1–12, defaulting to January."""

    def test_missing_key_defaults_to_january(
        self, tmp_config: Path
    ) -> None:
        from hledger_textual.config import load_fiscal_year_start

        assert load_fiscal_year_start() == 1

    def test_april_start(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from hledger_textual.config import load_fiscal_year_start

        config_file = tmp_path / "config.toml"
        config_file.write_text("fiscal_year_start = 4\n", encoding="utf-8")
        monkeypatch.setattr(
            "hledger_textual.config._CONFIG_PATH", config_file
        )
        assert load_fiscal_year_start() == 4

    def test_invalid_values_fall_back_to_january(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from hledger_textual.config import load_fiscal_year_start

        for bad in ["0", "13", '"april"', "true"]:
            config_file = tmp_path / "config.toml"
            config_file.write_text(
                f"fiscal_year_start = {bad}\n", encoding="utf-8"
            )
            monkeypatch.setattr(
                "hledger_textual.config._CONFIG_PATH", config_file
            )
            assert load_fiscal_year_start() == 1, bad


class TestFiscalYearSelection:
    """fiscal_year_selection covers the April→March span."""

    def test_bounds_and_label(self) -> None:
        from hledger_textual.period import fiscal_year_selection

        sel = fiscal_year_selection(2024, 4)
        assert (sel.begin, sel.end) == (date(2024, 4, 1), date(2025, 4, 1))
        assert sel.period_expr == "2024-04..2025-03"

    def test_january_matches_calendar_year(self) -> None:
        from hledger_textual.period import fiscal_year_selection, year_selection

        assert fiscal_year_selection(2024, 1) == year_selection(2024)

    def test_parse_round_trip(self) -> None:
        from hledger_textual.period import fiscal_year_selection, parse_period

        sel = fiscal_year_selection(2024, 4)
        reparsed = parse_period(sel.period_expr, today=date(2024, 6, 15))
        assert reparsed is not None
        assert (reparsed.begin, reparsed.end) == (sel.begin, sel.end)
