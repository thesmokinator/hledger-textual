"""Tests for the synthetic journal generator (issue #162)."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from scripts.generate_synthetic_journal import generate_journal, main


def _transaction_lines(path: Path) -> list[str]:
    """Return journal lines that start with an ISO date."""
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if len(line) >= 10 and line[:4].isdigit() and line[4] == "-"
    ]


class TestGenerateJournal:
    """Deterministic synthetic journal generation."""

    def test_exact_transaction_count(self, tmp_path: Path):
        """The generated journal contains exactly the requested transactions."""
        path = generate_journal(
            tmp_path / "j.journal", 25, seed=1, end=date(2026, 1, 31)
        )
        assert len(_transaction_lines(path)) == 25

    def test_deterministic_for_same_seed(self, tmp_path: Path):
        """Same seed and range produce byte-identical journals."""
        first = generate_journal(
            tmp_path / "a.journal", 100, seed=7, end=date(2026, 1, 31)
        )
        second = generate_journal(
            tmp_path / "b.journal", 100, seed=7, end=date(2026, 1, 31)
        )
        assert first.read_text() == second.read_text()

    def test_different_seed_changes_output(self, tmp_path: Path):
        """A different seed produces different contents."""
        first = generate_journal(
            tmp_path / "a.journal", 100, seed=7, end=date(2026, 1, 31)
        )
        second = generate_journal(
            tmp_path / "b.journal", 100, seed=8, end=date(2026, 1, 31)
        )
        assert first.read_text() != second.read_text()

    def test_zero_transactions(self, tmp_path: Path):
        """A zero-transaction journal is valid but has no transactions."""
        path = generate_journal(tmp_path / "empty.journal", 0, seed=1)
        assert _transaction_lines(path) == []

    def test_negative_transactions_raise(self, tmp_path: Path):
        """A negative count is rejected."""
        with pytest.raises(ValueError):
            generate_journal(tmp_path / "j.journal", -1)

    def test_end_before_start_raises(self, tmp_path: Path):
        """An inverted date range is rejected."""
        with pytest.raises(ValueError):
            generate_journal(
                tmp_path / "j.journal",
                1,
                start=date(2026, 2, 1),
                end=date(2026, 1, 1),
            )

    def test_cli_main_prints_path(self, tmp_path: Path, capsys):
        """The CLI entry point writes the journal and prints its path."""
        output = tmp_path / "cli.journal"
        assert main(["-n", "5", "-o", str(output), "--end", "2026-01-31"]) == 0
        assert output.exists()
        assert str(output) in capsys.readouterr().out

    @pytest.mark.skipif(
        shutil.which("hledger") is None, reason="hledger not installed"
    )
    def test_generated_journal_is_valid(self, tmp_path: Path):
        """Generated output passes hledger's own validation."""
        path = generate_journal(
            tmp_path / "valid.journal", 200, seed=3, end=date(2026, 1, 31)
        )
        subprocess.run(
            ["hledger", "--no-conf", "-f", str(path), "check"],
            check=True,
            capture_output=True,
        )


class TestBenchmarkAllTimeFlag:
    """The --all-time scenario flag parses correctly."""

    def test_flag_defaults_off(self) -> None:
        from scripts.benchmark_perf import _build_parser

        assert _build_parser().parse_args([]).all_time is False

    def test_flag_enables_scenario(self) -> None:
        from scripts.benchmark_perf import _build_parser

        args = _build_parser().parse_args(["--all-time"])
        assert args.all_time is True
