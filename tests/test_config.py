"""Tests for configuration resolution."""

from pathlib import Path

import pytest

from hledger_tui.config import parse_args, resolve_journal_file


class TestParseArgs:
    """Tests for CLI argument parsing."""

    def test_file_short_flag(self):
        args = parse_args(["-f", "/some/file.journal"])
        assert args.file == "/some/file.journal"

    def test_file_long_flag(self):
        args = parse_args(["--file", "/some/file.journal"])
        assert args.file == "/some/file.journal"

    def test_no_args(self):
        args = parse_args([])
        assert args.file is None


class TestResolveJournalFile:
    """Tests for journal file resolution."""

    def test_cli_file_takes_priority(self, tmp_path: Path, monkeypatch):
        journal = tmp_path / "cli.journal"
        journal.write_text("")
        monkeypatch.setenv("LEDGER_FILE", str(tmp_path / "env.journal"))

        result = resolve_journal_file(cli_file=str(journal))
        assert result == journal.resolve()

    def test_env_variable(self, tmp_path: Path, monkeypatch):
        journal = tmp_path / "env.journal"
        journal.write_text("")
        monkeypatch.setenv("LEDGER_FILE", str(journal))

        result = resolve_journal_file()
        assert result == journal.resolve()

    def test_missing_cli_file_exits(self, tmp_path: Path):
        with pytest.raises(SystemExit):
            resolve_journal_file(cli_file=str(tmp_path / "nonexistent.journal"))

    def test_missing_env_file_exits(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LEDGER_FILE", str(tmp_path / "nonexistent.journal"))
        with pytest.raises(SystemExit):
            resolve_journal_file()

    def test_config_toml(self, tmp_path: Path, monkeypatch):
        """Test config.toml resolution."""
        journal = tmp_path / "toml.journal"
        journal.write_text("")

        config_dir = tmp_path / ".config" / "hledger-tui"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(f'journal_file = "{journal}"\n')

        monkeypatch.delenv("LEDGER_FILE", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        result = resolve_journal_file()
        assert result == journal.resolve()

    def test_default_path(self, tmp_path: Path, monkeypatch):
        """Test default ~/.hledger.journal fallback."""
        journal = tmp_path / ".hledger.journal"
        journal.write_text("")

        monkeypatch.delenv("LEDGER_FILE", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        result = resolve_journal_file()
        assert result == journal

    def test_no_file_found_exits(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("LEDGER_FILE", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with pytest.raises(SystemExit):
            resolve_journal_file()
