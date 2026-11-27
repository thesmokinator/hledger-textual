"""Yearly/quarterly interval threading in report loaders (issue #278)."""

from __future__ import annotations

from pathlib import Path

import pytest


def _capture(monkeypatch: pytest.MonkeyPatch, output: str = ""):
    """Patch run_hledger; return the recorded arg tuples."""
    calls: list[tuple[tuple[str, ...], object]] = []

    def fake(*args: str, file=None) -> str:
        calls.append((args, file))
        return output

    monkeypatch.setattr("hledger_textual.hledger.run_hledger", fake)
    return calls


class TestReportInterval:
    """interval selects the hledger multi-period flag; default stays monthly."""

    def test_year_interval_uses_Y_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_report

        calls = _capture(monkeypatch)
        load_report(tmp_path / "j.journal", "is", interval="year")
        assert "-Y" in calls[0][0]
        assert "-M" not in calls[0][0]

    def test_quarter_interval_uses_Q_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_report

        calls = _capture(monkeypatch)
        load_report(tmp_path / "j.journal", "bs", interval="quarter")
        assert "-Q" in calls[0][0]
        assert "-M" not in calls[0][0]

    def test_default_stays_monthly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_report

        calls = _capture(monkeypatch)
        load_report(tmp_path / "j.journal", "cf")
        assert "-M" in calls[0][0]

    def test_investment_report_year_interval(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_investment_report

        calls = _capture(monkeypatch)
        load_investment_report(tmp_path / "j.journal", interval="year")
        assert "-Y" in calls[0][0]
        assert "-M" not in calls[0][0]

    def test_explicit_month_interval(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_report

        calls = _capture(monkeypatch)
        load_report(tmp_path / "j.journal", "is", interval="month")
        assert "-M" in calls[0][0]
