"""Global query threading through hledger loaders (issue #281).

Each loader gains ``query: str | None = None``; when set, its tokens are
appended to the hledger args (after period args) and included in the cache
key.  ``run_hledger`` is mocked; canned minimal outputs exercise arg capture
without parsing failures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BAL_CSV = "account,balance\n"


def _capture(monkeypatch: pytest.MonkeyPatch, output: str = BAL_CSV):
    """Patch run_hledger; return the list of recorded arg tuples."""
    calls: list[tuple[tuple[str, ...], object]] = []

    def fake(*args: str, file=None) -> str:
        calls.append((args, file))
        return output

    monkeypatch.setattr("hledger_textual.hledger.run_hledger", fake)
    return calls


class TestBalanceLoaders:
    """Account balances append the query after balance flags."""

    def test_flat_appends_query(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_account_balances

        calls = _capture(monkeypatch)
        load_account_balances(tmp_path / "j.journal", query="tag:x")
        assert calls[0][0][-1] == "tag:x"

    def test_flat_no_query_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_account_balances

        calls = _capture(monkeypatch)
        load_account_balances(tmp_path / "j.journal")
        assert "tag:x" not in calls[0][0]
        assert calls[0][0] == (
            "balance", "--flat", "--no-total", "-O", "csv",
        )

    def test_tree_appends_query(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_account_tree_balances

        calls = _capture(monkeypatch)
        load_account_tree_balances(tmp_path / "j.journal", query="tag:x")
        assert calls[0][0][-1] == "tag:x"


class TestBudgetLoaders:
    """Budget reports append the query after the Expenses filter."""

    def test_single_appends_query(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_budget_report

        calls = _capture(monkeypatch, output="")
        load_budget_report(tmp_path / "j.journal", "2024-03", query="tag:x")
        assert calls[0][0][-1] == "tag:x"

    def test_multi_appends_query(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_multi_period_budget_report

        calls = _capture(monkeypatch, output="")
        load_multi_period_budget_report(
            tmp_path / "j.journal", "2024-01", "2024-03", query="tag:x"
        )
        assert calls[0][0][-1] == "tag:x"


class TestSummaryLoaders:
    """Period summary and sides append the query to every inner query."""

    def test_summary_appends_to_all_inner_queries(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_period_summary

        calls = _capture(monkeypatch)
        load_period_summary(
            tmp_path / "j.journal", "2024-03", query="tag:x not:cleared"
        )
        assert len(calls) == 3
        for args, _file in calls:
            assert args[-2:] == ("tag:x", "not:cleared")

    def test_side_appends_query(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_period_net_by_commodity

        calls = _capture(monkeypatch)
        load_period_net_by_commodity(
            tmp_path / "j.journal", "2024-03", query="tag:x"
        )
        assert calls[0][0][-1] == "tag:x"


class TestBreakdownLoaders:
    """Breakdowns append the query; liabilities has no period."""

    def test_expense_appends_query(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_expense_breakdown

        calls = _capture(monkeypatch)
        load_expense_breakdown(
            tmp_path / "j.journal", "2024-03", query="tag:x"
        )
        assert calls[0][0][-1] == "tag:x"

    def test_liabilities_appends_query(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_liabilities_breakdown

        calls = _capture(monkeypatch)
        load_liabilities_breakdown(tmp_path / "j.journal", query="tag:x")
        assert calls[0][0][-1] == "tag:x"


class TestReportLoaders:
    """IS/BS/CF and investment reports append the query last."""

    def test_report_appends_query(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_report

        calls = _capture(monkeypatch, output="")
        load_report(
            tmp_path / "j.journal", "is", query="tag:x",
        )
        assert calls[0][0][-1] == "tag:x"

    def test_investment_report_appends_query(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hledger_textual.hledger import load_investment_report

        calls = _capture(monkeypatch, output="")
        load_investment_report(tmp_path / "j.journal", query="tag:x")
        assert calls[0][0][-1] == "tag:x"
